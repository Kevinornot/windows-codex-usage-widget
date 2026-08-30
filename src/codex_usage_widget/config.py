"""Application settings, Codex config fallback, and Windows startup integration."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ is required.
    tomllib = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class CodexConfigFallback:
    model: str | None = None
    model_context_window: int | None = None
    error: str | None = None


def read_codex_config(codex_home: Path) -> CodexConfigFallback:
    path = Path(codex_home) / "config.toml"
    if not path.exists():
        return CodexConfigFallback()
    if tomllib is None:
        return CodexConfigFallback(error="Python tomllib is unavailable; config fallback disabled")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return CodexConfigFallback(error=f"Unable to read Codex config: {exc}")
    model_raw = data.get("model") if isinstance(data, Mapping) else None
    window_raw = data.get("model_context_window") if isinstance(data, Mapping) else None
    model = str(model_raw).strip() if model_raw is not None else None
    if not model:
        model = None
    try:
        window = int(window_raw) if window_raw is not None else None
    except (TypeError, ValueError, OverflowError):
        window = None
    if window is not None and window <= 0:
        window = None
    return CodexConfigFallback(model=model, model_context_window=window)


@dataclass(frozen=True, slots=True)
class AppSettings:
    geometry: str = "462x250+24+60"
    opacity: float = 1.0
    auto_refresh: bool = True
    session_index: int = 0
    always_on_top: bool = True
    compact_mode: bool = True
    session_poll_seconds: float = 2.0
    account_poll_seconds: float = 180.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "AppSettings":
        if not isinstance(raw, Mapping):
            return cls()
        defaults = cls()
        geometry = raw.get("geometry", defaults.geometry)
        if not isinstance(geometry, str) or "x" not in geometry:
            geometry = defaults.geometry
        try:
            opacity = min(1.0, max(0.55, float(raw.get("opacity", defaults.opacity))))
        except (TypeError, ValueError):
            opacity = defaults.opacity
        try:
            index = max(0, int(raw.get("session_index", defaults.session_index)))
        except (TypeError, ValueError):
            index = defaults.session_index
        try:
            session_poll = min(
                60.0,
                max(1.0, float(raw.get("session_poll_seconds", defaults.session_poll_seconds))),
            )
        except (TypeError, ValueError):
            session_poll = defaults.session_poll_seconds
        try:
            account_poll = min(
                600.0,
                max(180.0, float(raw.get("account_poll_seconds", defaults.account_poll_seconds))),
            )
        except (TypeError, ValueError):
            account_poll = defaults.account_poll_seconds
        return cls(
            geometry=geometry,
            opacity=opacity,
            auto_refresh=bool(raw.get("auto_refresh", defaults.auto_refresh)),
            session_index=index,
            always_on_top=bool(raw.get("always_on_top", defaults.always_on_top)),
            compact_mode=bool(raw.get("compact_mode", defaults.compact_mode)),
            session_poll_seconds=session_poll,
            account_poll_seconds=account_poll,
        )


def default_settings_path() -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif os.environ.get("XDG_CONFIG_HOME"):
        base = Path(os.environ["XDG_CONFIG_HOME"])
    else:
        base = Path.home() / ".config"
    return base / "CodexUsageWidget" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self) -> AppSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return AppSettings()
        return AppSettings.from_mapping(raw if isinstance(raw, Mapping) else None)

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n"
        # Atomic replacement avoids a half-written settings file after a forced shutdown.
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def build_startup_script(executable: Path, launcher: Path | None = None) -> str:
    command = f'"{executable}"'
    if launcher is not None:
        command += f' "{launcher}"'
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'start "" {command}\r\n'
        "endlocal\r\n"
    )


def default_startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


class WindowsAutostart:
    FILE_NAME = "Codex Usage Widget.cmd"

    def __init__(
        self,
        *,
        startup_dir: Path | None = None,
        python_executable: Path | None = None,
        launcher: Path | None = None,
        direct_executable: bool = False,
    ) -> None:
        self.startup_dir = Path(startup_dir) if startup_dir is not None else default_startup_dir()
        if python_executable is None:
            current = Path(sys.executable)
            python_executable = (
                current.with_name("pythonw.exe")
                if os.name == "nt" and current.name.lower().startswith("python")
                else current
            )
        self.python_executable = Path(python_executable)
        self.launcher = (
            None
            if direct_executable
            else (
                Path(launcher)
                if launcher is not None
                else Path(__file__).resolve().parents[2] / "run_widget.pyw"
            )
        )

    @property
    def supported(self) -> bool:
        return self.startup_dir is not None

    @property
    def path(self) -> Path:
        if self.startup_dir is None:
            # Stable diagnostic path; enable() still raises a clear error.
            return Path(self.FILE_NAME)
        return self.startup_dir / self.FILE_NAME

    def is_enabled(self) -> bool:
        return self.supported and self.path.exists()

    def enable(self) -> None:
        if self.startup_dir is None:
            raise OSError("Windows Startup folder is unavailable")
        self.startup_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            build_startup_script(self.python_executable, self.launcher),
            encoding="utf-8-sig",
            newline="",
        )

    def disable(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise OSError(f"Unable to remove startup entry: {exc}") from exc

    def toggle(self) -> bool:
        if self.is_enabled():
            self.disable()
            return False
        self.enable()
        return True
