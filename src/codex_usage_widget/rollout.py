"""Read-only observation of Codex rollout JSONL files."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import RateLimitSet, SessionOption, SessionSnapshot, TokenBreakdown

DEFAULT_HEAD_BYTES = 256 * 1024
DEFAULT_TAIL_BYTES = 4 * 1024 * 1024
ACTIVE_SESSION_SECONDS = 180.0


def resolve_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".codex").resolve()


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def discover_sessions(codex_home: Path | None = None, *, limit: int = 50) -> list[Path]:
    """Return recent non-archived rollout files, newest first."""

    home = (codex_home or resolve_codex_home()).expanduser()
    sessions_dir = home / "sessions"
    if not sessions_dir.exists():
        return []
    try:
        candidates = [path for path in sessions_dir.rglob("rollout-*.jsonl") if path.is_file()]
    except OSError:
        return []
    candidates.sort(key=_safe_mtime, reverse=True)
    return candidates[: max(1, limit)]


def read_bounded_lines(
    path: Path,
    *,
    head_bytes: int = DEFAULT_HEAD_BYTES,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> list[str]:
    """Read complete JSONL lines from the head and tail of a potentially large file."""

    head_bytes = max(1, int(head_bytes))
    tail_bytes = max(1, int(tail_bytes))
    try:
        size = path.stat().st_size
    except OSError:
        return []

    try:
        with path.open("rb") as handle:
            if size <= head_bytes + tail_bytes:
                return handle.read().decode("utf-8", errors="replace").splitlines()

            head_raw = handle.read(head_bytes)
            # Drop a partial line at the end of the head chunk.
            if not head_raw.endswith((b"\n", b"\r")):
                newline = max(head_raw.rfind(b"\n"), head_raw.rfind(b"\r"))
                head_raw = head_raw[: newline + 1] if newline >= 0 else b""

            start = max(0, size - tail_bytes)
            handle.seek(start)
            tail_raw = handle.read()
            # Drop a partial line at the beginning of the tail chunk.
            if start > 0:
                newline = tail_raw.find(b"\n")
                tail_raw = tail_raw[newline + 1 :] if newline >= 0 else b""
    except OSError:
        return []

    head_lines = head_raw.decode("utf-8", errors="replace").splitlines()
    tail_lines = tail_raw.decode("utf-8", errors="replace").splitlines()
    return head_lines + tail_lines


def _get(mapping: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _parse_token_info(info: Mapping[str, Any] | None) -> tuple[TokenBreakdown, TokenBreakdown, int | None]:
    if not isinstance(info, Mapping):
        return TokenBreakdown(), TokenBreakdown(), None
    total_mapping = _get(info, "total_token_usage", "totalTokenUsage", "total")
    last_mapping = _get(info, "last_token_usage", "lastTokenUsage", "last")
    # A few historical clients persisted a single usage object instead of an info wrapper.
    if not isinstance(total_mapping, Mapping) and any(
        key in info for key in ("input_tokens", "inputTokens", "total_tokens", "totalTokens")
    ):
        total_mapping = info
    total = TokenBreakdown.from_mapping(total_mapping if isinstance(total_mapping, Mapping) else None)
    last = TokenBreakdown.from_mapping(last_mapping if isinstance(last_mapping, Mapping) else None)
    if last.is_empty and not total.is_empty:
        last = total
    window = _optional_int(_get(info, "model_context_window", "modelContextWindow"))
    return total, last, window


def _merge_limit(
    limits: dict[str, RateLimitSet],
    candidate: RateLimitSet | None,
    *,
    fallback_key: str = "codex",
) -> None:
    if candidate is None:
        return
    key = candidate.limit_id or candidate.limit_name or fallback_key
    limits[str(key)] = candidate


def _parse_rate_limit_container(value: Any) -> tuple[tuple[RateLimitSet, ...], str | None]:
    if not isinstance(value, Mapping):
        return (), None
    limits: dict[str, RateLimitSet] = {}
    plan_hint: str | None = None

    by_id = _get(value, "rate_limits_by_limit_id", "rateLimitsByLimitId")
    if isinstance(by_id, Mapping):
        for key, raw in by_id.items():
            candidate = RateLimitSet.from_mapping(raw if isinstance(raw, Mapping) else None)
            _merge_limit(limits, candidate, fallback_key=str(key))
            if candidate and candidate.plan_type:
                plan_hint = candidate.plan_type

    single = _get(value, "rate_limits", "rateLimits")
    if isinstance(single, Mapping):
        candidate = RateLimitSet.from_mapping(single)
        _merge_limit(limits, candidate)
        if candidate and candidate.plan_type:
            plan_hint = candidate.plan_type

    # A canonical rollout token_count stores the RateLimitSnapshot directly.
    direct = RateLimitSet.from_mapping(value)
    _merge_limit(limits, direct)
    if direct and direct.plan_type:
        plan_hint = direct.plan_type
    if plan_hint is None:
        plan_hint = _text(_get(value, "plan_type", "planType"))
    return tuple(limits.values()), plan_hint


def _iter_records(lines: Iterable[str]) -> tuple[list[Mapping[str, Any]], int]:
    records: list[Mapping[str, Any]] = []
    malformed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            malformed += 1
            continue
        if isinstance(value, Mapping):
            records.append(value)
    return records, malformed


def parse_rollout(
    path: Path,
    *,
    fallback_model: str | None = None,
    fallback_context_window: int | None = None,
    head_bytes: int = DEFAULT_HEAD_BYTES,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> SessionSnapshot:
    """Parse only Codex metadata and usage fields from a rollout file."""

    path = Path(path)
    lines = read_bounded_lines(path, head_bytes=head_bytes, tail_bytes=tail_bytes)
    records, malformed = _iter_records(lines)

    session_id: str | None = None
    model = fallback_model
    provider: str | None = None
    cwd: str | None = None
    source: str | None = None
    total_usage = TokenBreakdown()
    last_usage = TokenBreakdown()
    context_window = fallback_context_window
    limits: dict[str, RateLimitSet] = {}
    plan_hint: str | None = None
    record_updated_at: float | None = None

    for record in records:
        top_type = _text(_get(record, "type"))
        payload = _get(record, "payload", default={})
        if not isinstance(payload, Mapping):
            payload = {}
        record_updated_at = _timestamp(_get(record, "timestamp")) or record_updated_at

        if top_type == "session_meta":
            session_id = _text(_get(payload, "id", "session_id", "sessionId")) or session_id
            cwd = _text(_get(payload, "cwd")) or cwd
            provider = _text(_get(payload, "model_provider", "modelProvider")) or provider
            source_value = _get(payload, "source")
            if isinstance(source_value, Mapping):
                source_value = _get(source_value, "type", "kind")
            source = _text(source_value) or source
            model = _text(_get(payload, "model")) or model
            context_window = (
                _optional_int(_get(payload, "model_context_window", "modelContextWindow"))
                or context_window
            )

        elif top_type == "turn_context":
            model = _text(_get(payload, "model")) or model
            provider = _text(_get(payload, "model_provider", "modelProvider")) or provider
            cwd = _text(_get(payload, "cwd")) or cwd
            context_window = (
                _optional_int(_get(payload, "model_context_window", "modelContextWindow"))
                or context_window
            )

        elif top_type == "event_msg":
            event_type = _text(_get(payload, "type"))
            if event_type == "token_count":
                info = _get(payload, "info")
                parsed_total, parsed_last, parsed_window = _parse_token_info(
                    info if isinstance(info, Mapping) else None
                )
                if not parsed_total.is_empty:
                    total_usage = parsed_total
                if not parsed_last.is_empty:
                    last_usage = parsed_last
                context_window = parsed_window or context_window
                parsed_limits, parsed_plan = _parse_rate_limit_container(
                    _get(payload, "rate_limits", "rateLimits")
                )
                for candidate in parsed_limits:
                    _merge_limit(limits, candidate)
                plan_hint = parsed_plan or plan_hint
            elif event_type == "model_rerouted":
                model = _text(_get(payload, "to_model", "toModel")) or model

        method = _text(_get(record, "method"))
        params = _get(record, "params", default={})
        if not isinstance(params, Mapping):
            params = {}

        if method == "thread/tokenUsage/updated":
            session_id = _text(_get(params, "thread_id", "threadId")) or session_id
            token_usage = _get(params, "token_usage", "tokenUsage")
            parsed_total, parsed_last, parsed_window = _parse_token_info(
                token_usage if isinstance(token_usage, Mapping) else None
            )
            if not parsed_total.is_empty:
                total_usage = parsed_total
            if not parsed_last.is_empty:
                last_usage = parsed_last
            context_window = parsed_window or context_window

        elif method in {"thread/settings/updated", "threadSettings/updated"}:
            settings = _get(params, "thread_settings", "threadSettings", default=params)
            if isinstance(settings, Mapping):
                model = _text(_get(settings, "model")) or model
                provider = _text(_get(settings, "model_provider", "modelProvider")) or provider
                cwd = _text(_get(settings, "cwd")) or cwd

        elif method == "model/rerouted":
            model = _text(_get(params, "to_model", "toModel")) or model

        elif method == "account/rateLimits/updated":
            parsed_limits, parsed_plan = _parse_rate_limit_container(params)
            for candidate in parsed_limits:
                _merge_limit(limits, candidate)
            plan_hint = parsed_plan or plan_hint

    mtime = _safe_mtime(path)
    updated_at = max(value for value in (mtime, record_updated_at or 0.0) if value >= 0)
    status = "ok" if records else "unavailable"
    error = None if records else "No valid JSONL metadata found"
    return SessionSnapshot(
        session_id=session_id,
        path=path.resolve(),
        model=model,
        model_provider=provider,
        cwd=cwd,
        source=source,
        total_usage=total_usage,
        last_usage=last_usage,
        model_context_window=context_window,
        rate_limits=tuple(limits.values()),
        plan_type_hint=plan_hint,
        updated_at=updated_at or None,
        active=bool(mtime and (time.time() - mtime) <= ACTIVE_SESSION_SECONDS),
        status=status,
        error=error,
        malformed_lines=malformed,
    )


def read_latest_session(
    codex_home: Path | None = None,
    *,
    session_index: int = 0,
    fallback_model: str | None = None,
    fallback_context_window: int | None = None,
) -> SessionSnapshot:
    sessions = discover_sessions(codex_home)
    if not sessions:
        return SessionSnapshot(
            model=fallback_model,
            model_context_window=fallback_context_window,
            status="unavailable",
            error=f"No rollout files under {(codex_home or resolve_codex_home()) / 'sessions'}",
        )
    index = max(0, min(int(session_index), len(sessions) - 1))
    snapshot = parse_rollout(
        sessions[index],
        fallback_model=fallback_model,
        fallback_context_window=fallback_context_window,
    )
    options: list[SessionOption] = []
    for option_index, path in enumerate(sessions):
        preview = (
            snapshot
            if option_index == index
            else parse_rollout(
                path,
                fallback_model=fallback_model,
                fallback_context_window=fallback_context_window,
                head_bytes=64 * 1024,
                tail_bytes=128 * 1024,
            )
        )
        options.append(
            SessionOption(
                index=option_index,
                path=path.resolve(),
                session_id=preview.session_id,
                model=preview.model,
                cwd=preview.cwd,
                updated_at=preview.updated_at,
                active=preview.active,
            )
        )
    return SessionSnapshot(
        session_id=snapshot.session_id,
        path=snapshot.path,
        model=snapshot.model,
        model_provider=snapshot.model_provider,
        cwd=snapshot.cwd,
        source=snapshot.source,
        total_usage=snapshot.total_usage,
        last_usage=snapshot.last_usage,
        model_context_window=snapshot.model_context_window,
        rate_limits=snapshot.rate_limits,
        plan_type_hint=snapshot.plan_type_hint,
        updated_at=snapshot.updated_at,
        active=snapshot.active,
        status=snapshot.status,
        error=snapshot.error,
        malformed_lines=snapshot.malformed_lines,
        session_count=len(sessions),
        session_index=index,
        session_options=tuple(options),
    )
