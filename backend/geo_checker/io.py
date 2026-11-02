"""Low-level HTTP + HTML utilities shared across all check_* functions.

Migrated from /geo_checker.py lines 201–225 (fetch / get_soup /
get_text_content) and line 1048 (flesch_kincaid_grade).

fetch() caches responses in state._page_cache so repeated calls for the
same URL within a single request return the stored response. Cache is per
process. Cross-worker sharing belongs in the backend cache service.
"""

import re

import requests
from bs4 import BeautifulSoup

from . import state as _state


def fetch(url, timeout=15, allow_redirects=True):
    """GET *url* and return the requests.Response, or None on failure.

    Thread-safe caching via state._page_cache_lock. Two-phase locking:
      1. Check cache under lock.
      2. Release lock before the HTTP call (avoid holding a lock during
         network I/O — other threads can proceed with different URLs).
      3. Write back under lock.

    Worst case: two threads miss the same URL simultaneously and both fetch —
    2x wasted HTTP, no correctness issue. Acceptable.

    The 15-second default is an upper bound; individual callers may pass
    smaller timeouts (e.g. 5-6s) for probes that shouldn't block the whole
    check on a single slow host.
    """
    with _state._page_cache_lock:
        if url in _state._page_cache:
            return _state._page_cache[url]
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=allow_redirects, headers={
            "User-Agent": "GEO-Readiness-Checker/1.0"
        })
        with _state._page_cache_lock:
            _state._page_cache[url] = resp
        return resp
    except requests.RequestException:
        return None


def get_soup(base_url):
    """Fetch *base_url* and return (response, BeautifulSoup). Returns
    (None, None) on failure so callers can short-circuit with a single
    falsy check.

    Uses ``resp.content`` (raw bytes) instead of ``resp.text``: when the
    HTTP Content-Type lacks a ``charset`` directive, ``requests`` defaults
    to ISO-8859-1 per RFC 2616, mangling UTF-8 Chinese pages (the meta
    description in `--citation-check` ended up as `æªåºæ¥å£`-style mojibake).
    BeautifulSoup's UnicodeDammit reads the HTML's own `<meta charset>`
    and decodes correctly.
    """
    resp = fetch(base_url)
    if not resp or resp.status_code != 200:
        return None, None
    return resp, BeautifulSoup(resp.content, "html.parser")


def get_text_content(soup):
    """Extract visible text from a BeautifulSoup tree, dropping scripts,
    styles, and noscript blocks. Works on a copy so the original soup is
    unmodified (several callers rely on that)."""
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript"]):
        tag.decompose()
    return clone.get_text(separator=" ", strip=True)


# ---------------------------------------------------------------------------
# Text-analysis helpers used by content-quality checks
# ---------------------------------------------------------------------------
def flesch_kincaid_grade(text):
    """Approximate Flesch-Kincaid grade level from a plain text string.
    Returns None when the text has no sentences or no words."""
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return None
    words = re.findall(r'\b[a-zA-Z]+\b', text)
    if not words:
        return None

    def count_syllables(word):
        word = word.lower()
        count = 0
        vowels = 'aeiouy'
        if word and word[0] in vowels:
            count += 1
        for i in range(1, len(word)):
            if word[i] in vowels and word[i - 1] not in vowels:
                count += 1
        if word.endswith('e'):
            count = max(count - 1, 0)
        return max(count, 1)

    num_syllables = sum(count_syllables(w) for w in words)
    return 0.39 * (len(words) / len(sentences)) + 11.8 * (num_syllables / len(words)) - 15.59
