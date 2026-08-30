from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.config import (  # noqa: E402
    AppSettings,
    SettingsStore,
    WindowsAutostart,
    build_startup_script,
    read_codex_config,
)


class CodexConfigTests(unittest.TestCase):
    def test_reads_model_and_context_window_from_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.toml").write_text(
                'model = "gpt-example"\nmodel_context_window = 400000\n',
                encoding="utf-8",
            )
            config = read_codex_config(home)
            self.assertEqual(config.model, "gpt-example")
            self.assertEqual(config.model_context_window, 400000)

    def test_malformed_toml_returns_diagnostic_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.toml").write_text("model = [", encoding="utf-8")
            config = read_codex_config(home)
            self.assertIsNone(config.model)
            self.assertIn("config", config.error.lower())


class SettingsTests(unittest.TestCase):
    def test_round_trip_preserves_supported_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp) / "settings.json")
            settings = AppSettings(
                geometry="360x520+10+20",
                opacity=0.82,
                auto_refresh=False,
                session_index=3,
                always_on_top=False,
                compact_mode=True,
            )
            store.save(settings)
            self.assertEqual(store.load(), settings)

    def test_quota_only_compact_view_is_the_default(self) -> None:
        defaults = AppSettings()
        self.assertTrue(defaults.compact_mode)
        self.assertTrue(AppSettings.from_mapping({}).compact_mode)
        self.assertEqual(defaults.geometry, "462x250+24+60")
        self.assertEqual(defaults.opacity, 1.0)
        self.assertEqual(defaults.session_poll_seconds, 2.0)
        self.assertEqual(defaults.account_poll_seconds, 180.0)

    def test_saved_fast_account_poll_is_migrated_to_three_minutes(self) -> None:
        settings = AppSettings.from_mapping({"account_poll_seconds": 30})
        self.assertEqual(settings.account_poll_seconds, 180.0)

    def test_invalid_settings_use_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(SettingsStore(path).load(), AppSettings())


class AutostartTests(unittest.TestCase):
    def test_startup_script_quotes_paths(self) -> None:
        script = build_startup_script(
            Path(r"C:\Program Files\Python\pythonw.exe"),
            Path(r"C:\Users\ExampleUser\Codex Widget\run_widget.pyw"),
        )
        self.assertIn('"C:\\Program Files\\Python\\pythonw.exe"', script)
        self.assertIn('"C:\\Users\\ExampleUser\\Codex Widget\\run_widget.pyw"', script)

    def test_startup_script_can_launch_a_frozen_executable_directly(self) -> None:
        script = build_startup_script(
            Path(r"C:\Program Files\Codex Widget\CodexUsageWidget.exe")
        )
        self.assertIn(
            'start "" "C:\\Program Files\\Codex Widget\\CodexUsageWidget.exe"',
            script,
        )
        self.assertNotIn("run_widget.pyw", script)

    def test_autostart_writes_and_removes_cmd_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            startup = WindowsAutostart(
                startup_dir=Path(tmp),
                python_executable=Path("pythonw.exe"),
                launcher=Path("C:/Widget/run_widget.pyw"),
            )
            startup.enable()
            self.assertTrue(startup.is_enabled())
            self.assertIn("pythonw.exe", startup.path.read_text(encoding="utf-8-sig"))
            startup.disable()
            self.assertFalse(startup.is_enabled())


if __name__ == "__main__":
    unittest.main()
