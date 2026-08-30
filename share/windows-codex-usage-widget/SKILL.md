---
name: windows-codex-usage-widget
description: Use when a Windows user asks Codex to install, personalize, package, update, or troubleshoot a desktop Codex usage widget with quota, token, context, system-resource, and notification-area displays.
---

# Windows Codex Usage Widget

## Overview

Create a portable, privacy-safe Windows widget. Preserve live data, high-DPI clarity, and reliable notification-area hiding while treating names, paths, accounts, and hardware labels as user-specific.

## Inputs

Resolve these from the request or workspace:

- source folder containing `run_widget.pyw` and `src/codex_usage_widget`
- installation folder, if different from the source
- optional display suffix, avatar character, and custom GPU label
- whether startup registration is requested

Ask only for values that cannot be discovered safely. Never invent personal details.

## Workflow

1. Inspect the source, launchers, settings, UI tests, and repository instructions. Preserve unrelated changes.
2. Verify Windows and Python 3.11 or newer. Prefer an existing compatible runtime; do not install software without the required authorization.
3. When installing elsewhere, copy the complete application and verify relative imports and bundled assets.
4. Keep refresh responsibilities separate:
   - local session and resource data may refresh frequently;
   - official account limits default to a three-minute interval;
   - render only available limits and do not fabricate missing quota data.
5. Keep the compact view near `308x167`; use a `462`-pixel expanded width with content-driven height and keep the expanded window on-screen.
6. Use consistent glass-like cards, restrained radii, high-contrast text, vector or font icons, and high-DPI awareness. For Tkinter, prefer simulated glass; native Acrylic can blank GDI child controls.
7. Show the live model name. Add a user-provided profile suffix or avatar only when requested. Use detected hardware text unless the user explicitly supplies a custom label.
8. Make the hide control withdraw the window to the Windows notification area while monitoring continues. Verify 64-bit Win32 signatures for `CreateWindowExW`, `DefWindowProcW`, and cleanup calls. If tray initialization fails, report the cause instead of claiming the widget is hidden.
9. Test before and after each functional fix. Verify formatters, both geometries, resource labels, quota filtering, tray startup/hide/restore/exit, Python compilation, and one real launch.
10. Restart only the widget processes belonging to the resolved installation folder, then report the installed path and launcher.

## Privacy Contract

Before sharing or packaging, replace user-specific content with placeholders or runtime discovery:

| Data type | Portable representation |
|---|---|
| Person or device nickname | `<DISPLAY_NAME>` |
| Avatar | `<AVATAR_CHARACTER>` |
| Custom GPU title | `<GPU_LABEL>` or detected hardware |
| Install/source path | `<INSTALL_DIR>` / `<SOURCE_DIR>` |
| Account, session, project identifiers | runtime values, never examples |

Scan output for home paths, absolute paths, usernames, emails, session IDs, and copied usage values. Exclude screenshots and logs containing private data.

## Completion Evidence

Provide the exact portable folder, launcher name, tests executed, and whether the real tray icon was observed. Distinguish a notification-area icon from taskbar minimization.
