# infra/foundation

Foundation-owned repository and architecture guardrails. FOUND-003A adds PostgreSQL configuration parsing, non-secret health snapshots and a synthetic connection fixture; FOUND-003B adds S3-compatible configuration and a private, in-memory Fake Storage port; FOUND-003D adds PostgreSQL task-job polling configuration and an injectable DB-API queue seam; FOUND-006A adds no-network health aggregation and bounded Prometheus-compatible technical/business metrics; FOUND-006B adds local-by-default OpenTelemetry tracing, W3C propagation and an injectable append-only cost sink. Concrete drivers, pools, Redis, remote telemetry exporters and vendor SDKs remain with later task owners.

This directory is a V2 boundary created by FOUND-001. Add implementation only under the owning task card and preserve the synthetic/account-free constraints.
