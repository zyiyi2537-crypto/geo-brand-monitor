"""Timing instrumentation for GEO check functions.

Used to measure where time actually goes during a check request — both at
endpoint level (HTTP middleware) and at individual function level (monkey-patch
every `check_*` in the core geo_checker modules so we can see that e.g.
`check_cross_platform` eats 80s while `check_https` finishes in 200ms).

All log lines go to the `geo.timing` logger, format:
  func=<name> elapsed_ms=<int>
  block=<label> elapsed_ms=<int>
  http method=<m> path=<p> status=<code> elapsed_ms=<int>
"""

import functools
import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("geo.timing")


@contextmanager
def time_block(label: str):
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(f"block={label} elapsed_ms={elapsed_ms}")


def _wrap(name, fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        t0 = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info(f"func={name} elapsed_ms={elapsed_ms}")
    wrapped._geo_timed = True
    return wrapped


def instrument_checks(module, prefix: str = "check_") -> int:
    """Wrap every `prefix`-named callable on `module` with timing logs.

    Idempotent — re-applying skips already-wrapped callables. Returns the
    number of functions wrapped for sanity-check at module load.
    """
    wrapped_count = 0
    for name in list(vars(module)):
        if not name.startswith(prefix):
            continue
        fn = getattr(module, name)
        if not callable(fn) or getattr(fn, "_geo_timed", False):
            continue
        setattr(module, name, _wrap(name, fn))
        wrapped_count += 1
    return wrapped_count


def instrument_funcs(module, names) -> int:
    """Same as instrument_checks but for an explicit name list (top-level runners)."""
    wrapped_count = 0
    for name in names:
        fn = getattr(module, name, None)
        if fn is None or not callable(fn) or getattr(fn, "_geo_timed", False):
            continue
        setattr(module, name, _wrap(name, fn))
        wrapped_count += 1
    return wrapped_count
