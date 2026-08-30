from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.models import RateLimitSet, RateLimitWindow  # noqa: E402
from codex_usage_widget import ui  # noqa: E402
from codex_usage_widget.ui import (  # noqa: E402
    bundled_asset_path,
    format_bytes_pair,
    format_duration,
    format_duration_cn,
    format_session_choice_label,
    format_limit_heading,
    format_model_display,
    format_window_label_cn,
    geometry_with_size,
    geometry_with_size_on_screen,
    session_selector_labels,
    format_reset_countdown,
    format_tokens,
    rate_limit_rows,
)


class UiHelperTests(unittest.TestCase):
    def test_model_display_uses_only_the_live_model_name(self) -> None:
        self.assertEqual(format_model_display("gpt-example"), "GPT-example")
        self.assertEqual(format_model_display("GPT-Example-Spark"), "GPT-Example-Spark")
        self.assertEqual(format_model_display(None), "GPT-—")

    def test_bundled_asset_path_uses_pyinstaller_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sys, "_MEIPASS", tmp, create=True):
                self.assertEqual(
                    bundled_asset_path("codex_usage_widget.ico"),
                    Path(tmp) / "assets" / "codex_usage_widget.ico",
                )

    def test_formats_token_counts_compactly(self) -> None:
        self.assertEqual(format_tokens(999), "999")
        self.assertEqual(format_tokens(12_345), "12.3K")
        self.assertEqual(format_tokens(1_234_567), "1.23M")
        self.assertEqual(format_tokens(None), "—")

    def test_formats_duration(self) -> None:
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(65), "1m 5s")
        self.assertEqual(format_duration(3660), "1h 1m")

    def test_formats_chinese_duration_and_window_labels(self) -> None:
        self.assertEqual(format_duration_cn(65), "1分5秒")
        self.assertEqual(format_duration_cn(3660), "1小时1分")
        self.assertEqual(format_window_label_cn(300), "5 小时")
        self.assertEqual(format_window_label_cn(10_080), "7 天")

    def test_formats_session_choice_label(self) -> None:
        path = Path("rollout-2026-08-30T23-00-00-12345678-1234-1234-1234-abcdef987654.jsonl")
        label = format_session_choice_label(path, index=0, modified_at=1_788_131_200)
        self.assertIn("最新", label)
        self.assertIn("abcdef98", label)


    def test_session_selector_labels_include_current_and_recent_marker(self) -> None:
        labels = session_selector_labels(3)
        self.assertEqual(labels[0], "会话 1（最新）")
        self.assertEqual(labels[2], "会话 3")

    def test_formats_resource_memory_and_preserves_saved_window_position(self) -> None:
        self.assertEqual(format_bytes_pair(int(3.8 * 1024**3), 8 * 1024**3), "3.8 / 8.0 GB")
        self.assertEqual(format_bytes_pair(None, None), "—")
        self.assertEqual(
            geometry_with_size("372x690+24+80", width=430, height=360),
            "430x360+24+80",
        )
        self.assertEqual(
            geometry_with_size("372x690-24+80", width=430, height=760),
            "430x760-24+80",
        )

    def test_resized_window_is_kept_fully_inside_the_screen(self) -> None:
        self.assertEqual(
            geometry_with_size_on_screen(
                "308x167+2094+120",
                width=462,
                height=743,
                screen_width=2405,
                screen_height=1353,
            ),
            "462x743+1943+120",
        )

    def test_reset_countdown_uses_absolute_reset_timestamp(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(format_reset_countdown(int(now + 3660), now=now), "1h 1m")
        self.assertEqual(format_reset_countdown(int(now - 1), now=now), "now")

    def test_rate_limit_rows_selects_the_weekly_general_window(self) -> None:
        limit = RateLimitSet(
            limit_id="codex",
            limit_name="Codex",
            primary=RateLimitWindow(used_percent=20, window_minutes=300, resets_at=20),
            secondary=RateLimitWindow(used_percent=40, window_minutes=10080, resets_at=30),
        )
        rows = rate_limit_rows((limit,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].window_label, "7d")
        self.assertEqual(rows[0].remaining_percent, 60)

    def test_quota_rows_show_only_codex_weekly_and_spark_five_hour_limits(self) -> None:
        codex = RateLimitSet(
            limit_id="codex",
            limit_name="Codex",
            primary=RateLimitWindow(used_percent=20, window_minutes=300, resets_at=20),
            secondary=RateLimitWindow(used_percent=40, window_minutes=10_080, resets_at=30),
        )
        spark = RateLimitSet(
            limit_id="spark",
            limit_name="GPT-5.3-Codex-Spark",
            primary=RateLimitWindow(used_percent=30, window_minutes=300, resets_at=40),
            secondary=RateLimitWindow(used_percent=50, window_minutes=10_080, resets_at=50),
        )
        rows = rate_limit_rows((codex, spark))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            tuple(format_limit_heading(row) for row in rows),
            ("Codex · 7 天 · 通用", "GPT-5.3-Codex-Spark · 5 小时"),
        )
        self.assertEqual(tuple(row.used_percent for row in rows), (40, 30))


if __name__ == "__main__":
    unittest.main()
