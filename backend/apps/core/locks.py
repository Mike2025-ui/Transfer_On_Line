import contextlib
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def redis_lock(key, timeout=10, wait_timeout=5):
    """Best-effort distributed lock (Redis SET NX PX under the hood, via
    redis-py's own Lock class). This exists because select_for_update() is a
    documented no-op on SQLite (has_select_for_update=False - Django runs the
    query and silently drops the FOR UPDATE clause), which is what this
    project runs on by default. On PostgreSQL in production, select_for_update
    already provides a real row lock and this is pure defense-in-depth; in any
    SQLite deployment (dev only - see the production audit), it is the ONLY
    thing standing between two concurrent webhook deliveries actually
    serializing.

    Degrades gracefully to a no-op if Redis is unreachable - a missing/down
    Redis must never turn into a hard failure for payment processing, since
    this is a defense layer, not the primary correctness mechanism."""
    try:
        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry
    except ImportError:  # pragma: no cover - redis client always ships with this project
        yield
        return

    lock = None
    try:
        client = redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3, retry=Retry(NoBackoff(), 0),
        )
        lock = client.lock(f'tol-lock:{key}', timeout=timeout, blocking_timeout=wait_timeout, thread_local=True)
        if not lock.acquire():
            logger.warning('Could not acquire redis lock for %s within %ss - proceeding without it', key, wait_timeout)
            lock = None
        yield
    except Exception as exc:  # Redis down/unreachable/misconfigured
        logger.warning('Redis lock unavailable for %s (%s) - proceeding without distributed lock', key, exc)
        yield
    finally:
        if lock is not None:
            try:
                lock.release()
            except Exception:  # already expired or connection dropped - not fatal
                pass
