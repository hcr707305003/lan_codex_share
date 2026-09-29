# Public entry icons

Approved design: compact blue FRP tunnel and orange cloud SVG symbols beside the sidebar brand. Show configured origins only when the respective local runtime is detected. Tooltip explicitly says process detected, public connectivity unverified. Open a new tab with the current session query. No tunnel startup/termination or public connectivity probe.

Implementation: authenticated `/api/public-entries` returns only kind/origin; cached process inspection excludes help/version/management commands. Frontend polls only when authenticated and visible, hides stale results on failure, renders accessible links using existing SVG sprites/CSS (no inline style/CSP weakening). Detecting the process does not establish that its configuration targets this Share instance; tooltip states that limitation.

- [x] Add process detector and authenticated route with tests.
- [x] Add SVG symbols and compact links, polling and current-session URL updates.
- [x] Verify running/stopped/unknown states, unauthorized access, desktop/mobile layout and session preservation.
- [x] Full tests: 828 Python and 60 JavaScript passed. Desktop and 375px mobile browser checks passed against fake entry responses, including session switching and hiding stopped entries.
- [x] Version notes prepared for v0.4.1; the already pushed v0.4.0 tag remains unchanged. Release completion is tracked by the tag workflow.

Additional user request: add proxy path instructions in entry tooltips and README, with same-origin public URL examples and an explicit explanation that localhost is the Share machine.
