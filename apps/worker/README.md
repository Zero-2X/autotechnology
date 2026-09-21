# apps/worker

Worker composition root. `runtime.py` leases `TaskJob` records, invokes registered
application handlers, maintains cooperative heartbeats, routes every failure
through the transactional failure facade, and optionally dispatches Outbox
events in bounded batches. It does not copy domain rules.

## Boundaries

- Depend on registered contracts and public use cases.
- Long-running synchronous handlers call `WorkerExecutionContext.checkpoint()`
  to observe shutdown/timeout and renew their lease.
- Scale concurrency with multiple worker processes; each runtime bounds the
  number of leases it reserves using `batch_size`, `max_in_flight`, and the
  injected capacity provider.
- Keep credentials, raw tokens and provider-specific facts out of this directory.
- Do not implement adjacent tasks before their task card is active.
