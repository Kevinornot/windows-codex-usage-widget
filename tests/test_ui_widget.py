from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.config import AppSettings, SettingsStore  # noqa: E402
from codex_usage_widget.coordinator import SnapshotCoordinator  # noqa: E402
from codex_usage_widget.models import (  # noqa: E402
    AppServerSnapshot,
    RateLimitSet,
    RateLimitWindow,
    SessionOption,
    SessionSnapshot,
    SystemResourceSnapshot,
    TokenBreakdown,
)
from codex_usage_widget.ui import COMPACT_HEIGHT, CodexUsageWidget, RoundedCard  # noqa: E402


def display_is_available() -> bool:
    try:
        probe = tk.Tk()
        probe.withdraw()
        probe.update_idletasks()
        probe.destroy()
        return True
    except tk.TclError:
        return False


class FakeAutostart:
    supported = False

    def is_enabled(self) -> bool:
        return False

    def toggle(self) -> bool:
        return False


class FakeTray:
    supported = True

    def __init__(self, **callbacks: object) -> None:
        self.callbacks = callbacks
        self.started = False
        self.stopped = False
        self.error: str | None = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


@unittest.skipUnless(display_is_available(), "requires a working Tk display")
class WidgetInteractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        option_paths = tuple(Path(f"rollout-session-{index + 1}.jsonl") for index in range(3))
        options = tuple(
            SessionOption(
                index=index,
                path=path,
                session_id=f"session-{index + 1}",
                model=f"gpt-{index + 1}",
                cwd=f"C:/project/{index + 1}",
                updated_at=1_788_131_200 - index * 60,
                active=index == 0,
            )
            for index, path in enumerate(option_paths)
        )

        def read_session(index: int) -> SessionSnapshot:
            return SessionSnapshot(
                session_id=f"session-{index + 1}",
                path=option_paths[index],
                model=f"gpt-{index + 1}",
                model_provider="openai",
                cwd=f"C:/project/{index + 1}",
                source="codex-app",
                total_usage=TokenBreakdown(total_tokens=500_000 + index),
                last_usage=TokenBreakdown(
                    input_tokens=80_000 + index,
                    cached_input_tokens=40_000,
                    output_tokens=9_000,
                    reasoning_output_tokens=4_000,
                    total_tokens=90_000 + index,
                ),
                model_context_window=200_000,
                status="ok",
                active=index == 0,
                session_count=3,
                session_index=index,
                session_options=options,
            )

        self.coordinator = SnapshotCoordinator(
            session_reader=read_session,
            app_reader=lambda: AppServerSnapshot(
                rate_limits=(
                    RateLimitSet(
                        limit_id="codex",
                        primary=RateLimitWindow(used_percent=25, window_minutes=300),
                        secondary=RateLimitWindow(used_percent=45, window_minutes=10_080),
                    ),
                    RateLimitSet(
                        limit_id="spark",
                        limit_name="GPT-5.3-Codex-Spark",
                        primary=RateLimitWindow(used_percent=12, window_minutes=300),
                    ),
                ),
                status="ok",
            ),
            resource_reader=lambda: SystemResourceSnapshot(
                cpu_percent=23,
                memory_percent=61,
                gpu_percent=17,
                gpu_name="Example GPU",
                vram_used_bytes=int(3.8 * 1024**3),
                vram_total_bytes=8 * 1024**3,
                status="ok",
            ),
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(Path(self.tmp.name) / "settings.json")
        self.tray: FakeTray | None = None

        def build_tray(**callbacks: object) -> FakeTray:
            self.tray = FakeTray(**callbacks)
            return self.tray

        self.widget = CodexUsageWidget(
            self.root,
            coordinator=self.coordinator,
            settings_store=self.store,
            settings=AppSettings(compact_mode=False, geometry="462x900+20+20"),
            autostart=FakeAutostart(),
            codex_home=Path(self.tmp.name),
            tray_factory=build_tray,
        )
        self.root.update()
        self.widget._render(self.coordinator.poll_once(force_account=True))
        self.root.update()

    def tearDown(self) -> None:
        widget = getattr(self, "widget", None)
        if widget is not None:
            try:
                widget.exit_app()
            except tk.TclError:
                pass
        self.tmp.cleanup()

    def test_full_dashboard_uses_requested_section_order(self) -> None:
        self.assertFalse(self.widget.compact_mode)
        self.assertEqual(
            self.widget.section_order,
            ("model", "limits", "resources", "tokens", "context", "activity"),
        )
        self.assertEqual(self.widget.window_title_text, "Codex monitor")
        self.assertEqual(float(self.root.attributes("-alpha")), 1.0)

    def test_context_session_selector_changes_coordinator_session(self) -> None:
        self.widget.select_session(2)
        self.assertEqual(self.coordinator.session_index, 2)


    def test_compact_mode_shows_quota_without_full_dashboard(self) -> None:
        self.widget.show_widget()
        self.root.update()
        self.widget.toggle_details()
        self.root.update()
        self.assertTrue(self.widget.compact_mode)
        self.assertFalse(self.widget.model_card.winfo_ismapped())
        self.assertTrue(self.widget.limit_card.winfo_ismapped())
        self.assertFalse(self.widget.details_frame.winfo_ismapped())
        logical_width = self.root.winfo_width() / self.widget.display_scale
        logical_height = self.root.winfo_height() / self.widget.display_scale
        self.assertAlmostEqual(logical_width, 308, delta=1)
        self.assertAlmostEqual(logical_height, 167, delta=1)
        self.assertLess(float(self.root.attributes("-alpha")), 0.9)

    def test_live_ages_are_inside_quota_and_session_sections(self) -> None:
        self.assertEqual(self.widget.header_status.winfo_manager(), "")
        self.widget._update_status_text()
        self.assertIn("更新", str(self.widget.limit_summary.cget("text")))
        self.assertIn("更新", str(self.widget.session_button.cget("text")))

    def test_expand_control_is_below_the_quota_card(self) -> None:
        self.widget.show_widget()
        self.root.update()
        self.widget.toggle_details()
        self.root.update()
        self.assertGreater(
            self.widget.details_button.winfo_rooty(),
            self.widget.limit_card.winfo_rooty() + self.widget.limit_card.winfo_height() - 2,
        )

    def test_expanded_body_has_no_large_blank_footer(self) -> None:
        self.widget.show_widget()
        self.root.update()
        blank_pixels = self.widget.body.canvas.winfo_height() - self.widget.body.content.winfo_reqheight()
        self.assertLessEqual(blank_pixels, self.widget._px(18))

    def test_cards_use_restrained_corner_radius(self) -> None:
        self.assertLessEqual(self.widget.limit_card.radius, 10)

    def test_unchanged_quota_snapshot_does_not_rebuild_visible_rows(self) -> None:
        before = tuple(self.widget.limit_container.winfo_children())
        self.widget._render(self.coordinator.poll_once(force_account=False))
        self.root.update()
        after = tuple(self.widget.limit_container.winfo_children())
        self.assertEqual(after, before)

    def test_refresh_menu_distinguishes_live_session_from_three_minute_quota(self) -> None:
        labels: list[str] = []
        for index in range(self.widget.menu.index("end") + 1):
            try:
                labels.append(str(self.widget.menu.entrycget(index, "label")))
            except tk.TclError:
                continue
        self.assertTrue(any("限额 3 分钟" in label for label in labels))

    def test_widget_can_hide_to_tray_and_be_restored(self) -> None:
        self.widget.show_widget()
        self.root.update()
        self.assertTrue(self.root.winfo_viewable())
        self.widget.hide_widget()
        self.root.update()
        self.assertFalse(self.root.winfo_viewable())
        self.widget.show_widget()
        self.root.update()
        self.assertTrue(self.root.winfo_viewable())
        self.assertIsNotNone(self.tray)
        self.assertTrue(self.tray.started)

    def test_header_hide_control_sends_widget_to_system_tray(self) -> None:
        self.widget.show_widget()
        self.root.update()
        self.assertEqual(self.widget.hide_button.cget("text"), "—")

        self.widget.hide_button.event_generate("<Button-1>")
        self.root.update()

        self.assertFalse(self.root.winfo_viewable())
        self.assertIsNotNone(self.tray)
        self.assertTrue(self.tray.started)

    def test_failed_tray_uses_recoverable_taskbar_minimize(self) -> None:
        self.assertIsNotNone(self.tray)
        self.tray.error = "tray failed"
        self.widget.hide_widget()
        self.root.update()
        self.assertTrue(self.widget._fallback_minimized)

    def test_taskbar_restore_reapplies_borderless_window_style(self) -> None:
        self.assertIsNotNone(self.tray)
        self.widget.show_widget()
        self.root.update()
        self.tray.error = "tray failed"
        self.widget.hide_widget()
        self.root.update()
        self.assertFalse(bool(self.root.overrideredirect()))

        self.root.deiconify()
        self.root.update()

        self.assertTrue(bool(self.root.overrideredirect()))
        self.assertFalse(self.widget._fallback_minimized)

    def test_exit_app_cancels_scheduled_widget_jobs(self) -> None:
        self.assertTrue(self.widget._after_ids)
        widget = self.widget
        self.widget = None
        widget.exit_app()
        self.assertEqual(widget._after_ids, set())

    def test_rounded_card_redraw_accepts_canvas_outline_width(self) -> None:
        card = RoundedCard(self.root)
        card.pack(fill="x")
        self.root.update_idletasks()
        card._redraw()
        self.assertTrue(card.find_withtag("card-shape"))

    def test_system_resource_cards_render_live_values(self) -> None:
        self.assertEqual(self.widget.resource_values["cpu"].cget("text"), "23%")
        self.assertEqual(self.widget.resource_values["memory"].cget("text"), "61%")
        self.assertEqual(self.widget.resource_values["gpu"].cget("text"), "17%")
        self.assertEqual(self.widget.resource_values["vram"].cget("text"), "3.8 / 8.0 GB")
        self.assertEqual(
            self.widget.gpu_name_label.cget("text"),
            "Example GPU",
        )

    def test_system_resource_cards_use_vector_icons_and_usage_labels(self) -> None:
        icons = getattr(self.widget, "resource_icons", {})
        self.assertEqual(set(icons), {"cpu", "memory", "gpu", "vram"})
        self.assertTrue(all(not isinstance(icon, tk.Canvas) for icon in icons.values()))
        self.assertTrue(
            all(
                "Segoe Fluent Icons" in str(tkfont.Font(font=icon.cget("font")).actual("family"))
                for icon in icons.values()
            )
        )

        def label_texts(widget: tk.Misc) -> list[str]:
            texts: list[str] = []
            for child in widget.winfo_children():
                try:
                    text = child.cget("text")
                except tk.TclError:
                    text = ""
                if text:
                    texts.append(str(text))
                texts.extend(label_texts(child))
            return texts

        captions = label_texts(self.widget.details_frame)
        for caption in ("CPU占用", "内存占用", "GPU占用", "显存占用"):
            self.assertIn(caption, captions)

        resource_sizes = {
            int(tkfont.Font(font=value.cget("font")).actual("size"))
            for value in self.widget.resource_values.values()
        }
        token_sizes = {
            int(tkfont.Font(font=value.cget("font")).actual("size"))
            for value in self.widget.token_values.values()
        }
        self.assertEqual(len(resource_sizes), 1)
        self.assertGreater(min(resource_sizes), max(token_sizes))

    def test_model_card_uses_crisp_vector_avatar_and_live_model_name(self) -> None:
        self.assertEqual(self.widget.model_avatar.cget("text"), "C")
        self.assertIsInstance(self.widget.model_avatar, tk.Label)
        self.assertEqual(
            self.widget.model_label.cget("text"),
            "GPT-1",
        )


if __name__ == "__main__":
    unittest.main()
