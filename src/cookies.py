"""
In-process cookie jar for reusing Cloudflare clearance across requests.

Each /v1 call gets a fresh browser context, so without this every request
re-solves the challenge from scratch. `cf_clearance` is bound to both the
egress IP and the user agent, so entries are keyed by the proxy a request
will go out through: a clearance minted via one proxy must never be handed
to a request leaving through another (or through none).

The jar lives in memory only - a restart drops it, which is the accepted
trade-off for having no filesystem side effects.
"""

import time

from playwright.async_api import BrowserContext, Cookie

from src.utils import logger

__all__ = ["load", "reset", "store"]

_jar: dict[str, dict[tuple[str, str, str], Cookie]] = {}


def reset() -> None:
    """Drop every stored cookie; exists so tests never poke at privates."""
    _jar.clear()


async def store(context: BrowserContext, proxy_key: str) -> None:
    """Merge the context's current cookies into the jar for this proxy."""
    entries = _jar.setdefault(proxy_key, {})
    for cookie in await context.cookies():
        entries[(cookie["name"], cookie["domain"], cookie["path"])] = cookie
    logger.debug(
        "Stored cookies for proxy %r: %d total", proxy_key or "<none>", len(entries)
    )


async def load(context: BrowserContext, proxy_key: str) -> None:
    """Inject this proxy's stored cookies into the context before navigation."""
    entries = _jar.get(proxy_key)
    if not entries:
        return

    now = time.time()
    fresh = [
        cookie
        for cookie in entries.values()
        # Playwright reports session cookies as expires=-1; anything else is
        # an absolute timestamp to compare against now.
        if cookie["expires"] < 0 or cookie["expires"] >= now
    ]
    if not fresh:
        return

    await context.add_cookies(fresh)
    logger.debug(
        "Reusing %d stored cookies for proxy %r", len(fresh), proxy_key or "<none>"
    )
