# Course Markdown workspace

Implement the requested standalone course-body editor inline in this session.

- Fix content picker spacing on body-mounted dialogs using scoped dialog selectors and a responsive two-column grid.
- Add a validated `/markdown/<lesson>/<new|asset>` classroom route; both create and edit use the standalone workspace and existing authorization and asset APIs.
- Provide document name, import `.md`, save and return controls. Desktop shows Markdown source and safe server-rendered preview side by side; mobile offers source/preview tabs. Debounce compilation and ignore obsolete responses. Preserve image paste and math rendering.
- Import UTF-8 Markdown with BOM support; imported text remains editable before save. Preserve existing content on import errors. Keep a per-user/session draft on navigation and clear only after successful save.
- Verify route parsing, preview races/errors/disposal, file decoding, existing Markdown API permissions, and browser workflows including narrow viewports. Close all test browsers/services afterward.
