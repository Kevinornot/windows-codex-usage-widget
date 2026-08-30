"""Pure data models used by the Codex usage widget.

This module intentionally has no UI, filesystem, subprocess, or network side effects.
All mappings are parsed defensively because Codex rollout JSON uses snake_case while
app-server JSON-RPC uses camelCase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

CODEX_CONTEXT_BASELINE_TOKENS = 12_000


def _get(mapping: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class TokenBreakdown:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "TokenBreakdown":
        if not isinstance(mapping, Mapping):
            return cls()
        input_tokens = max(0, _as_int(_get(mapping, "input_tokens", "inputTokens")))
        cached_input_tokens = max(
            0, _as_int(_get(mapping, "cached_input_tokens", "cachedInputTokens"))
        )
        cache_write_input_tokens = max(
            0,
            _as_int(_get(mapping, "cache_write_input_tokens", "cacheWriteInputTokens")),
        )
        output_tokens = max(0, _as_int(_get(mapping, "output_tokens", "outputTokens")))
        reasoning_output_tokens = max(
            0,
            _as_int(_get(mapping, "reasoning_output_tokens", "reasoningOutputTokens")),
        )
        raw_total = _get(mapping, "total_tokens", "totalTokens")
        total_tokens = (
            max(0, _as_int(raw_total))
            if raw_total is not None
            else max(0, input_tokens + output_tokens)
        )
        return cls(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            output_tokens=output_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            total_tokens=total_tokens,
        )

    @property
    def non_cached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.input_tokens,
                self.cached_input_tokens,
                self.cache_write_input_tokens,
                self.output_tokens,
                self.reasoning_output_tokens,
                self.total_tokens,
            )
        )


@dataclass(frozen=True, slots=True)
class ContextUsage:
    last: TokenBreakdown = field(default_factory=TokenBreakdown)
    context_window: int | None = None

    @property
    def raw_used_tokens(self) -> int:
        return max(0, self.last.total_tokens)

    @property
    def raw_remaining_tokens(self) -> int | None:
        if self.context_window is None or self.context_window <= 0:
            return None
        return max(0, self.context_window - self.raw_used_tokens)

    @property
    def raw_used_percent(self) -> float | None:
        if self.context_window is None or self.context_window <= 0:
            return None
        return min(100.0, max(0.0, self.raw_used_tokens / self.context_window * 100.0))

    @property
    def codex_remaining_percent(self) -> float | None:
        """Return Codex's user-controllable context percentage.

        Codex reserves a fixed baseline for prompts/tools/compaction and subtracts it
        from both the numerator and denominator before calculating the percentage.
        """

        if self.context_window is None or self.context_window <= 0:
            return None
        if self.context_window <= CODEX_CONTEXT_BASELINE_TOKENS:
            return 0.0
        effective_window = self.context_window - CODEX_CONTEXT_BASELINE_TOKENS
        used = max(0, self.raw_used_tokens - CODEX_CONTEXT_BASELINE_TOKENS)
        remaining = max(0, effective_window - used)
        return min(100.0, max(0.0, remaining / effective_window * 100.0))

    @property
    def codex_used_percent(self) -> float | None:
        remaining = self.codex_remaining_percent
        return None if remaining is None else min(100.0, max(0.0, 100.0 - remaining))


@dataclass(frozen=True, slots=True)
class RateLimitWindow:
    used_percent: float = 0.0
    window_minutes: int | None = None
    resets_at: int | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "RateLimitWindow | None":
        if not isinstance(mapping, Mapping):
            return None
        used = min(
            100.0,
            max(0.0, _as_float(_get(mapping, "used_percent", "usedPercent"), 0.0)),
        )
        return cls(
            used_percent=used,
            window_minutes=_as_optional_int(
                _get(
                    mapping,
                    "window_minutes",
                    "windowMinutes",
                    "window_duration_mins",
                    "windowDurationMins",
                )
            ),
            resets_at=_as_optional_int(_get(mapping, "resets_at", "resetsAt")),
        )

    @property
    def remaining_percent(self) -> float:
        return min(100.0, max(0.0, 100.0 - self.used_percent))


@dataclass(frozen=True, slots=True)
class RateLimitSet:
    limit_id: str | None = None
    limit_name: str | None = None
    primary: RateLimitWindow | None = None
    secondary: RateLimitWindow | None = None
    plan_type: str | None = None
    reached_type: str | None = None
    credits_remaining: float | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "RateLimitSet | None":
        if not isinstance(mapping, Mapping):
            return None
        primary = RateLimitWindow.from_mapping(_get(mapping, "primary"))
        secondary = RateLimitWindow.from_mapping(_get(mapping, "secondary"))
        # Do not create an apparently valid limit from an unrelated object.
        if primary is None and secondary is None:
            return None
        raw_credits = _get(mapping, "credits")
        credits_remaining: float | None = None
        if isinstance(raw_credits, Mapping):
            candidate = _get(raw_credits, "balance", "remaining", "amount")
            if candidate is not None:
                credits_remaining = _as_float(candidate)
        elif raw_credits is not None and not isinstance(raw_credits, (list, tuple)):
            try:
                credits_remaining = float(raw_credits)
            except (TypeError, ValueError):
                pass
        return cls(
            limit_id=_as_optional_str(_get(mapping, "limit_id", "limitId")),
            limit_name=_as_optional_str(_get(mapping, "limit_name", "limitName")),
            primary=primary,
            secondary=secondary,
            plan_type=_as_optional_str(_get(mapping, "plan_type", "planType")),
            reached_type=_as_optional_str(
                _get(mapping, "rate_limit_reached_type", "rateLimitReachedType")
            ),
            credits_remaining=credits_remaining,
        )

    @property
    def display_name(self) -> str:
        return self.limit_name or self.limit_id or "Codex"


@dataclass(frozen=True, slots=True)
class DailyUsage:
    start_date: str
    tokens: int

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "DailyUsage | None":
        if not isinstance(mapping, Mapping):
            return None
        start_date = _as_optional_str(_get(mapping, "start_date", "startDate"))
        if start_date is None:
            return None
        return cls(start_date=start_date, tokens=max(0, _as_int(_get(mapping, "tokens"))))


@dataclass(frozen=True, slots=True)
class AccountUsage:
    lifetime_tokens: int | None = None
    peak_daily_tokens: int | None = None
    longest_running_turn_sec: int | None = None
    current_streak_days: int | None = None
    longest_streak_days: int | None = None
    daily_buckets: tuple[DailyUsage, ...] = ()
    today_tokens_override: int | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "AccountUsage":
        if not isinstance(mapping, Mapping):
            return cls()
        summary = _get(mapping, "summary", default={})
        buckets_raw = _get(mapping, "daily_usage_buckets", "dailyUsageBuckets", default=[])
        buckets: list[DailyUsage] = []
        if isinstance(buckets_raw, Sequence) and not isinstance(buckets_raw, (str, bytes)):
            for item in buckets_raw:
                bucket = DailyUsage.from_mapping(item if isinstance(item, Mapping) else None)
                if bucket is not None:
                    buckets.append(bucket)
        return cls(
            lifetime_tokens=_as_optional_int(
                _get(summary, "lifetime_tokens", "lifetimeTokens")
            ),
            peak_daily_tokens=_as_optional_int(
                _get(summary, "peak_daily_tokens", "peakDailyTokens")
            ),
            longest_running_turn_sec=_as_optional_int(
                _get(summary, "longest_running_turn_sec", "longestRunningTurnSec")
            ),
            current_streak_days=_as_optional_int(
                _get(summary, "current_streak_days", "currentStreakDays")
            ),
            longest_streak_days=_as_optional_int(
                _get(summary, "longest_streak_days", "longestStreakDays")
            ),
            daily_buckets=tuple(buckets),
        )

    @property
    def today_tokens(self) -> int | None:
        if self.today_tokens_override is not None:
            return self.today_tokens_override
        today = date.today().isoformat()
        for bucket in reversed(self.daily_buckets):
            if bucket.start_date == today:
                return bucket.tokens
        return None


@dataclass(frozen=True, slots=True)
class SessionOption:
    """Lightweight metadata used by the UI session selector."""

    index: int
    path: Path
    session_id: str | None = None
    model: str | None = None
    cwd: str | None = None
    updated_at: float | None = None
    active: bool = False


@dataclass(frozen=True, slots=True)
class SystemResourceSnapshot:
    """Best-effort local CPU, memory, GPU, and VRAM measurements."""

    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    gpu_percent: float | None = None
    vram_used_bytes: int | None = None
    vram_total_bytes: int | None = None
    gpu_name: str | None = None
    updated_at: float | None = None
    status: str = "unavailable"
    error: str | None = None


# A concise alias retained for callers that prefer usage terminology.
ResourceUsage = SystemResourceSnapshot


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str | None = None
    path: Path | None = None
    model: str | None = None
    model_provider: str | None = None
    cwd: str | None = None
    source: str | None = None
    total_usage: TokenBreakdown = field(default_factory=TokenBreakdown)
    last_usage: TokenBreakdown = field(default_factory=TokenBreakdown)
    model_context_window: int | None = None
    rate_limits: tuple[RateLimitSet, ...] = ()
    plan_type_hint: str | None = None
    updated_at: float | None = None
    active: bool = False
    status: str = "unavailable"
    error: str | None = None
    malformed_lines: int = 0
    session_count: int = 0
    session_index: int = 0
    session_options: tuple[SessionOption, ...] = ()

    @property
    def context(self) -> ContextUsage:
        return ContextUsage(last=self.last_usage, context_window=self.model_context_window)


@dataclass(frozen=True, slots=True)
class AppServerSnapshot:
    account_type: str | None = None
    email: str | None = None
    plan_type: str | None = None
    requires_openai_auth: bool | None = None
    rate_limits: tuple[RateLimitSet, ...] = ()
    reset_credit_count: int | None = None
    usage: AccountUsage = field(default_factory=AccountUsage)
    updated_at: float | None = None
    status: str = "unavailable"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WidgetSnapshot:
    model: str | None = None
    model_provider: str | None = None
    plan_type: str | None = None
    account_type: str | None = None
    email: str | None = None
    session_id: str | None = None
    session_path: Path | None = None
    cwd: str | None = None
    source: str | None = None
    total_usage: TokenBreakdown = field(default_factory=TokenBreakdown)
    last_usage: TokenBreakdown = field(default_factory=TokenBreakdown)
    context: ContextUsage = field(default_factory=ContextUsage)
    rate_limits: tuple[RateLimitSet, ...] = ()
    account_usage: AccountUsage = field(default_factory=AccountUsage)
    system_resources: SystemResourceSnapshot = field(default_factory=SystemResourceSnapshot)
    reset_credit_count: int | None = None
    session_updated_at: float | None = None
    account_updated_at: float | None = None
    session_active: bool = False
    session_status: str = "unavailable"
    app_server_status: str = "unavailable"
    malformed_lines: int = 0
    session_count: int = 0
    session_index: int = 0
    session_options: tuple[SessionOption, ...] = ()

    @property
    def resources(self) -> SystemResourceSnapshot:
        """Compatibility alias for the local resource snapshot."""

        return self.system_resources


def _status_text(status: str, error: str | None) -> str:
    if error:
        return f"{status}: {error}"
    return status


def merge_snapshots(
    session: SessionSnapshot | None,
    app: AppServerSnapshot | None,
    resources: SystemResourceSnapshot | None = None,
) -> WidgetSnapshot:
    session = session or SessionSnapshot()
    app = app or AppServerSnapshot()
    resources = resources or SystemResourceSnapshot()
    rate_limits = app.rate_limits or session.rate_limits
    plan_type = app.plan_type or session.plan_type_hint
    return WidgetSnapshot(
        model=session.model,
        model_provider=session.model_provider,
        plan_type=plan_type,
        account_type=app.account_type,
        email=app.email,
        session_id=session.session_id,
        session_path=session.path,
        cwd=session.cwd,
        source=session.source,
        total_usage=session.total_usage,
        last_usage=session.last_usage,
        context=session.context,
        rate_limits=rate_limits,
        account_usage=app.usage,
        system_resources=resources,
        reset_credit_count=app.reset_credit_count,
        session_updated_at=session.updated_at,
        account_updated_at=app.updated_at,
        session_active=session.active,
        session_status=_status_text(session.status, session.error),
        app_server_status=_status_text(app.status, app.error),
        malformed_lines=session.malformed_lines,
        session_count=session.session_count,
        session_index=session.session_index,
        session_options=session.session_options,
    )
