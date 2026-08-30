# Codex Usage Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver a dependency-light Windows desktop widget that monitors Codex session tokens, context, model, and account limits from official/local read-only data sources.

**Architecture:** A standard-library Python package separates immutable models, local rollout parsing, Codex App Server JSON-RPC, polling coordination, and Tkinter presentation. Local session metadata updates every five seconds; account data updates less frequently and is merged without overwriting fresher valid data.

**Tech Stack:** Python 3.11+, Tkinter, subprocess, threading, JSON-RPC over stdio, unittest, optional PyInstaller.

**Spec:** `docs/superpowers/specs/2026-08-29-codex-usage-widget-design.md`

## Global Constraints

- Runtime dependencies: Python standard library only.
- Target: Windows 10/11; parsing and non-UI tests remain cross-platform.
- Never read credential files or extract, display, persist, upload, or log auth tokens, prompts, or response text.
- Treat missing limit/account data as unavailable; never synthesize quota values.
- Keep all Codex session/config access read-only.

---

### Task 1: Domain models and context calculations

**Files:**
- Create: `src/codex_usage_widget/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `TokenBreakdown`, `ContextUsage`, `RateLimitWindow`, `RateLimitSet`, `AccountUsage`, `SessionSnapshot`, `AppServerSnapshot`, `WidgetSnapshot`, `merge_snapshots()`.

- [x] Write tests for token mapping, normalized/raw context percentages, rate-limit remaining percentages, and merge precedence.
- [x] Run the tests and verify failure because the model module does not exist.
- [x] Implement immutable dataclasses and pure merge/format helpers.
- [x] Run the tests and verify they pass.

### Task 2: Rollout discovery and parsing

**Files:**
- Create: `src/codex_usage_widget/rollout.py`
- Test: `tests/test_rollout.py`

**Interfaces:**
- Consumes: model dataclasses from Task 1.
- Produces: `resolve_codex_home()`, `discover_sessions()`, `parse_rollout(path)`, `read_latest_session()`.

- [x] Write synthetic JSONL tests for canonical snake_case, app-server camelCase, malformed lines, model fallback, newest-session selection, and bounded reads.
- [x] Run the tests and verify failure.
- [x] Implement tolerant key lookup, safe head/tail iteration, metadata-only extraction, and file recency state.
- [x] Run the tests and verify they pass.

### Task 3: App Server JSON-RPC client

**Files:**
- Create: `src/codex_usage_widget/app_server.py`
- Test: `tests/test_app_server.py`
- Create: `tests/fake_codex.py`

**Interfaces:**
- Produces: `JsonRpcProcess`, `CodexAppServerReader`, `AppServerError`, `find_codex_executable()`.

- [x] Write tests against a fake stdio JSON-RPC server for initialize, account parsing, timeouts, stderr isolation, and shutdown.
- [x] Run the tests and verify failure.
- [x] Implement a line-delimited JSON-RPC subprocess client with reader threads and request correlation.
- [x] Implement account/rate-limit/usage response parsing into domain models.
- [x] Run the tests and verify they pass.

### Task 4: Settings, config fallback, startup integration, and coordinator

**Files:**
- Create: `src/codex_usage_widget/config.py`
- Create: `src/codex_usage_widget/coordinator.py`
- Test: `tests/test_config.py`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Produces: `AppSettings`, `SettingsStore`, `read_codex_config()`, `WindowsAutostart`, `SnapshotCoordinator`.

- [x] Write tests for JSON settings, TOML fallback, startup-command quoting, polling merge, stale account preservation, and graceful errors.
- [x] Run the tests and verify failure.
- [x] Implement settings/config helpers and coordinator background loop.
- [x] Run the tests and verify they pass.

### Task 5: Tkinter widget and entry point

**Files:**
- Create: `src/codex_usage_widget/ui.py`
- Create: `src/codex_usage_widget/main.py`
- Create: `src/codex_usage_widget/__init__.py`
- Create: `src/codex_usage_widget/__main__.py`
- Test: `tests/test_ui_helpers.py`

**Interfaces:**
- Consumes: `SnapshotCoordinator`, `WidgetSnapshot`, `SettingsStore`, `WindowsAutostart`.
- Produces: `CodexUsageWidget`, `main()`.

- [x] Write headless tests for display strings, reset countdowns, and limit ordering.
- [x] Run the tests and verify failure.
- [x] Implement the frameless always-on-top draggable card, progress bars, status labels, right-click menu, opacity, session cycling, and safe close.
- [x] Run the tests and verify they pass.

### Task 6: Windows launchers, packaging, documentation, and final verification

**Files:**
- Create: `run_widget.bat`
- Create: `build_exe.bat`
- Create: `install_autostart.bat`
- Create: `uninstall_autostart.bat`
- Create: `requirements.txt`
- Create: `README.md`
- Create: `LICENSE`

**Interfaces:**
- Produces: one-click source launcher and an optional local Windows EXE build path.

- [x] Add launch/build scripts with path-safe quoting and no credential handling.
- [x] Document installation, data sources, limitations, troubleshooting, and privacy behavior.
- [x] Run `python -m unittest discover -s tests -v`.
- [x] Run `python -m compileall -q src tests`.
- [x] Scan source and archive contents for secrets/auth file access.
- [x] Create a reproducible ZIP and inspect its manifest.
