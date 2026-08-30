from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.coordinator import SnapshotCoordinator  # noqa: E402
from codex_usage_widget.models import (  # noqa: E402
    AccountUsage,
    AppServerSnapshot,
    RateLimitSet,
    RateLimitWindow,
    SessionSnapshot,
    SystemResourceSnapshot,
)


class FakeSessionSource:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, session_index: int = 0) -> SessionSnapshot:
        self.calls += 1
        return SessionSnapshot(model=f"model-{session_index}", status="ok")



class SequenceAppSource:
    def __init__(self, values: list[AppServerSnapshot | Exception]) -> None:
        self.values = values
        self.calls = 0

    def __call__(self) -> AppServerSnapshot:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


class CoordinatorTests(unittest.TestCase):
    def test_poll_merges_session_and_account_data(self) -> None:
        session_source = FakeSessionSource()
        app_source = SequenceAppSource(
            [
                AppServerSnapshot(
                    plan_type="pro",
                    usage=AccountUsage(lifetime_tokens=100),
                    status="ok",
                )
            ]
        )
        coordinator = SnapshotCoordinator(
            session_reader=session_source,
            app_reader=app_source,
            session_poll_seconds=5,
            account_poll_seconds=30,
        )
        snapshot = coordinator.poll_once(force_account=True)
        self.assertEqual(snapshot.model, "model-0")
        self.assertEqual(snapshot.plan_type, "pro")
        self.assertEqual(snapshot.account_usage.lifetime_tokens, 100)

    def test_failed_account_refresh_preserves_last_good_limits(self) -> None:
        limit = RateLimitSet(
            limit_id="codex",
            primary=RateLimitWindow(used_percent=10, window_minutes=300, resets_at=100),
        )
        app_source = SequenceAppSource(
            [AppServerSnapshot(rate_limits=(limit,), status="ok"), RuntimeError("offline")]
        )
        coordinator = SnapshotCoordinator(
            session_reader=FakeSessionSource(),
            app_reader=app_source,
            session_poll_seconds=5,
            account_poll_seconds=30,
        )
        first = coordinator.poll_once(force_account=True)
        second = coordinator.poll_once(force_account=True)
        self.assertEqual(first.rate_limits, (limit,))
        self.assertEqual(second.rate_limits, (limit,))
        self.assertIn("offline", second.app_server_status)

    def test_session_index_is_forwarded(self) -> None:
        source = FakeSessionSource()
        coordinator = SnapshotCoordinator(session_reader=source, app_reader=None)
        coordinator.set_session_index(2)
        snapshot = coordinator.poll_once(force_account=False)
        self.assertEqual(snapshot.model, "model-2")

    def test_poll_includes_local_system_resources(self) -> None:
        resources = SystemResourceSnapshot(
            cpu_percent=23.0,
            memory_percent=61.0,
            gpu_percent=17.0,
            vram_used_bytes=3_800_000_000,
            vram_total_bytes=8_000_000_000,
            status="ok",
        )
        coordinator = SnapshotCoordinator(
            session_reader=FakeSessionSource(),
            app_reader=None,
            resource_reader=lambda: resources,
        )

        snapshot = coordinator.poll_once(force_account=False)

        self.assertEqual(snapshot.system_resources, resources)

    def test_failed_resource_refresh_preserves_last_good_values(self) -> None:
        resources = SystemResourceSnapshot(cpu_percent=35.0, status="ok")
        values: list[SystemResourceSnapshot | Exception] = [resources, RuntimeError("gpu offline")]

        def read_resources() -> SystemResourceSnapshot:
            value = values.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        coordinator = SnapshotCoordinator(
            session_reader=FakeSessionSource(),
            app_reader=None,
            resource_reader=read_resources,
        )

        first = coordinator.poll_once(force_account=False)
        second = coordinator.poll_once(force_account=False)

        self.assertEqual(first.system_resources.cpu_percent, 35.0)
        self.assertEqual(second.system_resources.cpu_percent, 35.0)
        self.assertIn("gpu offline", second.system_resources.error or "")


if __name__ == "__main__":
    unittest.main()
