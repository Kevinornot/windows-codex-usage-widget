from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.rollout import (  # noqa: E402
    discover_sessions,
    parse_rollout,
    read_bounded_lines,
    read_latest_session,
    resolve_codex_home,
)


def write_jsonl(path: Path, records: list[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record if isinstance(record, str) else json.dumps(record))
            handle.write("\n")


class RolloutParserTests(unittest.TestCase):
    def test_parses_canonical_rollout_token_count_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions/2026/08/29/rollout-a.jsonl"
            write_jsonl(
                path,
                [
                    {
                        "timestamp": "2026-08-29T12:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "cwd": "C:/work/project",
                            "model_provider": "openai",
                            "source": "cli",
                        },
                    },
                    {
                        "timestamp": "2026-08-29T12:00:01Z",
                        "type": "turn_context",
                        "payload": {"turn_id": "turn-1", "model": "gpt-example"},
                    },
                    "{not valid json",
                    {
                        "timestamp": "2026-08-29T12:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 1000,
                                    "cached_input_tokens": 200,
                                    "output_tokens": 100,
                                    "reasoning_output_tokens": 25,
                                    "total_tokens": 1100,
                                },
                                "last_token_usage": {
                                    "input_tokens": 400,
                                    "cached_input_tokens": 100,
                                    "output_tokens": 50,
                                    "reasoning_output_tokens": 10,
                                    "total_tokens": 450,
                                },
                                "model_context_window": 128000,
                            },
                            "rate_limits": {
                                "limit_id": "codex",
                                "primary": {
                                    "used_percent": 23,
                                    "window_minutes": 300,
                                    "resets_at": 1800000000,
                                },
                                "secondary": {
                                    "used_percent": 51,
                                    "window_minutes": 10080,
                                    "resets_at": 1800100000,
                                },
                                "plan_type": "pro",
                            },
                        },
                    },
                ],
            )

            snapshot = parse_rollout(path)

            self.assertEqual(snapshot.session_id, "thread-1")
            self.assertEqual(snapshot.model, "gpt-example")
            self.assertEqual(snapshot.model_provider, "openai")
            self.assertEqual(snapshot.cwd, "C:/work/project")
            self.assertEqual(snapshot.total_usage.total_tokens, 1100)
            self.assertEqual(snapshot.last_usage.cached_input_tokens, 100)
            self.assertEqual(snapshot.model_context_window, 128000)
            self.assertEqual(snapshot.rate_limits[0].primary.used_percent, 23)
            self.assertEqual(snapshot.plan_type_hint, "pro")
            self.assertEqual(snapshot.malformed_lines, 1)

    def test_parses_camel_case_token_usage_notification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-b.jsonl"
            write_jsonl(
                path,
                [
                    {
                        "method": "thread/tokenUsage/updated",
                        "params": {
                            "threadId": "thread-2",
                            "tokenUsage": {
                                "total": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                                "last": {"inputTokens": 40, "outputTokens": 5, "totalTokens": 45},
                                "modelContextWindow": 200000,
                            },
                        },
                    },
                    {
                        "method": "thread/settings/updated",
                        "params": {"threadSettings": {"model": "gpt-example", "modelProvider": "openai"}},
                    },
                ],
            )
            snapshot = parse_rollout(path)
            self.assertEqual(snapshot.session_id, "thread-2")
            self.assertEqual(snapshot.model, "gpt-example")
            self.assertEqual(snapshot.total_usage.total_tokens, 120)
            self.assertEqual(snapshot.last_usage.output_tokens, 5)
            self.assertEqual(snapshot.model_context_window, 200000)

    def test_uses_config_fallback_when_session_has_no_model_or_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            write_jsonl(path, [{"type": "session_meta", "payload": {"id": "x"}}])
            snapshot = parse_rollout(path, fallback_model="gpt-fallback", fallback_context_window=99_000)
            self.assertEqual(snapshot.model, "gpt-fallback")
            self.assertEqual(snapshot.model_context_window, 99_000)

    def test_bounded_reader_keeps_head_and_tail_without_loading_middle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.jsonl"
            head = json.dumps({"type": "session_meta", "payload": {"id": "head-id"}})
            tail = json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": None}})
            with path.open("w", encoding="utf-8") as handle:
                handle.write(head + "\n")
                for index in range(20_000):
                    handle.write(json.dumps({"type": "response_item", "payload": {"index": index, "text": "x" * 80}}) + "\n")
                handle.write(tail + "\n")
            lines = read_bounded_lines(path, head_bytes=256, tail_bytes=2048)
            self.assertIn(head, lines)
            self.assertIn(tail, lines)
            self.assertLess(len(lines), 100)


class RolloutDiscoveryTests(unittest.TestCase):
    def test_resolve_codex_home_prefers_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = tmp
            try:
                self.assertEqual(resolve_codex_home(), Path(tmp).resolve())
            finally:
                if old is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = old

    def test_discovers_newest_session_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_path = home / "sessions/2026/08/28/rollout-old.jsonl"
            new_path = home / "sessions/2026/08/29/rollout-new.jsonl"
            write_jsonl(old_path, [{"type": "session_meta", "payload": {"id": "old"}}])
            write_jsonl(new_path, [{"type": "session_meta", "payload": {"id": "new"}}])
            now = time.time()
            os.utime(old_path, (now - 100, now - 100))
            os.utime(new_path, (now, now))
            sessions = discover_sessions(home)
            self.assertEqual(sessions[0], new_path)
            self.assertEqual(read_latest_session(home).session_id, "new")

    def test_latest_session_exposes_selectable_session_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            older = home / "sessions/2026/08/28/rollout-older.jsonl"
            newer = home / "sessions/2026/08/29/rollout-newer.jsonl"
            write_jsonl(
                older,
                [
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-older",
                            "cwd": "C:/work/older",
                            "model_provider": "openai",
                        },
                    },
                    {
                        "type": "turn_context",
                        "payload": {"model": "gpt-older"},
                    },
                ],
            )
            write_jsonl(
                newer,
                [
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-newer",
                            "cwd": "C:/work/newer",
                            "model_provider": "openai",
                        },
                    },
                    {
                        "type": "turn_context",
                        "payload": {"model": "gpt-newer"},
                    },
                ],
            )
            now = time.time()
            os.utime(older, (now - 60, now - 60))
            os.utime(newer, (now, now))

            selected = read_latest_session(home, session_index=1)

            self.assertEqual(selected.session_id, "thread-older")
            self.assertEqual(selected.session_index, 1)
            self.assertEqual(len(selected.session_options), 2)
            self.assertEqual(selected.session_options[0].index, 0)
            self.assertEqual(selected.session_options[0].session_id, "thread-newer")
            self.assertEqual(selected.session_options[0].model, "gpt-newer")
            self.assertEqual(selected.session_options[1].cwd, "C:/work/older")


if __name__ == "__main__":
    unittest.main()
