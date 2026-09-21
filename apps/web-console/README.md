# apps/web-console

Web Console build boundary for operations, approvals, knowledge and metrics. It calls the public API and never connects to the database.

## Boundaries

- Depend on registered contracts and public use cases.
- Keep credentials, raw tokens and provider-specific facts out of this directory.
- Do not implement adjacent tasks before their task card is active.

