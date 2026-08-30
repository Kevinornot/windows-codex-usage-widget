from __future__ import annotations

import os
import contextlib
import io
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.tray import (  # noqa: E402
    WindowsTrayIcon,
    _wndproc_parameter_types,
    tray_toggle_label,
)


class TrayTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires Windows notification area")
    def test_real_windows_tray_starts_without_native_handle_overflow(self) -> None:
        tray = WindowsTrayIcon(
            title="Codex 监控器测试",
            icon_path=None,
            on_show=lambda: None,
            on_toggle_details=lambda: None,
            on_exit=lambda: None,
            is_compact=lambda: True,
        )
        native_errors = io.StringIO()
        try:
            with contextlib.redirect_stderr(native_errors):
                tray.start()
                self.assertIsNone(tray.error)
                self.assertIsNotNone(tray._hwnd)
        finally:
            with contextlib.redirect_stderr(native_errors):
                tray.stop()
        self.assertEqual(native_errors.getvalue(), "")

    def test_toggle_label_matches_compact_state(self) -> None:
        self.assertEqual(tray_toggle_label(True), "展开详情")
        self.assertEqual(tray_toggle_label(False), "收起详情")

    def test_win32_window_procedure_uses_four_parameters(self) -> None:
        class FakeWinTypes:
            HWND = object()
            UINT = object()
            WPARAM = object()
            LPARAM = object()

        self.assertEqual(
            _wndproc_parameter_types(FakeWinTypes),
            (FakeWinTypes.HWND, FakeWinTypes.UINT, FakeWinTypes.WPARAM, FakeWinTypes.LPARAM),
        )

    def test_non_windows_tray_is_a_safe_noop(self) -> None:
        tray = WindowsTrayIcon(
            title="Codex 监控器",
            icon_path=None,
            on_show=lambda: None,
            on_toggle_details=lambda: None,
            on_exit=lambda: None,
            is_compact=lambda: True,
        )
        with mock.patch("threading.excepthook") as thread_error:
            tray.start()
            tray.stop()
            thread_error.assert_not_called()
        self.assertIsInstance(tray.supported, bool)

    def test_start_reports_missing_native_window_as_unavailable(self) -> None:
        class NoWindowTray(WindowsTrayIcon):
            @property
            def supported(self) -> bool:
                return True

            def _run(self) -> None:
                self._ready.set()

        tray = NoWindowTray(
            title="Codex 监控器",
            icon_path=None,
            on_show=lambda: None,
            on_toggle_details=lambda: None,
            on_exit=lambda: None,
            is_compact=lambda: True,
        )
        tray.start()
        self.assertIsNotNone(tray.error)
        tray.stop()


if __name__ == "__main__":
    unittest.main()
