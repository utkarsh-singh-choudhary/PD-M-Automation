"""
Login-attempt rate limiting (High Priority: "No login rate limiting /
brute-force protection"). In-memory sliding window, keyed by (ip, email) so
one abusive client can't lock out someone else's account, and one
compromised/shared IP hitting many accounts is still slowed down per
account.

LIMITATION: this state lives in a single process's memory. It is correct
and effective for a single API replica (Render's free/starter tiers,
most small-plant deployments), but does NOT share state across multiple
replicas - a determined attacker distributing requests across replicas
behind a load balancer could exceed the intended limit. For a genuinely
multi-replica production deployment, replace this with a Redis-backed
limiter (e.g. via `slowapi` + Redis, or a small custom Redis INCR+EXPIRE
counter) using the exact same key scheme below.
"""
import time
from collections import defaultdict
from threading import Lock

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60  # 15 minutes

_attempts: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def _key(ip: str, email: str) -> str:
    return f"{ip}:{(email or '').strip().lower()}"


def is_rate_limited(ip: str, email: str) -> tuple[bool, int]:
    """Returns (limited, seconds_until_retry)."""
    now = time.time()
    k = _key(ip, email)
    with _lock:
        recent = [t for t in _attempts[k] if now - t < WINDOW_SECONDS]
        _attempts[k] = recent
        if len(recent) >= MAX_ATTEMPTS:
            retry_after = int(WINDOW_SECONDS - (now - recent[0]))
            return True, max(retry_after, 1)
    return False, 0


def record_failed_attempt(ip: str, email: str) -> None:
    with _lock:
        _attempts[_key(ip, email)].append(time.time())


def clear_attempts(ip: str, email: str) -> None:
    """Called on successful login so a legitimate user isn't penalized by
    earlier typos once they get the password right."""
    with _lock:
        _attempts.pop(_key(ip, email), None)
