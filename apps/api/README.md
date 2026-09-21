# apps/api

HTTP/API composition root; it will validate requests, build TenantContext and call public use cases. Runtime entry wiring belongs to FOUND-002, while PostgreSQL configuration-only readiness belongs to FOUND-003A.

## Boundaries

- Depend on registered contracts and public use cases.
- Keep credentials, raw tokens and provider-specific facts out of this directory.
- Do not implement adjacent tasks before their task card is active.
