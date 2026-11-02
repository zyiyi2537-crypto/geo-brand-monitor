/**
 * Shared API error extraction helpers.
 *
 * The backend returns errors in two shapes depending on the exception class:
 *
 * - FastAPI `HTTPException`      → `{"detail": "..."}`
 * - Our custom `AppException`    → `{"error": {"code": 429, "message": "..."}}`
 *
 * Callers used to only read `body.detail || body.message`, so any AppException
 * fell through to the hardcoded English fallback and the real backend message
 * (e.g. "Monthly quota exceeded") never reached the user. These helpers
 * normalize both shapes so pages can surface the real reason the request
 * failed.
 */

export function extractBackendMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback;
  const obj = body as Record<string, any>;
  // FastAPI HTTPException(422, dict) 会把 dict 整个塞进 detail —
  // 比如 _validate_topic_runnable 抛 {"code": "PROFILE_INCOMPLETE", "message": "资料必填项缺失", "missing": [...]}.
  // 之前只接收 detail 是字符串的情况,object detail 会 fall through 到 fallback,真错被吞.
  const fromDetail =
    typeof obj.detail === 'string'
      ? obj.detail
      : obj.detail && typeof obj.detail === 'object' && typeof (obj.detail as any).message === 'string'
        ? (obj.detail as any).message
        : null;
  const fromNested =
    obj.error && typeof obj.error === 'object' && typeof obj.error.message === 'string'
      ? obj.error.message
      : null;
  const fromMessage = typeof obj.message === 'string' ? obj.message : null;
  return fromDetail || fromNested || fromMessage || fallback;
}

export async function readApiError(response: Response, fallback: string): Promise<string> {
  try {
    return extractBackendMessage(await response.json(), fallback);
  } catch {
    return fallback;
  }
}

/** Axios variant: pulls `error.response.data` and runs the same extraction. */
export function extractAxiosErrorMessage(error: unknown, fallback: string): string {
  const data = (error as any)?.response?.data;
  return extractBackendMessage(data, fallback);
}

/**
 * Current UI language as stored by i18next. Used to set `X-Locale` on outgoing
 * API requests so the backend can return localized error messages (see
 * `backend/geo/utils/error_i18n.py`). Falls back to "zh" because that is the
 * i18next default in `frontend/src/i18n/index.ts`.
 */
export function currentLocale(): string {
  try {
    return localStorage.getItem('i18nextLng') || 'zh';
  } catch {
    return 'zh';
  }
}

/**
 * Build request headers with the locale attached. Accepts any extra headers
 * (auth tokens, content type) and merges them on top of the locale header.
 */
export function localizedHeaders(
  extra: Record<string, string> = {},
): Record<string, string> {
  return { 'X-Locale': currentLocale(), ...extra };
}
