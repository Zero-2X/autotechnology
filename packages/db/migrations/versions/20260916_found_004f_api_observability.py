"""Record the FOUND-005 API observability contract checkpoint.

This compatibility revision follows the accepted FOUND-004E head naming.  The
correlation context, API errors, and structured logs are request/runtime
concerns and do not require a persisted database object in this phase.
"""

from __future__ import annotations


revision = "20260916_found_004f"
down_revision = "20260916_found_004e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
