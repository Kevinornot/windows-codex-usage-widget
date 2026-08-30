from __future__ import annotations

import sys
import tkinter as tk
import unittest
import ctypes
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget import windows_effects  # noqa: E402
from codex_usage_widget.windows_effects import pack_abgr  # noqa: E402


class WindowsEffectsTests(unittest.TestCase):
    def test_enables_per_monitor_high_dpi_awareness(self) -> None:
        enable = getattr(windows_effects, "enable_high_dpi_awareness", None)
        self.assertIsNotNone(enable)
        self.assertTrue(enable())

    def test_applies_a_rounded_region_to_a_real_window(self) -> None:
        apply_region = getattr(windows_effects, "apply_rounded_window_region", None)
        self.assertIsNotNone(apply_region)
        root = tk.Tk()
        try:
            root.geometry("320x220")
            root.update_idletasks()
            self.assertTrue(
                apply_region(root.winfo_id(), width=320, height=220, radius=24)
            )
            outer = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
            bounds = wintypes.RECT()
            self.assertIn(
                ctypes.windll.user32.GetWindowRgnBox(outer, ctypes.byref(bounds)),
                (2, 3),
            )
        finally:
            root.destroy()

    def test_reads_the_native_monitor_scale_for_a_real_window(self) -> None:
        get_scale = getattr(windows_effects, "get_window_scale", None)
        self.assertIsNotNone(get_scale)
        windows_effects.enable_high_dpi_awareness()
        root = tk.Tk()
        try:
            root.update_idletasks()
            outer = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
            native_dpi = ctypes.windll.user32.GetDpiForWindow(outer)
            self.assertAlmostEqual(get_scale(root.winfo_id()), native_dpi / 96.0, places=2)
        finally:
            root.destroy()

    def test_uses_the_high_resolution_desktop_scale_for_the_widget(self) -> None:
        get_scale = getattr(windows_effects, "get_desktop_scale", None)
        self.assertIsNotNone(get_scale)
        root = tk.Tk()
        try:
            root.update_idletasks()
            self.assertGreaterEqual(
                get_scale(root.winfo_id()),
                windows_effects.get_window_scale(root.winfo_id()),
            )
            self.assertLessEqual(get_scale(root.winfo_id()), 4.0)
        finally:
            root.destroy()

    def test_packs_rgb_and_alpha_for_windows_acrylic(self) -> None:
        self.assertEqual(pack_abgr("#F4F8FB", alpha=210), 0xD2FBF8F4)

    def test_rejects_invalid_hex_color(self) -> None:
        with self.assertRaises(ValueError):
            pack_abgr("white", alpha=200)


if __name__ == "__main__":
    unittest.main()
