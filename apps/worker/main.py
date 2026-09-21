"""Worker process entry and dependency composition seam.

The repository CLI remains an account-free smoke probe. A deployment host uses
``create_worker_runtime`` to provide its database stores, registered application
handlers and optional Outbox dispatcher without putting credentials in code.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Callable, Mapping

from infra.foundation.task_claim import TaskClaimStore
from infra.foundation.task_failure_facade import TaskFailureFacade

from .runtime import (
    Clock,
    OutboxDispatcherLike,
    ShutdownToken,
    Sleeper,
    TaskHandler,
    WorkerRuntime,
    WorkerSettings,
)


@dataclass(frozen=True)
class WorkerTick:
    status: str
    service: str
    dry_run: bool
    leased_jobs: int
    reason: str


def create_worker_runtime(
    *,
    settings: WorkerSettings,
    claim_store: TaskClaimStore,
    failure_facade: TaskFailureFacade,
    handlers: Mapping[str, TaskHandler],
    outbox_dispatcher: OutboxDispatcherLike | None = None,
    shutdown: ShutdownToken | None = None,
    clock: Clock | None = None,
    sleeper: Sleeper | None = None,
    capacity_provider: Callable[[], int] | None = None,
) -> WorkerRuntime:
    """Build the runnable worker from explicit, already-authorized dependencies."""
    kwargs = {}
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    return WorkerRuntime(
        settings=settings,
        claim_store=claim_store,
        failure_facade=failure_facade,
        handlers=handlers,
        outbox_dispatcher=outbox_dispatcher,
        shutdown=shutdown,
        clock=clock,
        capacity_provider=capacity_provider,
        **kwargs,
    )


def run_once(*, dry_run: bool) -> WorkerTick:
    return WorkerTick(
        status="ok",
        service="worker",
        dry_run=dry_run,
        leased_jobs=0,
        reason="no_jobs; account_free_probe; deployment host injects stores and handlers via create_worker_runtime",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker composition entry")
    parser.add_argument("--once", action="store_true", help="execute one poll iteration")
    parser.add_argument("--dry-run", action="store_true", help="disable queue and external side effects")
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("the account-free CLI probe requires --once")
    if not args.dry_run:
        parser.error("--dry-run is required because the repository CLI does not load deployment credentials")
    print(json.dumps(asdict(run_once(dry_run=args.dry_run)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
