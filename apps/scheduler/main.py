"""Dry-run Scheduler composition root for FOUND-002.

Job creation and wake-up persistence belong to later scheduler tasks.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SchedulerTick:
    status: str
    service: str
    dry_run: bool
    created_jobs: int
    reason: str


def run_once(*, dry_run: bool) -> SchedulerTick:
    return SchedulerTick(
        status="ok",
        service="scheduler",
        dry_run=dry_run,
        created_jobs=0,
        reason="no_due_jobs; scheduler persistence belongs to later tasks",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FOUND-002 Scheduler composition root")
    parser.add_argument("--once", action="store_true", help="execute one scheduling iteration")
    parser.add_argument("--dry-run", action="store_true", help="disable persistence and external side effects")
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("FOUND-002 only supports --once until scheduler persistence is implemented")
    if not args.dry_run:
        parser.error("--dry-run is required until scheduler persistence is implemented")
    print(json.dumps(asdict(run_once(dry_run=args.dry_run)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
