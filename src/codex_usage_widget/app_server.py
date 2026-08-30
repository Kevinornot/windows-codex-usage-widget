"""Minimal read-only client for the official Codex App Server JSON-RPC API."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import AccountUsage, AppServerSnapshot, RateLimitSet


class AppServerError(RuntimeError):
    """Raised when Codex App Server cannot satisfy a read request."""


def find_codex_executable() -> Path | None:
    override = os.environ.get("CODEX_BIN")
    if override:
        candidate = Path(override).expanduser()
        if candidate.exists():
            return candidate.resolve()

    located = shutil.which("codex")
    if located:
        return Path(located).resolve()

    if os.name == "nt":
        candidates: list[Path] = []
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        userprofile = os.environ.get("USERPROFILE")
        if appdata:
            candidates.extend(
                [Path(appdata) / "npm" / "codex.cmd", Path(appdata) / "npm" / "codex.exe"]
            )
        if localappdata:
            candidates.extend(
                [
                    Path(localappdata) / "Programs" / "Codex" / "codex.exe",
                    Path(localappdata) / "Microsoft" / "WinGet" / "Links" / "codex.exe",
                ]
            )
        if userprofile:
            candidates.extend(
                [
                    Path(userprofile) / ".local" / "bin" / "codex.exe",
                    Path(userprofile) / "scoop" / "shims" / "codex.exe",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
    return None


def build_codex_command(executable: Path, *, platform: str | None = None) -> list[str]:
    platform = platform or sys.platform
    executable = Path(executable)
    if platform.startswith("win") and executable.suffix.lower() in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        # The outer pair of quotes is required by cmd.exe when the executable path is quoted.
        command_text = f'""{executable}" app-server"'
        return [comspec, "/d", "/s", "/c", command_text]
    return [str(executable), "app-server"]


class JsonRpcProcess:
    """Line-delimited JSON-RPC process client with request correlation."""

    def __init__(self, command: Sequence[str], *, client_version: str = "1.0.0") -> None:
        if not command:
            raise ValueError("command cannot be empty")
        self.command = [str(part) for part in command]
        self.client_version = client_version
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[Mapping[str, Any]]] = {}
        self._next_id = 1
        self._started = False
        self._closing = threading.Event()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._notifications: deque[Mapping[str, Any]] = deque(maxlen=50)

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, timeout: float = 5.0) -> None:
        if self.is_running and self._started:
            return
        self.close()
        self._closing.clear()
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
        except (OSError, ValueError) as exc:
            raise AppServerError(f"Unable to start Codex App Server: {exc}") from exc

        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name="codex-app-server-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="codex-app-server-stderr",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()
        self._started = True
        try:
            self._call_started(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_usage_widget",
                        "title": "Codex Usage Widget",
                        "version": self.client_version,
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "optOutNotificationMethods": [
                            "item/agentMessage/delta",
                            "item/reasoning/summaryTextDelta",
                            "item/reasoning/textDelta",
                        ],
                    },
                },
                timeout=timeout,
            )
            self.notify("initialized", {})
        except Exception:
            self.close()
            raise

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for raw in process.stdout:
                if self._closing.is_set():
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, Mapping):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int) and ("result" in message or "error" in message):
                    with self._pending_lock:
                        waiter = self._pending.get(request_id)
                    if waiter is not None:
                        waiter.put(message)
                elif isinstance(request_id, int) and isinstance(message.get("method"), str):
                    # This observer has no server-request capabilities. Respond explicitly so
                    # app-server does not wait indefinitely (for example, external token refresh).
                    self._send(
                        {
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": "Codex Usage Widget does not handle server requests",
                            },
                        }
                    )
                else:
                    self._notifications.append(message)
        finally:
            self._fail_pending("Codex App Server closed its output stream")

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw in process.stderr:
            if self._closing.is_set():
                break
            text = raw.rstrip()
            if text:
                self._stderr_tail.append(text[:1000])

    def _fail_pending(self, reason: str) -> None:
        message: Mapping[str, Any] = {
            "error": {"code": -32000, "message": reason},
        }
        with self._pending_lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            try:
                waiter.put_nowait(message)
            except queue.Full:
                pass

    def _send(self, payload: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise AppServerError("Codex App Server is not running")
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        try:
            with self._write_lock:
                process.stdin.write(encoded + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise AppServerError(f"Unable to write to Codex App Server: {exc}") from exc

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        self._send({"method": method, "params": dict(params or {})})

    def _call_started(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            waiter: queue.Queue[Mapping[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
        try:
            payload: dict[str, Any] = {"method": method, "id": request_id}
            if params is not None:
                payload["params"] = dict(params)
            self._send(payload)
            try:
                response = waiter.get(timeout=max(0.01, timeout))
            except queue.Empty as exc:
                raise AppServerError(f"Codex App Server request '{method}' timed out") from exc
            error = response.get("error")
            if isinstance(error, Mapping):
                detail = error.get("message") or str(error)
                raise AppServerError(f"Codex App Server '{method}' error: {detail}")
            result = response.get("result", {})
            return result if isinstance(result, Mapping) else {"value": result}
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 8.0,
    ) -> Mapping[str, Any]:
        if not self.is_running or not self._started:
            self.start(timeout=min(5.0, timeout))
        return self._call_started(method, params, timeout=timeout)

    def close(self) -> None:
        self._closing.set()
        process = self._process
        self._process = None
        self._started = False
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                        process.wait(timeout=1.0)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            for stream in (process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
        for thread in (self._reader_thread, self._stderr_thread):
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self._reader_thread = None
        self._stderr_thread = None
        self._fail_pending("Codex App Server was closed")

    def __enter__(self) -> "JsonRpcProcess":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class CodexAppServerReader:
    """High-level reader for account, rate-limit, and activity summaries."""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        executable: Path | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.timeout = timeout
        if command is None:
            executable = executable or find_codex_executable()
            if executable is None:
                self._client: JsonRpcProcess | None = None
                self._missing_error = "Codex CLI was not found in PATH"
            else:
                self._client = JsonRpcProcess(build_codex_command(executable))
                self._missing_error = None
        else:
            self._client = JsonRpcProcess(command)
            self._missing_error = None

    def _ensure_client(self) -> JsonRpcProcess:
        if self._client is None:
            raise AppServerError(self._missing_error or "Codex App Server is unavailable")
        return self._client

    @staticmethod
    def _parse_limits(result: Mapping[str, Any]) -> tuple[tuple[RateLimitSet, ...], int | None]:
        parsed: list[RateLimitSet] = []
        by_id = result.get("rateLimitsByLimitId") or result.get("rate_limits_by_limit_id")
        if isinstance(by_id, Mapping):
            for key, raw in by_id.items():
                candidate = RateLimitSet.from_mapping(raw if isinstance(raw, Mapping) else None)
                if candidate is not None:
                    if candidate.limit_id is None:
                        candidate = RateLimitSet(
                            limit_id=str(key),
                            limit_name=candidate.limit_name,
                            primary=candidate.primary,
                            secondary=candidate.secondary,
                            plan_type=candidate.plan_type,
                            reached_type=candidate.reached_type,
                            credits_remaining=candidate.credits_remaining,
                        )
                    parsed.append(candidate)
        if not parsed:
            single = result.get("rateLimits") or result.get("rate_limits")
            candidate = RateLimitSet.from_mapping(single if isinstance(single, Mapping) else None)
            if candidate is not None:
                parsed.append(candidate)

        credits = result.get("rateLimitResetCredits") or result.get("rate_limit_reset_credits")
        reset_count: int | None = None
        if isinstance(credits, Mapping):
            value = credits.get("availableCount", credits.get("available_count"))
            try:
                reset_count = int(value) if value is not None else None
            except (TypeError, ValueError):
                reset_count = None
        return tuple(parsed), reset_count

    def read_snapshot(self) -> AppServerSnapshot:
        client = self._ensure_client()
        errors: list[str] = []
        account_type: str | None = None
        email: str | None = None
        plan_type: str | None = None
        requires_auth: bool | None = None
        limits: tuple[RateLimitSet, ...] = ()
        reset_count: int | None = None
        usage = AccountUsage()

        try:
            account_result = client.call(
                "account/read", {"refreshToken": False}, timeout=self.timeout
            )
            account = account_result.get("account")
            if isinstance(account, Mapping):
                account_type = str(account.get("type")) if account.get("type") is not None else None
                email = str(account.get("email")) if account.get("email") else None
                raw_plan = account.get("planType", account.get("plan_type"))
                plan_type = str(raw_plan) if raw_plan is not None else None
            raw_requires = account_result.get(
                "requiresOpenaiAuth", account_result.get("requires_openai_auth")
            )
            requires_auth = bool(raw_requires) if raw_requires is not None else None
        except AppServerError as exc:
            errors.append(str(exc))

        try:
            limit_result = client.call("account/rateLimits/read", timeout=self.timeout)
            limits, reset_count = self._parse_limits(limit_result)
            if plan_type is None:
                for limit in limits:
                    if limit.plan_type:
                        plan_type = limit.plan_type
                        break
        except AppServerError as exc:
            errors.append(str(exc))

        try:
            usage_result = client.call("account/usage/read", timeout=self.timeout)
            usage = AccountUsage.from_mapping(usage_result)
        except AppServerError as exc:
            errors.append(str(exc))

        status = "ok" if not errors else ("partial" if account_type or limits else "error")
        return AppServerSnapshot(
            account_type=account_type,
            email=email,
            plan_type=plan_type,
            requires_openai_auth=requires_auth,
            rate_limits=limits,
            reset_credit_count=reset_count,
            usage=usage,
            updated_at=time.time(),
            status=status,
            error=" | ".join(errors) if errors else None,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
