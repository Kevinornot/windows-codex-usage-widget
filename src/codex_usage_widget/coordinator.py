"""Background polling and merge orchestration."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Callable

from .models import (
    AppServerSnapshot,
    SessionSnapshot,
    SystemResourceSnapshot,
    WidgetSnapshot,
    merge_snapshots,
)

SessionReader = Callable[[int], SessionSnapshot]
AppReader = Callable[[], AppServerSnapshot]
SnapshotListener = Callable[[WidgetSnapshot], None]
ResourceReader = Callable[[], SystemResourceSnapshot]


class SnapshotCoordinator:
    """Coordinate fast local polling with slower account reads.

    The class is intentionally UI-agnostic. Listeners are invoked on the coordinator's
    worker thread; GUI clients should marshal updates onto their own event loop.
    """

    def __init__(
        self,
        *,
        session_reader: SessionReader,
        app_reader: AppReader | None,
        resource_reader: ResourceReader | None = None,
        session_poll_seconds: float = 5.0,
        account_poll_seconds: float = 30.0,
    ) -> None:
        self.session_reader = session_reader
        self.app_reader = app_reader
        self.resource_reader = resource_reader
        self.session_poll_seconds = max(1.0, float(session_poll_seconds))
        self.account_poll_seconds = max(10.0, float(account_poll_seconds))
        self._session_index = 0
        self._last_session = SessionSnapshot()
        self._last_app = AppServerSnapshot()
        self._last_resources = SystemResourceSnapshot()
        self._snapshot = merge_snapshots(
            self._last_session,
            self._last_app,
            self._last_resources,
        )
        self._last_account_monotonic = float("-inf")
        self._lock = threading.RLock()
        self._listeners: list[SnapshotListener] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._force_account = threading.Event()
        self._thread: threading.Thread | None = None
        self._auto_refresh = True

    @property
    def session_index(self) -> int:
        with self._lock:
            return self._session_index

    @property
    def snapshot(self) -> WidgetSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def auto_refresh(self) -> bool:
        with self._lock:
            return self._auto_refresh

    def set_auto_refresh(self, enabled: bool) -> None:
        with self._lock:
            self._auto_refresh = bool(enabled)
        if enabled:
            self._wake.set()

    def set_session_index(self, index: int) -> None:
        with self._lock:
            self._session_index = max(0, int(index))
        self._wake.set()

    def cycle_session(self, delta: int) -> int:
        current = self.snapshot
        count = max(1, current.session_count)
        with self._lock:
            self._session_index = (self._session_index + int(delta)) % count
            result = self._session_index
        self._wake.set()
        return result

    def add_listener(self, listener: SnapshotListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: SnapshotListener) -> None:
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

    def _notify(self, snapshot: WidgetSnapshot) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                # A presentation callback must not stop monitoring.
                continue

    def poll_once(self, *, force_account: bool = False) -> WidgetSnapshot:
        with self._lock:
            session_index = self._session_index
        try:
            session = self.session_reader(session_index)
        except Exception as exc:
            with self._lock:
                previous_session = self._last_session
            session = replace(previous_session, status="error", error=str(exc))

        now = time.monotonic()
        with self._lock:
            previous_app = self._last_app
            due = (now - self._last_account_monotonic) >= self.account_poll_seconds

        app = previous_app
        if self.app_reader is not None and (force_account or due):
            try:
                app = self.app_reader()
            except Exception as exc:
                app = replace(
                    previous_app,
                    status="error",
                    error=str(exc),
                    updated_at=time.time(),
                )
            with self._lock:
                self._last_account_monotonic = now
        elif self.app_reader is None and previous_app.status == "unavailable":
            app = replace(previous_app, error="Codex App Server reader is disabled")

        with self._lock:
            previous_resources = self._last_resources
        resources = previous_resources
        if self.resource_reader is not None:
            try:
                resources = self.resource_reader()
            except Exception as exc:
                resources = replace(
                    previous_resources,
                    status="error",
                    error=str(exc),
                    updated_at=time.time(),
                )
        elif previous_resources.status == "unavailable":
            resources = replace(previous_resources, error="System resource reader is disabled")

        snapshot = merge_snapshots(session, app, resources)
        with self._lock:
            # Clamp a selection that became invalid after sessions were removed.
            if session.session_count > 0 and self._session_index >= session.session_count:
                self._session_index = session.session_count - 1
            self._last_session = session
            self._last_app = app
            self._last_resources = resources
            self._snapshot = snapshot
        self._notify(snapshot)
        return snapshot

    def request_refresh(self, *, include_account: bool = True) -> None:
        if include_account:
            self._force_account.set()
        self._wake.set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="codex-usage-widget-poller",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        first = True
        while not self._stop.is_set():
            with self._lock:
                enabled = self._auto_refresh
            if first or enabled or self._wake.is_set():
                include_account = first or self._force_account.is_set()
                self._force_account.clear()
                self._wake.clear()
                self.poll_once(force_account=include_account)
                first = False
            self._wake.wait(self.session_poll_seconds)
            self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
