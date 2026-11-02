# Frontend Internationalization Contract

Owner: frontend
Last reviewed: 2026-08-28

The React SPA supports Simplified Chinese (`zh`) and English (`en`).
Translation resources and locale loading live under `frontend/src/i18n/`.

## Current behavior

- The initial locale comes from `i18nextLng` in browser storage, then the
  browser language, then English.
- The selected locale is persisted in browser storage.
- Main, result, and knowledge packs are loaded dynamically for the active
  language.
- `fallbackLng` is intentionally disabled. English is **not** loaded as a
  missing-key fallback.
- Key parity between Chinese and English is therefore a release requirement.
- API values, brand names, URLs, and code identifiers are not translated.
- Outgoing API requests include the active locale in `X-Locale`.

## Review checklist

1. Add every new key to both language resources.
2. Verify that no raw translation keys appear when a lazy namespace loads.
3. Verify desktop and mobile layouts with longer English strings.
4. Check date, number, currency, and plural formatting.
5. Confirm that refresh preserves the selected locale.
6. Verify backend error responses in both locales.
7. Run frontend lint and the production build.

If fallback behavior changes, update this document and
`frontend/src/i18n/index.ts` together.
