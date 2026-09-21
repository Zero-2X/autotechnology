from __future__ import annotations

from infra.foundation.database import ConnectionFixture


def test_synthetic_database_connection_supports_local_transaction(
    synthetic_database_connection: ConnectionFixture,
) -> None:
    fixture = synthetic_database_connection
    fixture.connection.execute("CREATE TABLE health_fixture (value INTEGER NOT NULL)")
    fixture.connection.execute("INSERT INTO health_fixture VALUES (1)")
    row = fixture.connection.execute("SELECT value FROM health_fixture").fetchone()
    assert row == (1,)
    assert fixture.settings.source == "synthetic_fixture"
