from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.models import (  # noqa: E402
    AccountUsage,
    AppServerSnapshot,
    ContextUsage,
    RateLimitSet,
    RateLimitWindow,
    SystemResourceSnapshot,
    SessionSnapshot,
    TokenBreakdown,
    merge_snapshots,
)


class TokenBreakdownTests(unittest.TestCase):
    def test_from_mapping_accepts_snake_case(self) -> None:
        usage = TokenBreakdown.from_mapping(
            {
                "input_tokens": 100,
                "cached_input_tokens": 30,
                "cache_write_input_tokens": 7,
                "output_tokens": 20,
                "reasoning_output_tokens": 5,
                "total_tokens": 120,
            }
        )
        self.assertEqual(usage.input_tokens, 100)
        self.assertEqual(usage.cached_input_tokens, 30)
        self.assertEqual(usage.cache_write_input_tokens, 7)
        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.reasoning_output_tokens, 5)
        self.assertEqual(usage.total_tokens, 120)

    def test_from_mapping_accepts_camel_case_and_derives_total(self) -> None:
        usage = TokenBreakdown.from_mapping(
            {
                "inputTokens": "90",
                "cachedInputTokens": 20,
                "outputTokens": 10,
                "reasoningOutputTokens": 3,
            }
        )
        self.assertEqual(usage.input_tokens, 90)
        self.assertEqual(usage.output_tokens, 10)
        self.assertEqual(usage.total_tokens, 100)


class ContextUsageTests(unittest.TestCase):
    def test_raw_and_codex_style_context_percentages(self) -> None:
        context = ContextUsage(
            last=TokenBreakdown(total_tokens=56_000),
            context_window=100_000,
        )
        self.assertAlmostEqual(context.raw_used_percent, 56.0)
        self.assertAlmostEqual(context.codex_used_percent, 50.0)
        self.assertAlmostEqual(context.codex_remaining_percent, 50.0)

    def test_context_below_baseline_is_zero_user_controllable_usage(self) -> None:
        context = ContextUsage(
            last=TokenBreakdown(total_tokens=8_000),
            context_window=100_000,
        )
        self.assertEqual(context.codex_used_percent, 0.0)
        self.assertEqual(context.codex_remaining_percent, 100.0)

    def test_missing_window_is_unavailable(self) -> None:
        context = ContextUsage(last=TokenBreakdown(total_tokens=20), context_window=None)
        self.assertIsNone(context.raw_used_percent)
        self.assertIsNone(context.codex_used_percent)


class RateLimitTests(unittest.TestCase):
    def test_window_parses_official_shape(self) -> None:
        window = RateLimitWindow.from_mapping(
            {"usedPercent": 27.5, "windowDurationMins": 300, "resetsAt": 1_800_000_000}
        )
        self.assertEqual(window.used_percent, 27.5)
        self.assertEqual(window.remaining_percent, 72.5)
        self.assertEqual(window.window_minutes, 300)
        self.assertEqual(window.resets_at, 1_800_000_000)

    def test_limit_set_parses_snake_case_rollout_shape(self) -> None:
        limit = RateLimitSet.from_mapping(
            {
                "limit_id": "codex",
                "limit_name": "Codex",
                "primary": {"used_percent": 25, "window_minutes": 300, "resets_at": 1000},
                "secondary": {"used_percent": 40, "window_minutes": 10080, "resets_at": 2000},
                "plan_type": "pro",
            }
        )
        self.assertEqual(limit.limit_id, "codex")
        self.assertEqual(limit.primary.used_percent, 25)
        self.assertEqual(limit.secondary.window_minutes, 10080)
        self.assertEqual(limit.plan_type, "pro")


class AccountUsageTests(unittest.TestCase):
    def test_today_tokens_does_not_relabel_an_old_bucket_as_today(self) -> None:
        usage = AccountUsage.from_mapping(
            {
                "dailyUsageBuckets": [
                    {"startDate": "1900-01-01", "tokens": 12_345}
                ]
            }
        )

        self.assertIsNone(usage.today_tokens)


class MergeTests(unittest.TestCase):
    def test_app_server_limits_take_precedence_over_rollout_limits(self) -> None:
        rollout_limit = RateLimitSet(
            limit_id="codex",
            primary=RateLimitWindow(used_percent=80, window_minutes=300, resets_at=1000),
        )
        app_limit = RateLimitSet(
            limit_id="codex",
            primary=RateLimitWindow(used_percent=20, window_minutes=300, resets_at=2000),
        )
        session = SessionSnapshot(
            model="gpt-test",
            total_usage=TokenBreakdown(total_tokens=1000),
            last_usage=TokenBreakdown(total_tokens=400),
            model_context_window=10_000,
            rate_limits=(rollout_limit,),
            status="ok",
        )
        resources = SystemResourceSnapshot(cpu_percent=23.0, memory_percent=61.0, status="ok")
        app = AppServerSnapshot(
            plan_type="pro",
            rate_limits=(app_limit,),
            usage=AccountUsage(lifetime_tokens=123_456),
            status="ok",
        )

        merged = merge_snapshots(session, app, resources)

        self.assertEqual(merged.model, "gpt-test")
        self.assertEqual(merged.plan_type, "pro")
        self.assertEqual(merged.rate_limits[0].primary.used_percent, 20)
        self.assertEqual(merged.account_usage.lifetime_tokens, 123_456)
        self.assertEqual(merged.system_resources.cpu_percent, 23.0)

    def test_rollout_limits_remain_when_app_server_has_none(self) -> None:
        rollout_limit = RateLimitSet(
            limit_id="codex",
            primary=RateLimitWindow(used_percent=80, window_minutes=300, resets_at=1000),
        )
        session = SessionSnapshot(rate_limits=(rollout_limit,), status="ok")
        merged = merge_snapshots(session, AppServerSnapshot(status="error", error="offline"))
        self.assertEqual(merged.rate_limits, (rollout_limit,))
        self.assertIn("offline", merged.app_server_status)


if __name__ == "__main__":
    unittest.main()
