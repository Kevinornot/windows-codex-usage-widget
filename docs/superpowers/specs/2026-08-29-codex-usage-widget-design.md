# Codex Usage Widget Design

## Purpose

Build a lightweight Windows 10/11 desktop widget that shows the Codex model, current context usage, token counters, ChatGPT/Codex rate-limit windows, reset times, and account token-usage summary without reading, storing, or displaying credentials.

## User experience

The app opens as a compact, frameless, always-on-top dark card. It is draggable from the header, supports opacity adjustment, refreshes session data every five seconds, refreshes account data every thirty seconds, and offers a right-click menu for refresh, session selection, auto-start, opacity, and exit. Missing or unsupported fields are shown as unavailable rather than estimated.

## Data sources

1. **Local rollout observer (read-only)**
   - Resolve Codex home from `CODEX_HOME`, falling back to `~/.codex`.
   - Find recent `sessions/**/rollout-*.jsonl` files and select the most recently modified session by default.
   - Parse the canonical `session_meta`, `turn_context`, and `event_msg/token_count` records.
   - Extract model, provider, working directory, thread/session id, total and last-turn token breakdown, model context window, and persisted rate-limit snapshots.
   - Read only bounded portions of the file (head plus tail) to avoid loading large histories.

2. **Codex App Server client**
   - Launch the existing `codex app-server` executable using the user's existing Codex authentication.
   - Perform the JSON-RPC initialize handshake.
   - Read `account/read`, `account/rateLimits/read`, and `account/usage/read` when supported.
   - Never inspect auth files or include environment secrets in logs.

3. **Config fallback**
   - Read only `~/.codex/config.toml` for fallback `model` and `model_context_window` values.

## Merge rules

- Current-session values: rollout record > config fallback > unavailable.
- Account/limit values: App Server response > latest rollout rate-limit snapshot > unavailable.
- App Server errors never erase a valid recent rollout snapshot.
- Data age and source status are visible in the UI.

## Context calculation

The widget displays the raw latest-context token total divided by the reported model context window. It also computes the Codex-style user-controllable percentage using a 12,000-token baseline. Both are labeled so the raw count is not confused with the normalized percentage.

## Architecture

- `models.py`: immutable data records and merge/display calculations.
- `rollout.py`: local session discovery and resilient JSONL parsing.
- `app_server.py`: subprocess lifecycle and JSON-RPC client.
- `config.py`: application settings, Codex config fallback, and Windows startup helpers.
- `coordinator.py`: background polling and snapshot merge.
- `ui.py`: Tkinter widget, menu, drag behavior, and rendering.
- `main.py`: entry point and logging setup.

The application uses only Python's standard library at runtime. Optional packaging uses PyInstaller through a provided Windows script.

## Failure handling

- Missing Codex CLI: local session data remains available and the limit area shows a clear App Server status.
- Unsupported account endpoint or API-key auth: account usage is marked unavailable; no fake limit is shown.
- Malformed/truncated JSONL line: skip the line and preserve the last valid snapshot.
- No local session: show config defaults and a diagnostic path.
- App Server timeout/crash: terminate the child safely, retry with exponential cooldown, and continue local polling.

## Security and privacy

The widget does not request an API key, read token files, transmit data, modify Codex sessions, or log prompt/response contents. It parses only metadata and token-count fields from local rollout files.

## Verification

Automated tests cover snake_case and camelCase token usage, session/model discovery, rate-limit parsing, bounded tail reading, snapshot merge rules, context percentages, JSON-RPC framing, and app-server failure behavior. Final verification includes unit tests, compile checks, source scans for credential patterns, and archive inspection.
