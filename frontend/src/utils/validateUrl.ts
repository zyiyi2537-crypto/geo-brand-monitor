// See docs/contracts/url-and-outbound-fetch-security.md for the shared syntax
// contract. The backend must separately authorize resolved network addresses.
// Must stay in sync with backend/geo/utils/validator.py::validate_url —
// identical rule, identical cases.
//
// Rule: ASCII only; scheme http/https; hostname is LDH with at least one dot
// (each label starts/ends with alnum, hyphens allowed internally). IDN /
// non-ASCII / emoji domains are rejected — add idna conversion both sides
// before relaxing this.

const HOST_RE =
  /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)+$/;

const ASCII_ONLY = /^[\x00-\x7F]+$/;

export const normalizeUrl = (input: string): string => {
  const trimmed = input.trim();
  if (!trimmed) return trimmed;
  return trimmed.startsWith('http://') || trimmed.startsWith('https://')
    ? trimmed
    : `https://${trimmed}`;
};

export const validateUrl = (input: string): boolean => {
  const url = normalizeUrl(input);
  if (!url || !ASCII_ONLY.test(url)) return false;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false;
  // URL.hostname lowercases and, for IDN input, already returns punycode —
  // but because we reject non-ASCII above, we only ever see plain LDH here.
  return HOST_RE.test(parsed.hostname);
};
