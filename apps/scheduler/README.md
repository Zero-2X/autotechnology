# apps/scheduler

Scheduler composition root; it will create or wake jobs and will not implement domain decisions.

## Boundaries

- Depend on registered contracts and public use cases.
- Keep credentials, raw tokens and provider-specific facts out of this directory.
- Do not implement adjacent tasks before their task card is active.

