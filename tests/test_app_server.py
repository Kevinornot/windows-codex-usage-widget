from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.app_server import (  # noqa: E402
    AppServerError,
    CodexAppServerReader,
    JsonRpcProcess,
    build_codex_command,
)


class JsonRpcProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        fake = Path(__file__).with_name("fake_codex.py")
        self.client = JsonRpcProcess([sys.executable, str(fake)])
        self.client.start()

    def tearDown(self) -> None:
        self.client.close()

    def test_initialize_and_call(self) -> None:
        result = self.client.call("account/read", {"refreshToken": False}, timeout=1)
        self.assertEqual(result["account"]["type"], "chatgpt")

    def test_timeout_raises_clear_error(self) -> None:
        with self.assertRaises(AppServerError) as caught:
            self.client.call("hang", timeout=0.1)
        self.assertIn("timed out", str(caught.exception).lower())

    def test_remote_error_raises_clear_error(self) -> None:
        with self.assertRaises(AppServerError) as caught:
            self.client.call("unknown", timeout=1)
        self.assertIn("not found", str(caught.exception).lower())


class AppServerReaderTests(unittest.TestCase):
    def test_reads_account_limits_and_usage(self) -> None:
        fake = Path(__file__).with_name("fake_codex.py")
        reader = CodexAppServerReader(command=[sys.executable, str(fake)])
        try:
            snapshot = reader.read_snapshot()
        finally:
            reader.close()

        self.assertEqual(snapshot.account_type, "chatgpt")
        self.assertEqual(snapshot.plan_type, "pro")
        self.assertEqual(snapshot.email, "user@example.com")
        self.assertEqual(len(snapshot.rate_limits), 2)
        self.assertEqual(snapshot.rate_limits[0].limit_id, "codex")
        self.assertEqual(snapshot.reset_credit_count, 2)
        self.assertEqual(snapshot.usage.lifetime_tokens, 1_234_567)
        self.assertEqual(snapshot.usage.today_tokens, 12_345)
        self.assertEqual(snapshot.status, "ok")

    def test_windows_batch_command_is_wrapped_with_comspec(self) -> None:
        command = build_codex_command(Path(r"C:\Users\ExampleUser\AppData\Roaming\npm\codex.cmd"), platform="win32")
        self.assertTrue(command[0].lower().endswith(("cmd.exe", "cmd")))
        self.assertIn("app-server", command[-1])
        self.assertIn("codex.cmd", command[-1])


if __name__ == "__main__":
    unittest.main()
