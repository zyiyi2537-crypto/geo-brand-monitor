from urllib.parse import urlparse
import re

# See docs/contracts/url-and-outbound-fetch-security.md for the shared syntax
# contract. Syntax validation is not outbound-fetch authorization; server-side
# callers still need the network-address controls specified there.
# ASCII LDH host with at least one dot; each label starts/ends with alnum,
# may contain hyphens internally; no non-ASCII (IDN not supported yet).
_HOST_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)'
    r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)+$'
)
_ASCII_ONLY = re.compile(r'^[\x00-\x7F]+$')


def validate_url(url: str) -> bool:
    """Validate URL format — scheme must be http/https, host must be ASCII LDH
    with at least one dot. Rejects IDN / non-ASCII input instead of silently
    mangling it downstream.
    """
    if not url or not _ASCII_ONLY.match(url):
        return False
    try:
        result = urlparse(url)
    except ValueError:
        return False
    if result.scheme not in ('http', 'https'):
        return False
    hostname = result.hostname
    if not hostname:
        return False
    return bool(_HOST_RE.match(hostname))


def sanitize_url(url: str) -> str:
    """Ensure URL has a scheme. Assumes `validate_url(url)` already passed, so
    no regex stripping — callers that skip validation are on their own.
    """
    if not url.startswith(('http://', 'https://')):
        return 'https://' + url
    return url


def validate_email(email: str) -> bool:
    """Validate email format"""
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_regex, email) is not None

def sanitize_string(input_str: str) -> str:
    """Sanitize string to prevent XSS attacks"""
    # Remove HTML tags
    sanitized = re.sub(r'<[^>]+>', '', input_str)
    # Escape special characters
    sanitized = sanitized.replace('&', '&amp;')
    sanitized = sanitized.replace('<', '&lt;')
    sanitized = sanitized.replace('>', '&gt;')
    sanitized = sanitized.replace('"', '&quot;')
    sanitized = sanitized.replace("'", '&#39;')
    return sanitized
