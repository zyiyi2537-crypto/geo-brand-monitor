# URL and Outbound Fetch Security Contract

Owner: backend GEO API and frontend URL-entry components
Last reviewed: 2026-08-28

This contract separates two controls that must not be treated as equivalent:

1. URL syntax validation, which is shared by the frontend and backend.
2. Outbound fetch authorization, which is a server-side security boundary.

## Current implementation status

The syntax rules below are implemented by
`frontend/src/utils/validateUrl.ts` and
`backend/geo/utils/validator.py::validate_url`.

The required outbound-address controls are **not yet implemented centrally**.
Until they are, accepting arbitrary user-supplied URLs on a network that can
reach private services carries SSRF risk. Syntax validation alone does not make
a URL safe to fetch.

## URL syntax rules

1. The normalized URL must use `http` or `https`.
2. The hostname must contain at least one dot.
3. The hostname uses ASCII LDH characters: letters, digits, hyphens, and dots.
4. Every hostname label starts and ends with an alphanumeric character.
5. IDN, non-ASCII, emoji, and IPv6 host input is currently rejected.
6. Ports, paths, and query strings are allowed.
7. The frontend adds `https://` when the user omits a scheme. Backend callers
   must submit a normalized URL.

### Syntax cases

| Input | Syntax result | Notes |
| --- | --- | --- |
| `example.com` | Frontend pass | Normalized to `https://example.com` |
| `https://example.com/path?q=1` | Pass | Path and query are allowed |
| `https://sub.example.com:8080` | Pass | Subdomain and port are allowed |
| `http://192.168.1.1` | Syntax pass | Must be rejected by outbound authorization |
| `hello` | Reject | Host has no dot |
| `ftp://example.com` | Reject | Unsupported scheme |
| `https://example-.com` | Reject | Label ends with a hyphen |
| `https://-example.com` | Reject | Label starts with a hyphen |
| `https://example .com` | Reject | Contains a space |
| `https://[::1]` | Reject | IPv6 is not supported by the current syntax |
| `淘宝.中国` | Reject | IDN input is not currently supported |
| `javascript:alert(1)` | Reject | Unsupported scheme |

## Required outbound-fetch authorization

Before the backend opens a connection, it must:

- resolve every hostname and reject loopback, private, link-local, multicast,
  reserved, unspecified, and cloud-metadata destinations;
- validate every resolved address, not only the hostname string;
- repeat resolution and validation after every redirect;
- prevent a validated public hostname from being swapped to a private address
  between validation and connection;
- apply bounded redirects, response-size limits, connection/read timeouts, and
  an explicit port policy;
- use the same policy in the default checker, advanced modes, browser workers,
  and any proxy that accepts a target URL;
- log a safe rejection reason without recording credentials embedded in URLs.

Whether public IPv4 literals are supported should be an explicit product
decision. Private and special-use address ranges must never pass merely because
their textual URL syntax is valid.

## Verification

- Keep a shared fixture covering every syntax case above.
- Add backend tests for IPv4 and IPv6 special-use ranges, DNS rebinding, and
  redirects from a public URL to a private destination.
- Run the same syntax fixture against both frontend and backend implementations.
- Treat a change to either syntax or outbound policy as a contract change and
  update this document in the same pull request.
