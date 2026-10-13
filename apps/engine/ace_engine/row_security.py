"""Team isolation in the database itself: row-level security on every team table.

A request of a signed-in user runs as the `ace_team` role with the setting `ace.team` set to
the user's team (`for_team`). The policies then show and accept only that team's rows, so
the API's queries name no team. The worker and the signed webhooks connect as the tables'
owner, which row-level security does not filter: they act for the system, not for a team.
The step cache is the exception: the worker reads and writes it through `for_team`, so the
database keeps one team's saved outputs from another.
Workflows and platform alerts are shared by every team and have no policy
(docs/decisions/team-isolation.md).
"""

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.sql.compiler import IdentifierPreparer

from ace_engine import db

TEAM_ROLE = "ace_team"
TEAM_SETTING = "ace.team"
# The schema the tables live in.
SCHEMA = "public"
# The execution option that carries a request's team to its database session.
TEAM_OPTION = "ace_team"
# Workflows and platform alerts belong to no team.
SHARED_TABLES = frozenset({db.WorkflowVersion.__tablename__, db.Alert.__tablename__})
# Tables with their own team column; the other team tables reach theirs through a campaign.
TEAM_KEYED_TABLES = frozenset({db.Campaign.__tablename__, db.StepCacheEntry.__tablename__})
# One installer at a time: the API and the worker can start together.
_INSTALL_LOCK = 4_040_040
# The setting is a constant, never caller input; it is the one literal in the policy SQL.
_CURRENT_TEAM = f"current_setting('{TEAM_SETTING}', true)"


def team_tables() -> list[str]:
    """Every table but the shared ones: each holds one team's rows."""
    return sorted(set(db.Base.metadata.tables) - SHARED_TABLES)


def _policy_condition(preparer: IdentifierPreparer, table: str) -> str:
    """Campaigns and the step cache carry their team; every other team table belongs to a
    campaign."""
    team = preparer.quote_identifier("team")
    if table in TEAM_KEYED_TABLES:
        return f"{team} = {_CURRENT_TEAM}"
    campaigns = preparer.quote_identifier(db.Campaign.__tablename__)
    campaign_id = preparer.quote_identifier("campaign_id")
    id_ = preparer.quote_identifier("id")
    return (
        f"EXISTS (SELECT 1 FROM {campaigns} c "  # noqa: S608  only quoted identifiers; values stay bound
        f"WHERE c.{id_} = {campaign_id} AND c.{team} = {_CURRENT_TEAM})"
    )


def install(engine: Engine) -> None:
    """Create the team role, grant it the tables, and turn row-level security on with one
    policy per team table. Safe to run on every start: each run puts the same rules back.
    DDL cannot take bound parameters, so every identifier goes through the dialect's
    identifier preparer; values (the role name in the lookup, the team) stay bound."""
    with engine.begin() as conn:
        preparer = conn.dialect.identifier_preparer
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INSTALL_LOCK})
        has_role = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": TEAM_ROLE}
        ).first()
        if has_role is None:
            conn.execute(text(f"CREATE ROLE {preparer.quote_identifier(TEAM_ROLE)} NOLOGIN"))
        is_superuser = conn.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
        if not is_superuser:
            conn.execute(text(f"GRANT {preparer.quote_identifier(TEAM_ROLE)} TO CURRENT_USER"))
        for statement in grant_statements(preparer, list(db.Base.metadata.tables)):
            conn.execute(text(statement))
        for table in team_tables():
            for statement in policy_statements(preparer, table):
                conn.execute(text(statement))


def grant_statements(preparer: IdentifierPreparer, tables: list[str]) -> list[str]:
    """What the team role may touch: the schema, every table, and their sequences."""
    role = preparer.quote_identifier(TEAM_ROLE)
    schema = preparer.quote_identifier(SCHEMA)
    return [
        f"GRANT USAGE ON SCHEMA {schema} TO {role}",
        *(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {preparer.quote_identifier(t)} TO {role}"
            for t in tables
        ),
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}",
    ]


def policy_statements(preparer: IdentifierPreparer, table: str) -> list[str]:
    """Row-level security on `table` and its one policy, put back from scratch."""
    quoted = preparer.quote_identifier(table)
    policy = preparer.quote_identifier(f"{table}_by_team")
    role = preparer.quote_identifier(TEAM_ROLE)
    condition = _policy_condition(preparer, table)
    return [
        f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {policy} ON {quoted}",
        f"CREATE POLICY {policy} ON {quoted} TO {role} "
        f"USING ({condition}) WITH CHECK ({condition})",
    ]


def for_team(engine: Engine, team: str | None) -> Engine:
    """The engine a request of `team` uses: every transaction on it runs as the team role
    with the team set, so the database shows it only the team's rows. No team sees nothing."""
    return engine.execution_options(**{TEAM_OPTION: team or ""})


@event.listens_for(Session, "after_begin")
def _set_team(_session: Session, _transaction: SessionTransaction, conn: Connection) -> None:
    team = conn.get_execution_options().get(TEAM_OPTION)
    # Row-level security is Postgres's: an SQLite test database has no roles to set.
    if team is None or conn.dialect.name != "postgresql":
        return
    conn.execute(
        text(f"SET LOCAL ROLE {conn.dialect.identifier_preparer.quote_identifier(TEAM_ROLE)}")
    )
    conn.execute(
        text("SELECT set_config(:name, :team, true)"), {"name": TEAM_SETTING, "team": team}
    )
