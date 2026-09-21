# apps/knowledge-site

First-party knowledge-site build boundary. It reads through public API/contracts and does not become a separate domain service.

`scripts/site_page.py` implements the SITE-001 application projection rules. It
normalizes canonical paths and immutable page metadata through a repository
port; it does not contain SQL or reach into domain storage.

`scripts/site_render.py` implements the SITE-002 deterministic renderer. It
accepts tenant-scoped `SitePageVersion` snapshots and emits escaped SSR HTML,
canonical and hreflang links, sitemap XML, RSS, Atom, and robots text. The
renderer is offline and side-effect free; `InMemorySiteRenderStore` is only an
idempotency/audit fixture. It never emits JSON-LD.

For GEO_REGION-002 the renderer accepts an optional `eligibility_port` (or
`region_filter` alias). Pages are checked before route selection, so blocked,
expired, missing-version and manual-review pages cannot enter HTML alternates,
`x-default`, sitemap, RSS or Atom. Without the port, SITE-002 behavior remains
compatible with existing callers.

`scripts/site_structured_data.py` implements SITE-003. It projects the same
tenant-scoped page snapshot into deterministic Article or TechArticle,
Organization, and Person JSON-LD. VideoObject stays behind the phase-6 and
approved-asset gate. Script text escapes HTML delimiters, and the service has
no database, network, credential, or publishing access.

`scripts/site_quality.py` implements SITE-004 as an offline audit boundary.
It checks page/link HTTP observations, bounded redirects, performance budgets,
image alt text, media captions, SSR content and optional dynamic DOM parity.
Observations come from the caller or an explicitly injected probe port; the
default service performs no network or browser work. Reports retain stable
codes, metrics and hashes only, while `site_quality_reports` stores an
append-only tenant-scoped projection without raw HTML or DOM content.

## Boundaries

- Depend on registered contracts and public use cases.
- Keep credentials, raw tokens and provider-specific facts out of this directory.
- Do not implement adjacent tasks before their task card is active.
- Keep rendered output reproducible from the source snapshot, origin, renderer version, and fixed clock.
