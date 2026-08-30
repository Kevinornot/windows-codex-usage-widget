# Windows Codex Usage Widget — reusable prompt

Use `$windows-codex-usage-widget` to install or customize the supplied Windows Codex usage widget.

## Inputs

- Source folder: `<SOURCE_DIR>`
- Installation folder: `<INSTALL_DIR>`
- Optional display suffix: `<DISPLAY_NAME>`
- Optional avatar character: `<AVATAR_CHARACTER>`
- GPU title: `<GPU_LABEL>` or `AUTO`
- Register Windows startup: `YES` or `NO`

If a required path is not provided, locate the folder containing `run_widget.pyw` and `src/codex_usage_widget`. Ask before installing a new runtime or overwriting unrelated files.

## Desired result

Install a portable Windows desktop widget with these defaults:

- compact quota view near `308x167` and expanded width `462`;
- official Codex quota refresh every three minutes without visible flicker;
- available Codex weekly and compatible five-hour model limits, without duplicate context limits;
- live model name, optional profile suffix, and a high-DPI vector or font avatar;
- system resources above a compact Token section;
- CPU, memory, GPU, and VRAM usage with consistent typography;
- a restrained liquid-glass appearance that remains readable and does not blank Tkinter controls;
- a bottom expand/collapse control and no oversized blank footer;
- hiding to the Windows notification area rather than the taskbar, with working restore and exit actions;
- window positioning that keeps the expanded widget fully on-screen.

Use detected hardware information when GPU title is `AUTO`. Treat every value inside angle brackets as an input placeholder, not literal interface text.

## Privacy and verification

Remove personal names, device nicknames, usernames, email addresses, absolute paths, account/session identifiers, screenshots, and copied usage values from anything intended for sharing. Preserve private data only in the local runtime settings when the user explicitly requests it.

Run focused tests, Python compilation, a real application launch, and a real hide-to-notification-area check. Report the final folder, launcher, verification results, and any environment-specific limitation.
