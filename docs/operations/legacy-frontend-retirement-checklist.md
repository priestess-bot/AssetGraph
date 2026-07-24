# Legacy Frontend Route Migration And Retirement Checklist

> Scope: browser entry routes only. `/api/maitu/*` and `/api/live-research/*`
> remain supported domain APIs and are not renamed by this migration.
> Status: redirect active; legacy static assets retained for cached clients;
> retirement approval remains open.

## Canonical Mapping

| Legacy entry | Stable Console route | Query mapping |
| --- | --- | --- |
| `/maitu/` or `view=production` | `/production/live-rooms` | Remove `view`; preserve `run`, immutable `reference_template_*` pins and all other deep-link parameters. |
| `/maitu/?view=resources` | `/assets/library` | Remove `view`; preserve `asset` and all other parameters. |
| `/maitu/?view=gemini` | `/assets/library?panel=analysis` | Remove `view`; force `panel=analysis`; preserve `run` and all other parameters. |
| `/live-research/` or `view=watch` | `/research/live-sources` | Canonicalize the default by removing `view`; preserve source parameters. |
| `/live-research/?view=sessions` | `/research/live-sources?view=sessions` | Preserve `session` and other timeline parameters. |
| `/live-research/?view=drafts` | `/research/live-sources?view=drafts` | Preserve `template` and other review parameters. |
| `/live-research/?view=published` | `/research/live-sources?view=published` | Preserve `template` and immutable projection references. |

Unknown legacy `view` values fail to the former default view and are removed.
Repeated non-routing query keys and blank values are preserved. Only `GET` and
`HEAD` receive permanent redirects, so this layer cannot replay mutation bodies.

## Functional Equivalence

- [x] Stable production uses the same `ProductionPage` component and `/api/maitu/workbench/*` calls as the legacy production view.
- [x] Stable asset resources use the same `ResourcesPage` component and APIs as `view=resources`.
- [x] Stable asset analysis uses the same `GeminiPage` component and APIs as `view=gemini`.
- [x] Stable live research reuses `WatchPage`, `SessionsPage` and `TemplatesPage` for all four views.
- [x] Stable routes are served by the shared Console shell on desktop and mobile.
- [x] Published-template production handoff now targets `/production/live-rooms` with a complete immutable template pin.
- [x] Route tests cover both slash forms, every view, default/unknown views, repeated parameters and production/session/template deep links.
- [x] Legacy entry redirects are registered before static mounts and return `308`.
- [x] Cached legacy JS/CSS can still load from the retained `/maitu/*` and `/live-research/*` static mounts during observation.

## Rollout Observation

- [ ] Name the engineering and product owners for the observation window.
- [ ] Add privacy-safe counters for legacy root hits, redirect target, response status and user-agent class; never record token-like query values.
- [ ] Confirm internal navigation, template handoffs, documentation and operator bookmarks use stable routes.
- [ ] Exercise representative production, resource, analysis, watch, session, draft and published workflows against non-demo data.
- [ ] Verify redirects behind the production proxy/CDN, including encoded Chinese text, repeated keys and blank values.
- [ ] Confirm no monitored redirect loop, elevated 4xx/5xx rate or material task-completion regression.
- [ ] Observe zero required legacy-root use for the owner-approved representative operating window.
- [ ] Inventory external bookmarks/embedded links and record each migrated consumer or explicit exception.

## Retirement Gate

- [ ] Product confirms functional equivalence for all mapped workflows.
- [ ] Engineering confirms legacy entry traffic meets the agreed zero-use threshold and rollback is tested.
- [ ] Design/accessibility confirms the Console shell does not regress keyboard, focus, responsive or screen-reader behavior.
- [ ] Operations confirms runbooks, support links and dashboards use stable routes.
- [ ] Security confirms redirects do not expose sensitive query values in logs or analytics.
- [ ] Remove the legacy Vite entry builds only after the preceding approvals.
- [ ] Remove legacy static mounts only after cached-client and rollback windows close.
- [ ] Add explicit `410 Gone` or documented terminal redirects if policy requires them; do not silently serve an unrelated page.
- [ ] Archive before/after route tests, traffic evidence, approvals, rollback result and known exceptions in the Phase acceptance package.

Rollback before retirement is to disable the exact root redirect routes and let
the retained static mounts serve the old shells. API routes and canonical domain
records are unchanged, so rollback must not rewrite data or replay commands.
