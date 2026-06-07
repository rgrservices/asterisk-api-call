from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_call_timestamps: dict[int, deque[float]] = defaultdict(deque)


def is_allowed(token_id: int, calls_per_minute: int) -> bool:
    """Retorna True se a requisição está dentro do limite; False se excedeu."""
    now = time.monotonic()
    cutoff = now - 60.0

    with _lock:
        q = _call_timestamps[token_id]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= calls_per_minute:
            return False
        q.append(now)
        return True
