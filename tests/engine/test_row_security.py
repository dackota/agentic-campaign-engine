"""The row-level security DDL names tables, policies, and the role. DDL identifiers cannot
be bound parameters, so each one is quoted by the dialect's identifier preparer."""

from ace_engine import row_security
from sqlalchemy import create_engine

# Never connects: only its dialect's identifier preparer is used.
PREPARER = create_engine("postgresql+psycopg://").dialect.identifier_preparer
HOSTILE = 'runs"; DROP TABLE campaigns; --'


def test_every_identifier_in_the_policy_ddl_is_quoted() -> None:
    statements = row_security.policy_statements(PREPARER, HOSTILE)

    quoted_table = '"runs""; DROP TABLE campaigns; --"'
    assert all(quoted_table in s for s in statements)
    assert all('"ace_team"' in s for s in statements if s.startswith("CREATE POLICY"))
    assert not any(f" {HOSTILE} " in s or s.endswith(HOSTILE) for s in statements)


def test_every_identifier_in_the_grants_is_quoted() -> None:
    statements = row_security.grant_statements(PREPARER, [HOSTILE])

    assert any('"runs""; DROP TABLE campaigns; --"' in s for s in statements)
    assert all('"ace_team"' in s for s in statements)
