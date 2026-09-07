"""Windows toast notifications (best effort, never blocking)."""
from __future__ import annotations

import threading

from . import APP_NAME


def notify(title: str, message: str) -> None:
    """Fire a Windows toast on a background thread (never blocks the UI)."""
    threading.Thread(target=_notify, args=(title, message), daemon=True).start()


def _notify(title: str, message: str) -> None:
    try:
        from winotify import Notification
        Notification(app_id=APP_NAME, title=title[:64], msg=message[:250]).show()
    except Exception:
        pass  # a missing notification backend must never break anything
