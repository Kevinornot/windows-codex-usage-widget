from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherScriptTests(unittest.TestCase):
    def test_batch_scripts_do_not_expand_stale_errorlevel_inside_blocks(self) -> None:
        for name in ("run_widget.bat", "build_exe.bat"):
            content = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("%errorlevel%", content, name)

    def test_build_exe_bundles_the_tray_icon(self) -> None:
        content = (PROJECT_ROOT / "build_exe.bat").read_text(encoding="utf-8")
        self.assertIn('--add-data "assets\\codex_usage_widget.ico;assets"', content)

    def test_hidden_vbs_launcher_reports_startup_failures(self) -> None:
        content = (PROJECT_ROOT / "run_widget.vbs").read_text(encoding="utf-8")
        self.assertIn("shell.Run(command, 0, True)", content)
        self.assertIn("MsgBox", content)



if __name__ == "__main__":
    unittest.main()
