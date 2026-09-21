from __future__ import annotations

import pytest

from infra.foundation.database import ConnectionFixture, create_connection_fixture


@pytest.fixture
def synthetic_database_connection() -> ConnectionFixture:
    """Provide an in-memory DB-API connection without PostgreSQL/network access."""
    with create_connection_fixture() as fixture:
        yield fixture
