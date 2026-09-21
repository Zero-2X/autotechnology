"""SITE-003 records a projection-only structured-data renderer revision.

JSON-LD is generated from immutable site page snapshots and is not stored as a
new content fact.  The no-op revision keeps the migration chain and release
evidence aligned without adding a table or changing SITE-001/SITE-002 data.
"""

revision = "20260919_found_site_003"
down_revision = "20260919_found_site_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No database object: structured data is a deterministic read projection."""


def downgrade() -> None:
    """Keep the revision chain reversible; no object is removed."""
