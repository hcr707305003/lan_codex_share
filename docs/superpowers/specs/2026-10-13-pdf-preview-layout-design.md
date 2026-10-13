# PDF preview layout — approved option A

User approved the lightweight layout on 2026-10-13 after reviewing the mockup.

- Keep the browser-native PDF viewer, existing resize handle and ZIP APIs.
- Combine directory navigation, return-to-list and downloads in one compact, wrapping toolbar.
- PDF fills the space below the toolbar; no permanent fallback warning above it.
- Keep fallback text inside the PDF object and keep download links available on failure.
- Allow long filenames without widening the panel. On narrow panels the toolbar can wrap.
- Other ZIP member types retain scrolling; returning to a list must not retain PDF-only layout.
- No new dependencies, service restart, commit, packaging or release in this task.

Validate DOM behavior with Node tests, route/CSP regressions with Python tests, and real-browser layout at wide/narrow panel sizes. Native viewer internals are browser-owned and not restyled.
