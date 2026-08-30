"""Application entry point."""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Sequence

from .app_server import CodexAppServerReader
from .config import SettingsStore, WindowsAutostart, read_codex_config
from .coordinator import SnapshotCoordinator
from .models import (
    AccountUsage,
    AppServerSnapshot,
    DailyUsage,
    RateLimitSet,
    RateLimitWindow,
    SessionOption,
    SessionSnapshot,
    SystemResourceSnapshot,
    TokenBreakdown,
)
from .rollout import read_latest_session, resolve_codex_home
from .system_resources import SystemResourceReader
from .ui import CodexUsageWidget
from .windows_effects import enable_high_dpi_awareness


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex token and quota desktop widget")
    parser.add_argument("--demo", action="store_true", help="show realistic demo data")
    parser.add_argument(
        "--no-app-server",
        action="store_true",
        help="disable official account/rate-limit reads and use local rollout data only",
    )
    parser.add_argument("--codex-home", type=Path, help="override the Codex home directory")
    return parser


def _demo_session(index: int = 0) -> SessionSnapshot:
    now = time.time()
    demos = (
        {
            "session_id": "019c-demo-codex-widget",
            "model": "gpt-example",
            "cwd": r"C:\Projects\research",
            "total": 531_327,
            "last": TokenBreakdown(
                input_tokens=81_220,
                cached_input_tokens=46_104,
                output_tokens=9_407,
                reasoning_output_tokens=4_562,
                total_tokens=90_627,
            ),
            "age": 0,
        },
        {
            "session_id": "019c-demo-paper-polish",
            "model": "gpt-example",
            "cwd": r"C:\Projects\paper",
            "total": 284_190,
            "last": TokenBreakdown(
                input_tokens=49_810,
                cached_input_tokens=25_602,
                output_tokens=5_401,
                reasoning_output_tokens=2_120,
                total_tokens=55_211,
            ),
            "age": 780,
        },
        {
            "session_id": "019c-demo-data-analysis",
            "model": "gpt-example",
            "cwd": r"C:\Projects\analysis",
            "total": 806_420,
            "last": TokenBreakdown(
                input_tokens=101_442,
                cached_input_tokens=60_241,
                output_tokens=11_832,
                reasoning_output_tokens=6_235,
                total_tokens=113_274,
            ),
            "age": 3_600,
        },
    )
    selected_index = max(0, min(int(index), len(demos) - 1))
    selected = demos[selected_index]
    options = tuple(
        SessionOption(
            index=option_index,
            path=Path.home() / ".codex" / "sessions" / f"demo-{option_index + 1}.jsonl",
            session_id=str(item["session_id"]),
            model=str(item["model"]),
            cwd=str(item["cwd"]),
            updated_at=now - int(item["age"]),
            active=option_index == 0,
        )
        for option_index, item in enumerate(demos)
    )
    return SessionSnapshot(
        session_id=str(selected["session_id"]),
        path=options[selected_index].path,
        model=str(selected["model"]),
        model_provider="openai",
        cwd=str(selected["cwd"]),
        source="codex-app",
        total_usage=TokenBreakdown(
            input_tokens=max(0, int(selected["total"]) - 42_907),
            cached_input_tokens=322_014,
            output_tokens=42_907,
            reasoning_output_tokens=18_562,
            total_tokens=int(selected["total"]),
        ),
        last_usage=selected["last"],
        model_context_window=200_000,
        updated_at=now - int(selected["age"]),
        active=selected_index == 0,
        status="ok",
        session_count=len(demos),
        session_index=selected_index,
        session_options=options,
    )


def _demo_account() -> AppServerSnapshot:
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    return AppServerSnapshot(
        account_type="chatgpt",
        plan_type="pro",
        rate_limits=(
            RateLimitSet(
                limit_id="codex",
                limit_name="Codex",
                primary=RateLimitWindow(
                    used_percent=38,
                    window_minutes=300,
                    resets_at=int(now + 7_420),
                ),
                secondary=RateLimitWindow(
                    used_percent=64,
                    window_minutes=10_080,
                    resets_at=int(now + 278_400),
                ),
            ),
        ),
        reset_credit_count=1,
        usage=AccountUsage(
            lifetime_tokens=12_458_721,
            peak_daily_tokens=861_330,
            current_streak_days=12,
            longest_streak_days=31,
            daily_buckets=(DailyUsage(today, 421_850),),
        ),
        updated_at=now,
        status="ok",
    )


def _demo_resources() -> SystemResourceSnapshot:
    return SystemResourceSnapshot(
        cpu_percent=23.0,
        memory_percent=61.0,
        memory_used_bytes=int(9.8 * 1024**3),
        memory_total_bytes=16 * 1024**3,
        gpu_percent=17.0,
        vram_used_bytes=int(3.8 * 1024**3),
        vram_total_bytes=8 * 1024**3,
        gpu_name="NVIDIA GeForce RTX Demo",
        updated_at=time.time(),
        status="ok",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    codex_home = (args.codex_home or resolve_codex_home()).expanduser().resolve()
    settings_store = SettingsStore()
    settings = settings_store.load()
    fallback = read_codex_config(codex_home)

    app_server: CodexAppServerReader | None = None
    resource_monitor: SystemResourceReader | None = None
    if args.demo:
        session_reader = _demo_session
        app_reader = _demo_account
        resource_reader = _demo_resources
    else:
        session_reader = lambda index: read_latest_session(
            codex_home,
            session_index=index,
            fallback_model=fallback.model,
            fallback_context_window=fallback.model_context_window,
        )
        if args.no_app_server:
            app_reader = None
        else:
            app_server = CodexAppServerReader()
            app_reader = app_server.read_snapshot
        resource_monitor = SystemResourceReader()
        resource_reader = resource_monitor.read_snapshot

    coordinator = SnapshotCoordinator(
        session_reader=session_reader,
        app_reader=app_reader,
        resource_reader=resource_reader,
        session_poll_seconds=settings.session_poll_seconds,
        account_poll_seconds=settings.account_poll_seconds,
    )
    if getattr(sys, "frozen", False):
        autostart = WindowsAutostart(
            python_executable=Path(sys.executable),
            direct_executable=True,
        )
    else:
        autostart = WindowsAutostart(
            launcher=Path(__file__).resolve().parents[2] / "run_widget.pyw"
        )

    try:
        enable_high_dpi_awareness()
        root = tk.Tk()
        CodexUsageWidget(
            root,
            coordinator=coordinator,
            settings_store=settings_store,
            settings=settings,
            autostart=autostart,
            codex_home=codex_home,
        )
        root.mainloop()
    except tk.TclError as exc:
        print(f"Unable to start the desktop widget: {exc}")
        return 1
    finally:
        coordinator.stop()
        if app_server is not None:
            app_server.close()
    return 0
