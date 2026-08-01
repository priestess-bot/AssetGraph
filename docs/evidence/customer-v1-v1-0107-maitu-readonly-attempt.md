# V1-0107 Maitu Read-only Canary Record

## 2026-07-31 Closure

The current authenticated account successfully read the real test room `41172`
from the Maitu working environment. The authoritative result was title
`asser测试`, `status=0`, `live_session_id=null`, and
`latest_live_time=null`. The adapter contract was
`maitu-web-working-room.internal.v1`, with acceptance-time matrix fingerprint
`c19b5ca196033d248df2419d9dec56348a67100ea2c9a30abccfb69c4a4c1213`.

The same room then completed the controlled mutation canary and an independent
readback after reopening the page. Full evidence is in
`docs/evidence/maitu-41172-zhangyu-pro-rebuild-attempt.md` and
`docs/evidence/maitu-41172-zhangyu-pro-final-readback.json`. `V1-0107` is now
closed. The 2026-07-26 failed-login attempt remains below as historical
evidence.

Date: 2026-07-26
Target: protected reference room `38336`
Adapter contract: `maitu-web-working-room.internal.v1`

## Safety Boundary

Only `browser_use_worker --probe-maitu` and `--observe-maitu` were used. The
browser opened the already registered protected reference URL. No click, input,
upload, scene operation, script write, save, API write-back, or go-live command
was issued. The temporary Chrome process was terminated after the check.

## Result

1. With no CDP browser listening, the first probe failed locally with `All
   connection attempts failed`; it did not reach Maitu.
2. A read-only Chrome session was started on loopback CDP `9222` with the
   project-specific profile and room URL.
3. The initial fast probe exposed a defect: generic Maitu title/URL markers could
   be classified as logged in before the SPA redirect settled.
4. Stable observation reached `https://live2.maituai.com/Login` and returned
   `logged_in=false`, `login_required=true`, with no room ID/name or scenes.
5. The probe was fixed to require authenticated body markers and to reread an
   empty Maitu shell. The real probe was repeated and correctly returned exit
   code 2, `/Login`, `logged_in=false`, and `login_required=true`.

## Regression Evidence

- `uv run pytest -q tests/test_browser_cli_session.py tests/test_cli.py --tb=short`:
  100 passed.
- `uv run ruff check src/browser_use_worker/browser_cli_session.py
  tests/test_browser_cli_session.py`: passed.

## Checklist Decision

`V1-0107` remains open. The current profile is logged out, so no current room
title/status readback or authenticated canary artifact can be produced. Maitu
`read_room` remains `manual_only`; this attempt must not be represented as a
successful external capability validation.

To close the item, an operator must log in through the visible project browser,
then rerun the read-only probe and stable observation for an approved room while
recording the current capability matrix fingerprint.
