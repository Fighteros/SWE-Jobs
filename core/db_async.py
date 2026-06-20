"""
core/db_async.py — async facade over core.db.

Every function in core.db is synchronous psycopg2 I/O. Calling it directly from
the asyncio event loop (command handlers, callbacks, the scheduler) blocks the
loop: a single stalled query freezes the bot *and* the API until restart.

This facade exposes the same names as core.db, but each one runs the underlying
sync function in a worker thread via asyncio.to_thread, so DB I/O never blocks
the event loop. Usage:

    from core import db_async as adb
    user = await adb.get_or_create_user(telegram_id, username)

The sync core.db API is left untouched, so tests and any non-async callers keep
working. Because the wrapper resolves ``getattr(core.db, name)`` at call time,
tests that patch ``core.db.<fn>`` are still honored through the facade.

Thread-safety note: core.db uses a ThreadedConnectionPool, which is required now
that these calls run on multiple worker threads.
"""

import asyncio

from core import db as _db


def __getattr__(name: str):  # PEP 562 module-level __getattr__
    """Return an async wrapper that runs core.db.<name> in a worker thread."""
    fn = getattr(_db, name)
    if not callable(fn):
        raise AttributeError(f"core.db.{name} is not callable")

    async def _runner(*args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    _runner.__name__ = f"async_{name}"
    _runner.__qualname__ = _runner.__name__
    return _runner
