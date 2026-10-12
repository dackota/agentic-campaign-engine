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

from ace_engine import db

TEAM_ROLE = "ace_team"
TEAM_SETTING = "ace.team"
# The execution option that carries a request's team to its database session.
TEAM_OPTION = "ace_team"
# Workflows and platform alerts belong to no team.
SHARED_TABLES = frozenset({db.WorkflowVersion.__tablename__, db.Alert.__tablename__})
# Tables with their own team column; the other team tables reach theirs through a campaign.
TEAM_KEYED_TABLES = frozenset({db.Campaign.__tablename__, db.StepCacheEntry.__tablename__})
# One installer at a time: the API and the worker can start together.
_INSTALL_LOCK = 4_040_040
_CURRENT_TEAM = f"current_setting('{TEAM_SETTING}', true)"
_OWN_CAMPAIGN = (
    f"EXISTS (SELECT 1 FROM campaigns c WHERE c.id = campaign_id AND c.team = {_CURRENT_TEAM})"
)


def team_tables() -> list[str]:
    """Every table but the shared ones: each holds one team's rows."""
    return sorted(set(db.Base.metadata.tables) - SHARED_TABLES)


def _policy_condition(table: str) -> str:
    """Campaigns and the step cache carry their team; every other team table belongs to a
    campaign."""
    if table in TEAM_KEYED_TABLES:
        return f"team = {_CURRENT_TEAM}"
    return _OWN_CAMPAIGN


def install(engine: Engine) -> None:
    """Create the team role, grant it the tables, and turn row-level security on with one
    policy per team table. Safe to run on every start: each run puts the same rules back."""
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INSTALL_LOCK})
        conn.execute(
            text(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{TEAM_ROLE}') "
                f"THEN CREATE ROLE {TEAM_ROLE} NOLOGIN; END IF; END $$"
            )
        )
        is_superuser = conn.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
        if not is_superuser:
            conn.execute(text(f"GRANT {TEAM_ROLE} TO CURRENT_USER"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {TEAM_ROLE}"))
        for table in db.Base.metadata.tables:
            conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {TEAM_ROLE}"))
        conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {TEAM_ROLE}"))
        for table in team_tables():
            _install_policy(conn, table)


def _install_policy(conn: Connection, table: str) -> None:
    policy = f"{table}_by_team"
    condition = _policy_condition(table)
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    conn.execute(
        text(
            f"CREATE POLICY {policy} ON {table} TO {TEAM_ROLE} "
            f"USING ({condition}) WITH CHECK ({condition})"
        )
    )


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
    conn.execute(text(f"SET LOCAL ROLE {TEAM_ROLE}"))
    conn.execute(
        text("SELECT set_config(:name, :team, true)"), {"name": TEAM_SETTING, "team": team}
    )
