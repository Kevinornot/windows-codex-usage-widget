"""Chinese white-glass Tkinter presentation for the Codex usage widget."""

from __future__ import annotations

import os
import queue
import re
import sys
import time
import tkinter as tk
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable, Iterable

from .config import AppSettings, SettingsStore, WindowsAutostart
from .coordinator import SnapshotCoordinator
from .models import RateLimitSet, SessionOption, SystemResourceSnapshot, WidgetSnapshot
from .tray import WindowsTrayIcon
from .windows_effects import apply_rounded_window_region, get_desktop_scale

# Light glass palette. Window-level opacity and optional Windows acrylic provide
# the translucency; these pale surfaces preserve text contrast.
SHELL = "#EAF3FA"
SHELL_HOVER = "#DFEDF7"
CARD = "#F4F9FC"
CARD_ALT = "#EAF3F9"
BORDER = "#FFFFFF"
BORDER_SOFT = "#D7E5EF"
GLASS_SHADOW = "#CEDDE8"
TEXT = "#162334"
MUTED = "#66788E"
DIM = "#91A1B1"
ACCENT = "#24C7A0"
ACCENT_DARK = "#11A884"
ACCENT_SOFT = "#DDF8F0"
WARNING = "#D99632"
DANGER = "#DF6570"
TRACK = "#DCE6EC"
WHITE = "#FFFFFF"
FONT = "Microsoft YaHei UI"
NUMBER_FONT = "Segoe UI"
ICON_FONT = "Segoe Fluent Icons"

WIDGET_WIDTH = 462
COMPACT_WIDTH = 308
COMPACT_HEIGHT = 167
COMPACT_OPACITY = 0.84
EXPANDED_MAX_HEIGHT = 900


def bundled_asset_path(name: str) -> Path:
    """Resolve an asset in a source checkout or PyInstaller one-file bundle."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    base = Path(bundle_root) if bundle_root else Path(__file__).resolve().parents[2]
    return base / "assets" / name


def format_tokens(value: int | None) -> str:
    if value is None:
        return "—"
    value = max(0, int(value))
    if value < 1_000:
        return f"{value:,}"
    if value < 1_000_000:
        return f"{value / 1_000:.1f}K"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.2f}M"
    return f"{value / 1_000_000_000:.2f}B"


def format_bytes_pair(used_bytes: int | None, total_bytes: int | None) -> str:
    if used_bytes is None or total_bytes is None or total_bytes <= 0:
        return "—"
    gib = 1024**3
    return f"{max(0, used_bytes) / gib:.1f} / {max(0, total_bytes) / gib:.1f} GB"


def format_model_display(model: str | None) -> str:
    """Present the live model name without user-specific decoration."""

    live_model = (model or "—").strip() or "—"
    if live_model.casefold().startswith("gpt-"):
        live_model = f"GPT-{live_model[4:]}"
    elif live_model != "—":
        live_model = f"GPT-{live_model}"
    else:
        live_model = "GPT-—"
    return live_model


def geometry_with_size(geometry: str, *, width: int, height: int) -> str:
    match = re.search(r"([+-]\d+)([+-]\d+)$", geometry or "")
    position = "" if match is None else f"{match.group(1)}{match.group(2)}"
    return f"{int(width)}x{int(height)}{position}"


def geometry_with_size_on_screen(
    geometry: str,
    *,
    width: int,
    height: int,
    screen_width: int,
    screen_height: int,
) -> str:
    """Resize while keeping positive-positioned windows fully visible."""

    match = re.search(r"([+-])(\d+)([+-])(\d+)$", geometry or "")
    if match is None:
        return f"{int(width)}x{int(height)}"
    x_sign, x_text, y_sign, y_text = match.groups()
    x = int(x_text)
    y = int(y_text)
    x_position = (
        f"-{x}"
        if x_sign == "-"
        else f"+{min(x, max(0, int(screen_width) - int(width)))}"
    )
    y_position = (
        f"-{y}"
        if y_sign == "-"
        else f"+{min(y, max(0, int(screen_height) - int(height)))}"
    )
    return f"{int(width)}x{int(height)}{x_position}{y_position}"


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


def format_duration_cn(seconds: int | float | None) -> str:
    """Format a duration using compact Simplified Chinese units."""

    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}天{hours}小时" if hours else f"{days}天"
    if hours:
        return f"{hours}小时{minutes}分" if minutes else f"{hours}小时"
    if minutes:
        return f"{minutes}分{secs}秒" if secs else f"{minutes}分"
    return f"{secs}秒"


def format_reset_countdown(resets_at: int | None, *, now: float | None = None) -> str:
    if resets_at is None:
        return "—"
    now = time.time() if now is None else now
    remaining = int(resets_at - now)
    return "now" if remaining <= 0 else format_duration(remaining)


def format_reset_countdown_cn(resets_at: int | None, *, now: float | None = None) -> str:
    if resets_at is None:
        return "未知时间"
    now = time.time() if now is None else now
    remaining = int(resets_at - now)
    return "即将重置" if remaining <= 0 else f"{format_duration_cn(remaining)}后重置"


def _window_label(minutes: int | None) -> str:
    if minutes is None:
        return "window"
    if minutes % 10_080 == 0:
        weeks = minutes // 10_080
        return f"{weeks * 7}d"
    if minutes % 1_440 == 0:
        return f"{minutes // 1_440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def format_window_label_cn(minutes: int | None) -> str:
    if minutes is None:
        return "窗口"
    if minutes % 10_080 == 0:
        return f"{minutes // 1_440} 天"
    if minutes % 1_440 == 0:
        return f"{minutes // 1_440} 天"
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return f"{minutes} 分钟"


def session_selector_labels(count: int) -> tuple[str, ...]:
    total = max(0, int(count))
    return tuple(
        f"会话 {index + 1}{'（最新）' if index == 0 else ''}"
        for index in range(total)
    )


def format_session_choice_label(
    path: Path,
    *,
    index: int,
    modified_at: float | None,
) -> str:
    """Build a compact human-readable label for a Codex rollout session."""

    stem = path.stem
    short_id = stem.rsplit("-", 1)[-1][:8] if "-" in stem else stem[-8:]
    when = (
        datetime.fromtimestamp(modified_at).strftime("%m-%d %H:%M")
        if modified_at is not None
        else "时间未知"
    )
    recent = "（最新）" if index == 0 else ""
    return f"会话 {index + 1}{recent} · {when} · {short_id}"


@dataclass(frozen=True, slots=True)
class RateLimitRow:
    limit_id: str
    limit_name: str
    window_label: str
    window_minutes: int | None
    used_percent: float
    remaining_percent: float
    resets_at: int | None
    reached_type: str | None = None


def rate_limit_rows(limits: Iterable[RateLimitSet]) -> tuple[RateLimitRow, ...]:
    general_row: RateLimitRow | None = None
    spark_row: RateLimitRow | None = None
    for limit in limits:
        limit_id = limit.limit_id or "codex"
        is_spark = "spark" in f"{limit_id} {limit.display_name}".casefold()
        target_minutes = 300 if is_spark else 10_080
        window = next(
            (
                candidate
                for candidate in (limit.primary, limit.secondary)
                if candidate is not None and candidate.window_minutes == target_minutes
            ),
            None,
        )
        if window is None:
            continue
        row = RateLimitRow(
            limit_id=limit_id,
            limit_name=limit.display_name,
            window_label=_window_label(window.window_minutes),
            window_minutes=window.window_minutes,
            used_percent=window.used_percent,
            remaining_percent=window.remaining_percent,
            resets_at=window.resets_at,
            reached_type=limit.reached_type,
        )
        if is_spark and spark_row is None:
            spark_row = row
        elif not is_spark and limit_id.casefold() == "codex" and general_row is None:
            general_row = row
    return tuple(row for row in (general_row, spark_row) if row is not None)


def format_limit_heading(row: RateLimitRow) -> str:
    if "spark" in row.limit_name.casefold():
        return f"GPT-5.3-Codex-Spark · {format_window_label_cn(row.window_minutes)}"
    return f"Codex · {format_window_label_cn(row.window_minutes)} · 通用"


def _truncate_middle(text: str | None, max_length: int = 48) -> str:
    if not text:
        return "—"
    if len(text) <= max_length:
        return text
    left = max_length // 2 - 1
    right = max_length - left - 1
    return f"{text[:left]}…{text[-right:]}"


def _percent_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"


def _age_text_cn(timestamp: float | None) -> str:
    if timestamp is None:
        return "未更新"
    age = max(0, int(time.time() - timestamp))
    return "刚刚" if age < 2 else f"{format_duration_cn(age)}前"


def _progress_color(used_percent: float | None) -> str:
    if used_percent is None:
        return DIM
    if used_percent >= 90:
        return DANGER
    if used_percent >= 70:
        return WARNING
    return ACCENT


def _rounded_polygon(
    canvas: tk.Canvas,
    canvas_width: int,
    canvas_height: int,
    radius: int,
    **kwargs: Any,
) -> int:
    radius = max(2, min(radius, canvas_width // 2, canvas_height // 2))
    points = (
        radius,
        0,
        canvas_width - radius,
        0,
        canvas_width - radius,
        0,
        canvas_width,
        0,
        canvas_width,
        radius,
        canvas_width,
        canvas_height - radius,
        canvas_width,
        canvas_height - radius,
        canvas_width,
        canvas_height,
        canvas_width - radius,
        canvas_height,
        radius,
        canvas_height,
        radius,
        canvas_height,
        0,
        canvas_height,
        0,
        canvas_height - radius,
        0,
        radius,
        0,
        radius,
        0,
        0,
        radius,
        0,
    )
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class RoundedCard(tk.Canvas):
    """A resize-aware rounded canvas containing a normal Tk frame."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        fill: str = CARD,
        outline: str = BORDER,
        radius: int = 9,
        padx: int = 10,
        pady: int = 7,
    ) -> None:
        super().__init__(
            master,
            bg=master.cget("bg"),
            highlightthickness=0,
            bd=0,
            height=20,
        )
        self.fill = fill
        self.outline = outline
        self.radius = radius
        self.padx = padx
        self.pady = pady
        self.content = tk.Frame(self, bg=fill, bd=0)
        self._window = self.create_window(padx, pady, anchor="nw", window=self.content)
        self.bind("<Configure>", self._redraw)
        self.content.bind("<Configure>", self._sync_height)

    def _sync_height(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        requested = max(20, self.content.winfo_reqheight() + self.pady * 2)
        if int(float(self.cget("height"))) != requested:
            self.configure(height=requested)
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        self.delete("card-shape")
        _rounded_polygon(
            self,
            width - 2,
            height - 2,
            self.radius,
            fill=GLASS_SHADOW,
            outline="",
            tags="card-shape",
        )
        self.move("card-shape", 1, 2)
        _rounded_polygon(
            self,
            width - 3,
            height - 3,
            self.radius,
            fill=self.fill,
            outline=self.outline,
            width=1,
            tags="card-shape",
        )
        self.tag_lower("card-shape")
        self.coords(self._window, self.padx, self.pady)
        self.itemconfigure(self._window, width=max(1, width - self.padx * 2))


class ProgressBar(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 7,
        bg: str | None = None,
        track: str = TRACK,
    ) -> None:
        super().__init__(
            master,
            height=height,
            bg=bg or master.cget("bg"),
            highlightthickness=0,
            bd=0,
        )
        self._value = 0.0
        self._color = ACCENT
        self._track = track
        self.bind("<Configure>", self._draw)

    def set(self, value: float | None, *, color: str | None = None) -> None:
        self._value = min(100.0, max(0.0, float(value or 0.0)))
        if color is not None:
            self._color = color
        self._draw()

    def _draw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        radius = max(1, height // 2)
        _rounded_polygon(self, width, height, radius, fill=self._track, outline="")
        fill_width = int(width * self._value / 100.0)
        if fill_width > 0:
            _rounded_polygon(
                self,
                max(height, fill_width),
                height,
                radius,
                fill=self._color,
                outline="",
            )


class FluentIcon(tk.Label):
    """DPI-aware Windows glyph icon rendered by the system font."""

    GLYPHS = {
        "cpu": "\uE950",
        "memory": "\uE7F4",
        "gpu": "\uE9D9",
        "vram": "\uE8B7",
        "clock": "\uE823",
        "spark": "\uE945",
    }
    COLORS = {
        "cpu": ("#E7F8F2", "#0D9A76"),
        "memory": ("#EAF1FF", "#3E70D8"),
        "gpu": ("#FFF2DF", "#C97D1D"),
        "vram": ("#F2EAFE", "#7952BC"),
        "clock": ("#E7F8F2", "#0D9A76"),
        "spark": ("#FFF2DF", "#D58B1C"),
    }

    def __init__(self, master: tk.Misc, *, kind: str, size: int = 12, bg: str | None = None) -> None:
        surface, ink = self.COLORS.get(kind, self.COLORS["cpu"])
        super().__init__(
            master,
            text=self.GLYPHS.get(kind, self.GLYPHS["cpu"]),
            font=(ICON_FONT, size),
            fg=ink,
            bg=surface if bg is None else bg,
            anchor="center",
            bd=0,
            padx=3,
            pady=1,
        )


class ScrollableBody(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=SHELL, bd=0)
        self.canvas = tk.Canvas(self, bg=SHELL, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=SHELL, bd=0)
        self._window = self.canvas.create_window(0, 0, anchor="nw", window=self.content)
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_content_configure(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)


TrayFactory = Callable[..., Any]


class CodexUsageWidget:
    def __init__(
        self,
        root: tk.Tk,
        *,
        coordinator: SnapshotCoordinator,
        settings_store: SettingsStore,
        settings: AppSettings,
        autostart: WindowsAutostart,
        codex_home: Path,
        tray_factory: TrayFactory | None = None,
        tray_icon_path: Path | None = None,
    ) -> None:
        self.root = root
        self.coordinator = coordinator
        self.settings_store = settings_store
        self.settings = settings
        self.autostart = autostart
        self.codex_home = codex_home
        self.compact_mode = bool(settings.compact_mode)
        self._snapshot = WidgetSnapshot()
        self._snapshot_queue: queue.SimpleQueue[WidgetSnapshot] = queue.SimpleQueue()
        self._ui_command_queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._after_ids: set[str] = set()
        self._drag_x = 0
        self._drag_y = 0
        self._limit_bars: list[ProgressBar] = []
        self._limit_signature: tuple[tuple[Any, ...], ...] | None = None
        self._limit_reset_labels: list[tuple[tk.Label, int | None, float]] = []
        self._resource_bars: dict[str, ProgressBar] = {}
        self._exiting = False
        self._fallback_minimized = False
        self._last_geometry = settings.geometry
        self.section_order = ("model", "limits", "resources", "tokens", "context", "activity")
        self.window_title_text = "Codex monitor"
        try:
            self.root.update_idletasks()
            self.display_scale = get_desktop_scale(self.root.winfo_id())
            self.root.tk.call("tk", "scaling", self.display_scale * 96.0 / 72.0)
        except (tk.TclError, TypeError, ValueError):
            self.display_scale = 1.0

        self._configure_window()
        self._build_ui()
        self._build_menu()

        factory = tray_factory or WindowsTrayIcon
        if tray_icon_path is None:
            candidate = bundled_asset_path("codex_usage_widget.ico")
            tray_icon_path = candidate if candidate.exists() else None
        self.tray = factory(
            title=self.window_title_text,
            icon_path=tray_icon_path,
            on_show=self._schedule(self.show_widget),
            on_toggle_details=self._schedule(self.toggle_details),
            on_exit=self._schedule(self.exit_app),
            is_compact=lambda: self.compact_mode,
        )
        try:
            self.tray.start()
        except Exception:
            pass

        self.coordinator.set_session_index(settings.session_index)
        self.coordinator.set_auto_refresh(settings.auto_refresh)
        self.coordinator.add_listener(self._receive_snapshot)
        self.coordinator.start()
        self._after(80, self._apply_glass)
        self._after(100, self._drain_snapshots)
        self._after(80, self._drain_ui_commands)
        self._after(1_000, self._tick)
        self._after(50, self._resize_for_mode)

    def _configure_window(self) -> None:
        self.root.title(self.window_title_text)
        self.root.configure(bg=BORDER)
        initial_width = self._px(COMPACT_WIDTH if self.compact_mode else WIDGET_WIDTH)
        initial_height = self._px(COMPACT_HEIGHT) if self.compact_mode else self._expanded_height()
        self.root.geometry(
            geometry_with_size(
                self.settings.geometry,
                width=initial_width,
                height=initial_height,
            )
        )
        self.root.minsize(self._px(COMPACT_WIDTH), self._px(150))
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.settings.always_on_top)
        self.root.attributes("-alpha", self._mode_opacity())
        self.root.protocol("WM_DELETE_WINDOW", self.hide_widget)
        self.root.bind("<Map>", self._on_window_mapped, add="+")

    def _apply_glass(self) -> None:
        if self._exiting:
            return
        try:
            self.root.update_idletasks()
            apply_rounded_window_region(
                self.root.winfo_id(),
                width=self.root.winfo_width(),
                height=self.root.winfo_height(),
                radius=self._px(10),
            )
        except tk.TclError:
            return

    def _px(self, value: int | float) -> int:
        return max(1, round(float(value) * self.display_scale))

    def _mode_opacity(self) -> float:
        return min(self.settings.opacity, COMPACT_OPACITY) if self.compact_mode else self.settings.opacity

    def _schedule(self, callback: Callable[[], None]) -> Callable[[], None]:
        def scheduled() -> None:
            if not self._exiting:
                self._ui_command_queue.put(callback)

        return scheduled

    def _after(self, delay_ms: int, callback: Callable[[], None]) -> str | None:
        if self._exiting:
            return None
        holder: dict[str, str] = {}

        def run() -> None:
            after_id = holder.get("id")
            if after_id is not None:
                self._after_ids.discard(after_id)
            if not self._exiting:
                callback()

        try:
            after_id = self.root.after(delay_ms, run)
        except tk.TclError:
            return None
        holder["id"] = after_id
        self._after_ids.add(after_id)
        return after_id

    def _drain_ui_commands(self) -> None:
        while True:
            try:
                callback = self._ui_command_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                continue
        self._after(80, self._drain_ui_commands)

    def _label(
        self,
        master: tk.Misc,
        text: str = "",
        *,
        size: int = 10,
        weight: str = "normal",
        color: str = TEXT,
        anchor: str = "w",
        number_font: bool = False,
        **kwargs: Any,
    ) -> tk.Label:
        return tk.Label(
            master,
            text=text,
            font=(NUMBER_FONT if number_font else FONT, size, weight),
            fg=color,
            bg=kwargs.pop("bg", master.cget("bg")),
            anchor=anchor,
            bd=0,
            **kwargs,
        )

    def _icon_button(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        size: int = 14,
    ) -> tk.Label:
        label = self._label(
            master,
            text,
            size=size,
            color=MUTED,
            anchor="center",
            cursor="hand2",
            padx=5,
            pady=5,
        )
        label.bind("<Button-1>", lambda _event: command())
        label.bind("<Enter>", lambda _event: label.configure(bg=SHELL_HOVER, fg=TEXT))
        label.bind("<Leave>", lambda _event: label.configure(bg=master.cget("bg"), fg=MUTED))
        return label

    def _card(self, parent: tk.Misc, *, pady: tuple[int, int] = (0, 8)) -> RoundedCard:
        card = RoundedCard(parent)
        card.pack(fill="x", padx=8, pady=pady)
        return card

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=SHELL, bd=0)
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        self.shell = shell

        header = tk.Frame(shell, bg=SHELL, height=40)
        header.pack(fill="x", padx=11, pady=(2, 0))
        header.pack_propagate(False)
        self.header = header

        logo = tk.Canvas(header, width=24, height=24, bg=SHELL, highlightthickness=0, bd=0)
        logo.pack(side="left", padx=(0, 7), pady=(8, 0))
        logo.create_line(3, 12, 9, 6, 15, 16, 21, 8, fill=ACCENT, width=4, capstyle="round")

        title_box = tk.Frame(header, bg=SHELL)
        title_box.pack(side="left", fill="y", expand=True)
        self._label(title_box, self.window_title_text, size=12, weight="bold").pack(anchor="w", pady=(8, 0))
        self.header_status = self._label(title_box, "正在读取数据…", size=8, color=MUTED)

        self.hide_button = self._icon_button(header, "—", self.hide_widget, size=16)
        self.hide_button.pack(side="right", pady=(4, 0))
        menu_button = self._icon_button(header, "•••", self._show_menu_at_pointer, size=11)
        menu_button.pack(side="right", pady=(5, 0), padx=(0, 2))

        self._bind_drag(header)
        self._bind_drag(logo)
        self._bind_drag(title_box)
        for child in title_box.winfo_children():
            self._bind_drag(child)
        header.bind("<Double-Button-1>", lambda _event: self.toggle_details())

        self.bottom_controls = tk.Frame(shell, bg=SHELL, height=19)
        self.bottom_controls.pack(side="bottom", fill="x", padx=8, pady=(0, 2))
        self.bottom_controls.pack_propagate(False)
        self.details_button = self._icon_button(
            self.bottom_controls,
            "⌄" if self.compact_mode else "⌃",
            self.toggle_details,
            size=13,
        )
        self.details_button.pack(anchor="center")

        self.body = ScrollableBody(shell)
        self.body.pack(fill="both", expand=True)
        body = self.body.content

        # The model card belongs to the expanded dashboard; compact mode keeps quota only.
        model_card = self._card(body)
        self.model_card = model_card
        model = model_card.content
        top = tk.Frame(model, bg=CARD)
        top.pack(fill="x")
        avatar_shell = tk.Frame(
            top,
            bg=ACCENT_SOFT,
            highlightbackground=WHITE,
            highlightthickness=1,
            bd=0,
            width=48,
            height=48,
        )
        avatar_shell.pack(side="left", padx=(0, 10))
        avatar_shell.pack_propagate(False)
        self.model_avatar = tk.Label(
            avatar_shell,
            text="C",
            font=("Segoe UI Variable Display", 22, "bold"),
            fg=ACCENT_DARK,
            bg=ACCENT_SOFT,
            anchor="center",
            bd=0,
        )
        self.model_avatar.pack(fill="both", expand=True)
        model_copy = tk.Frame(top, bg=CARD)
        model_copy.pack(side="left", fill="both", expand=True)
        model_heading = tk.Frame(model_copy, bg=CARD)
        model_heading.pack(fill="x")
        self._label(model_heading, "当前模型", size=9, color=MUTED).pack(side="left")
        self.active_badge = self._label(
            model_heading,
            "● 离线",
            size=8,
            weight="bold",
            color=DIM,
            anchor="e",
            bg=ACCENT_SOFT,
            padx=8,
            pady=3,
        )
        self.active_badge.pack(side="right")
        self.model_label = self._label(model_copy, "GPT-—", size=15, weight="bold", number_font=True)
        self.model_label.pack(fill="x", pady=(3, 0))
        self.model_meta = self._label(model_copy, "套餐 —  ·  提供方 —", size=8, color=MUTED)
        self.model_meta.pack(fill="x", pady=(0, 1))

        # Quota remains visible in both modes and is the entire compact view.
        limit_card = self._card(body)
        self.limit_card = limit_card
        limit = limit_card.content
        limit_top = tk.Frame(limit, bg=CARD)
        limit_top.pack(fill="x", pady=(0, 2))
        self.limit_top = limit_top
        self._label(limit_top, "限额", size=9, color=MUTED).pack(side="left")
        self.limit_summary = self._label(limit_top, "账户数据不可用", size=8, color=DIM, anchor="e")
        self.limit_summary.pack(side="right")
        self.limit_container = tk.Frame(limit, bg=CARD)
        self.limit_container.pack(fill="x")

        self.details_frame = tk.Frame(body, bg=SHELL, bd=0)
        self._build_resource_card(self.details_frame)
        self._build_token_card(self.details_frame)
        self._build_context_card(self.details_frame)
        self._build_activity_card(self.details_frame)
        if not self.compact_mode:
            self.details_frame.pack(fill="x")
        else:
            self.model_card.pack_forget()

        self._render_limits(())
        shell.bind("<Button-3>", self._show_menu)
        self.root.bind("<Button-3>", self._show_menu)
        self.root.bind("<Escape>", lambda _event: self.hide_widget())
        self.root.bind("<Control-r>", lambda _event: self._refresh())
        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<Button-4>", lambda _event: self._scroll_units(-3))
        self.root.bind("<Button-5>", lambda _event: self._scroll_units(3))

    def _build_token_card(self, parent: tk.Misc) -> None:
        card = self._card(parent)
        content = card.content
        header = tk.Frame(content, bg=CARD)
        header.pack(fill="x", pady=(0, 4))
        self._label(header, "Token 用量", size=9, color=MUTED).pack(side="left")
        self.token_scope_label = self._label(header, "当前上下文", size=8, color=DIM, anchor="e")
        self.token_scope_label.pack(side="right")

        grid = tk.Frame(content, bg=CARD)
        grid.pack(fill="x")
        for column in range(3):
            grid.grid_columnconfigure(column, weight=1, uniform="token")
        self.token_values: dict[str, tk.Label] = {}
        metrics = (
            ("input", "输入"),
            ("cached", "缓存"),
            ("output", "输出"),
            ("reasoning", "推理"),
            ("context_total", "上下文"),
            ("session_total", "会话累计"),
        )
        for index, (key, caption) in enumerate(metrics):
            cell = tk.Frame(
                grid,
                bg=CARD_ALT,
                highlightbackground=BORDER_SOFT,
                highlightthickness=1,
                bd=0,
            )
            cell.grid(row=index // 3, column=index % 3, sticky="nsew", padx=3, pady=3)
            value = self._label(
                cell,
                "—",
                size=11,
                weight="bold",
                anchor="center",
                bg=CARD_ALT,
                number_font=True,
            )
            value.pack(fill="x", pady=(5, 0))
            self._label(cell, caption, size=7, color=MUTED, anchor="center", bg=CARD_ALT).pack(
                fill="x", pady=(0, 5)
            )
            self.token_values[key] = value

    def _build_resource_card(self, parent: tk.Misc) -> None:
        card = self._card(parent)
        content = card.content
        header = tk.Frame(content, bg=CARD)
        header.pack(fill="x", pady=(0, 4))
        self._label(header, "系统资源", size=9, color=MUTED).pack(side="left")
        self.gpu_name_label = self._label(header, "GPU 数据按设备支持情况显示", size=8, color=DIM, anchor="e")
        self.gpu_name_label.pack(side="right")

        grid = tk.Frame(content, bg=CARD)
        grid.pack(fill="x")
        for column in range(2):
            grid.grid_columnconfigure(column, weight=1, uniform="resource")
        self.resource_values: dict[str, tk.Label] = {}
        resources = (
            ("cpu", "CPU占用"),
            ("memory", "内存占用"),
            ("gpu", "GPU占用"),
            ("vram", "显存占用"),
        )
        self.resource_icons: dict[str, FluentIcon] = {}
        for index, (key, caption) in enumerate(resources):
            cell = tk.Frame(
                grid,
                bg=CARD_ALT,
                bd=0,
                padx=10,
                pady=9,
            )
            cell.grid(row=index // 2, column=index % 2, sticky="nsew", padx=3, pady=3)
            top = tk.Frame(cell, bg=CARD_ALT)
            top.pack(fill="x")
            icon = FluentIcon(top, kind=key, size=14)
            icon.pack(side="left")
            self.resource_icons[key] = icon
            self._label(top, caption, size=9, color=MUTED, bg=CARD_ALT).pack(side="left", padx=(6, 0))
            value = self._label(
                top,
                "—",
                size=15,
                weight="bold",
                anchor="e",
                bg=CARD_ALT,
                number_font=True,
            )
            value.pack(side="right", fill="x", expand=True)
            bar = ProgressBar(cell, height=6, bg=CARD_ALT)
            bar.pack(fill="x", pady=(9, 0))
            self.resource_values[key] = value
            self._resource_bars[key] = bar

    def _build_context_card(self, parent: tk.Misc) -> None:
        card = self._card(parent)
        content = card.content
        header = tk.Frame(content, bg=CARD)
        header.pack(fill="x")
        self._label(header, "上下文", size=9, color=MUTED).pack(side="left")
        self.context_percent = self._label(
            header,
            "—",
            size=17,
            weight="bold",
            color=ACCENT,
            anchor="e",
            number_font=True,
        )
        self.context_percent.pack(side="right")

        self.session_menu = tk.Menu(
            self.root,
            tearoff=False,
            bg=WHITE,
            fg=TEXT,
            activebackground=ACCENT_SOFT,
            activeforeground=TEXT,
            bd=0,
            font=(FONT, 9),
        )
        self.session_button = tk.Menubutton(
            header,
            text="会话 — ▾",
            menu=self.session_menu,
            font=(FONT, 8),
            fg=MUTED,
            bg=CARD_ALT,
            activebackground=ACCENT_SOFT,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=8,
            pady=3,
        )
        self.session_button.pack(side="right", padx=(0, 10))

        self.context_numbers = self._label(content, "— / — tokens", size=14, weight="bold", number_font=True)
        self.context_numbers.pack(fill="x", pady=(4, 5))
        self.context_bar = ProgressBar(content, bg=CARD, height=8)
        self.context_bar.pack(fill="x")
        self.context_detail = self._label(
            content,
            "Codex 调整后用量 · 原始用量 —",
            size=8,
            color=MUTED,
        )
        self.context_detail.pack(fill="x", pady=(5, 0))

    def _build_activity_card(self, parent: tk.Misc) -> None:
        card = self._card(parent, pady=(0, 12))
        content = card.content
        stats = tk.Frame(content, bg=CARD)
        stats.pack(fill="x", pady=(0, 5))
        for column in range(4):
            stats.grid_columnconfigure(column, weight=1, uniform="activity")
        self.account_values: dict[str, tk.Label] = {}
        for column, (key, caption) in enumerate(
            (("today", "今日"), ("lifetime", "累计"), ("streak", "连续"), ("credits", "重置"))
        ):
            cell = tk.Frame(stats, bg=CARD)
            cell.grid(row=0, column=column, sticky="ew")
            value = self._label(
                cell,
                "—",
                size=11,
                weight="bold",
                anchor="center",
                number_font=True,
            )
            value.pack(fill="x")
            self._label(cell, caption, size=8, color=MUTED, anchor="center").pack(fill="x")
            self.account_values[key] = value
            if column:
                tk.Frame(stats, bg=BORDER_SOFT, width=1).grid(
                    row=0, column=column, sticky="nsw", pady=3
                )

        tk.Frame(content, bg=BORDER_SOFT, height=1).pack(fill="x", pady=(2, 5))
        self.session_label = self._label(content, "▣  会话 —", size=8, color=MUTED)
        self.session_label.pack(fill="x")
        self.cwd_label = self._label(content, "▱  工作目录 —", size=8, color=MUTED)
        self.cwd_label.pack(fill="x", pady=(2, 0))
        self.footer_status = self._label(content, "●  正在等待 Codex 数据…", size=8, color=MUTED)
        self.footer_status.pack(fill="x", pady=(2, 0))

    def _bind_drag(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event: tk.Event[tk.Misc]) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")
        self._last_geometry = self.root.geometry()

    def _build_menu(self) -> None:
        menu = tk.Menu(
            self.root,
            tearoff=False,
            bg=WHITE,
            fg=TEXT,
            activebackground=ACCENT_SOFT,
            activeforeground=TEXT,
            bd=0,
            font=(FONT, 9),
        )
        menu.add_command(label="立即刷新    Ctrl+R", command=self._refresh)
        menu.add_command(label="展开详情", command=self.toggle_details)
        self._details_menu_index = 1
        menu.add_command(label="隐藏小组件    Esc", command=self.hide_widget)
        self.auto_refresh_var = tk.BooleanVar(value=self.settings.auto_refresh)
        menu.add_checkbutton(
            label="自动刷新（会话 2 秒 · 限额 3 分钟）",
            variable=self.auto_refresh_var,
            command=self._toggle_auto_refresh,
        )
        menu.add_separator()
        menu.add_command(label="较新会话", command=lambda: self._cycle_session(-1))
        menu.add_command(label="较旧会话", command=lambda: self._cycle_session(1))
        menu.add_separator()
        self.topmost_var = tk.BooleanVar(value=self.settings.always_on_top)
        menu.add_checkbutton(
            label="始终置顶",
            variable=self.topmost_var,
            command=self._toggle_topmost,
        )
        self.autostart_var = tk.BooleanVar(value=self.autostart.is_enabled())
        menu.add_checkbutton(
            label="开机启动",
            variable=self.autostart_var,
            command=self._toggle_autostart,
            state="normal" if self.autostart.supported else "disabled",
        )
        opacity_menu = tk.Menu(
            menu,
            tearoff=False,
            bg=WHITE,
            fg=TEXT,
            activebackground=ACCENT_SOFT,
            activeforeground=TEXT,
            bd=0,
            font=(FONT, 9),
        )
        self.opacity_var = tk.IntVar(value=round(self.settings.opacity * 100))
        for percent in (82, 88, 93, 97):
            opacity_menu.add_radiobutton(
                label=f"{percent}%",
                value=percent,
                variable=self.opacity_var,
                command=self._set_opacity,
            )
        menu.add_cascade(label="透明度", menu=opacity_menu)
        menu.add_command(label="打开 Codex 会话目录", command=self._open_sessions_folder)
        menu.add_separator()
        menu.add_command(label="退出", command=self.exit_app)
        self.menu = menu

    def _update_menu_labels(self) -> None:
        self.menu.entryconfigure(
            self._details_menu_index,
            label="展开详情" if self.compact_mode else "收起详情",
        )

    def _show_menu_at_pointer(self) -> None:
        x, y = self.root.winfo_pointerxy()
        self._post_menu(x, y)

    def _show_menu(self, event: tk.Event[tk.Misc]) -> None:
        self._post_menu(event.x_root, event.y_root)

    def _post_menu(self, x: int, y: int) -> None:
        self._update_menu_labels()
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def _receive_snapshot(self, snapshot: WidgetSnapshot) -> None:
        self._snapshot_queue.put(snapshot)

    def _drain_snapshots(self) -> None:
        if self._exiting:
            return
        latest: WidgetSnapshot | None = None
        while True:
            try:
                latest = self._snapshot_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._snapshot = latest
            self._render(latest)
        self._after(150, self._drain_snapshots)

    def _render(self, snapshot: WidgetSnapshot) -> None:
        self.model_label.config(text=format_model_display(snapshot.model))
        meta = "  ·  ".join(
            part
            for part in (
                snapshot.plan_type or "套餐未知",
                snapshot.model_provider or "提供方未知",
                snapshot.source or "本地会话",
            )
            if part
        )
        self.model_meta.config(text=meta)
        if snapshot.session_active:
            self.active_badge.config(text="● 最近", fg=ACCENT_DARK, bg=ACCENT_SOFT)
        elif snapshot.session_status.startswith("ok"):
            self.active_badge.config(text="● 历史", fg=MUTED, bg=CARD_ALT)
        else:
            self.active_badge.config(text="● 离线", fg=DANGER, bg=CARD_ALT)

        context = snapshot.context
        used_percent = context.codex_used_percent
        self.context_percent.config(text=_percent_text(used_percent))
        self.context_numbers.config(
            text=f"{format_tokens(context.raw_used_tokens)} / "
            f"{format_tokens(context.context_window)} tokens"
        )
        self.context_bar.set(used_percent, color=_progress_color(used_percent))
        raw_used = _percent_text(context.raw_used_percent)
        raw_remaining = format_tokens(context.raw_remaining_tokens)
        self.context_detail.config(
            text=f"Codex 调整后用量 · 原始 {raw_used} · 原始剩余 {raw_remaining}"
        )

        last = snapshot.last_usage
        self.token_values["input"].config(text=format_tokens(last.input_tokens))
        self.token_values["cached"].config(text=format_tokens(last.cached_input_tokens))
        self.token_values["output"].config(text=format_tokens(last.output_tokens))
        self.token_values["reasoning"].config(text=format_tokens(last.reasoning_output_tokens))
        self.token_values["context_total"].config(text=format_tokens(last.total_tokens))
        self.token_values["session_total"].config(text=format_tokens(snapshot.total_usage.total_tokens))

        self._render_resources(snapshot.system_resources)
        self._render_limits(snapshot.rate_limits)
        self._render_session_selector(snapshot)

        usage = snapshot.account_usage
        self.account_values["today"].config(text=format_tokens(usage.today_tokens))
        self.account_values["lifetime"].config(text=format_tokens(usage.lifetime_tokens))
        self.account_values["streak"].config(
            text="—" if usage.current_streak_days is None else f"{usage.current_streak_days}天"
        )
        self.account_values["credits"].config(
            text="—" if snapshot.reset_credit_count is None else str(snapshot.reset_credit_count)
        )
        count = max(0, snapshot.session_count)
        current = snapshot.session_index + 1 if count else 0
        self.session_label.config(
            text=f"▣  会话 {current}/{count or '—'}  ·  {_truncate_middle(snapshot.session_id, 32)}"
        )
        self.cwd_label.config(text=f"▱  工作目录  {_truncate_middle(snapshot.cwd, 48)}")
        self._update_status_text()
        self._after(0, self._resize_for_mode)

    def _render_resources(self, resources: SystemResourceSnapshot) -> None:
        self.resource_values["cpu"].config(text=_percent_text(resources.cpu_percent))
        self.resource_values["memory"].config(text=_percent_text(resources.memory_percent))
        self.resource_values["gpu"].config(text=_percent_text(resources.gpu_percent))
        self.resource_values["vram"].config(
            text=format_bytes_pair(resources.vram_used_bytes, resources.vram_total_bytes)
        )
        self._resource_bars["cpu"].set(resources.cpu_percent)
        self._resource_bars["memory"].set(resources.memory_percent)
        self._resource_bars["gpu"].set(resources.gpu_percent)
        vram_percent = None
        if resources.vram_used_bytes is not None and resources.vram_total_bytes:
            vram_percent = resources.vram_used_bytes / resources.vram_total_bytes * 100.0
        self._resource_bars["vram"].set(vram_percent)
        self.gpu_name_label.config(
            text=_truncate_middle(resources.gpu_name or "GPU 数据按设备支持情况显示", 30)
        )

    def _render_limits(self, limits: Iterable[RateLimitSet]) -> None:
        rows = rate_limit_rows(limits)
        signature = tuple(
            (
                row.limit_id,
                row.limit_name,
                row.window_minutes,
                row.used_percent,
                row.resets_at,
            )
            for row in rows
        ) + (("compact", self.compact_mode),)
        if signature == self._limit_signature:
            return
        self._limit_signature = signature
        for child in self.limit_container.winfo_children():
            child.destroy()
        self._limit_bars.clear()
        self._limit_reset_labels.clear()
        if not rows:
            self._label(
                self.limit_container,
                "暂未获取官方额度；本地 Token 与上下文监控仍可使用。",
                size=8,
                color=MUTED,
            ).pack(fill="x", pady=(4, 3))
            self.limit_summary.config(text="账户数据不可用")
            return

        self.limit_summary.config(text=f"{len(rows)} 项")
        for index, row in enumerate(rows):
            if index:
                tk.Frame(self.limit_container, bg=BORDER_SOFT, height=1).pack(
                    fill="x", pady=2 if self.compact_mode else 4
                )
            top = tk.Frame(self.limit_container, bg=CARD)
            top.pack(fill="x")
            icon = FluentIcon(
                top,
                kind="spark" if "spark" in row.limit_name.casefold() else "clock",
                size=9 if self.compact_mode else 11,
            )
            icon.pack(side="left", padx=(0, 5))
            self._label(
                top,
                format_limit_heading(row),
                size=8 if self.compact_mode else 10,
                weight="bold",
            ).pack(side="left")
            self._label(
                top,
                f"剩余 {row.remaining_percent:.0f}%",
                size=8 if self.compact_mode else 10,
                weight="bold",
                color=_progress_color(row.used_percent),
                anchor="e",
            ).pack(side="right")
            bar = ProgressBar(self.limit_container, bg=CARD, height=4 if self.compact_mode else 6)
            bar.pack(fill="x", pady=(2 if self.compact_mode else 4, 1 if self.compact_mode else 3))
            bar.set(row.used_percent, color=_progress_color(row.used_percent))
            self._limit_bars.append(bar)
            reset_label = self._label(
                self.limit_container,
                f"已用 {row.used_percent:.0f}%  ·  {format_reset_countdown_cn(row.resets_at)}",
                size=6 if self.compact_mode else 8,
                color=MUTED,
            )
            reset_label.pack(fill="x")
            self._limit_reset_labels.append((reset_label, row.resets_at, row.used_percent))

    def _session_option_menu_label(self, option: SessionOption) -> str:
        model = option.model or "模型未知"
        project = Path(option.cwd).name if option.cwd else "目录未知"
        base = format_session_choice_label(
            option.path,
            index=option.index,
            modified_at=option.updated_at,
        )
        return f"{base} · {model} · {project}"

    def _render_session_selector(self, snapshot: WidgetSnapshot) -> None:
        self.session_menu.delete(0, "end")
        options = snapshot.session_options
        if options:
            for option in options[:20]:
                prefix = "✓ " if option.index == snapshot.session_index else "   "
                self.session_menu.add_command(
                    label=prefix + self._session_option_menu_label(option),
                    command=lambda index=option.index: self.select_session(index),
                )
            count = snapshot.session_count or len(options)
        else:
            labels = session_selector_labels(snapshot.session_count)
            for index, label in enumerate(labels[:20]):
                prefix = "✓ " if index == snapshot.session_index else "   "
                self.session_menu.add_command(
                    label=prefix + label,
                    command=lambda selected=index: self.select_session(selected),
                )
            count = snapshot.session_count
        current = snapshot.session_index + 1 if count else 0
        self.session_button.config(text=f"会话 {current}/{count or '—'} ▾")

    def _update_status_text(self) -> None:
        snapshot = self._snapshot
        session_age = _age_text_cn(snapshot.session_updated_at)
        account_age = _age_text_cn(snapshot.account_updated_at)
        rows = rate_limit_rows(snapshot.rate_limits)
        if rows:
            self.limit_summary.config(text=f"{len(rows)} 项 · {account_age}更新")
        count = max(0, snapshot.session_count)
        current = snapshot.session_index + 1 if count else 0
        self.session_button.config(
            text=f"会话 {current}/{count or '—'} · {session_age}更新 ▾"
        )
        session_ok = snapshot.session_status.startswith("ok")
        account_ok = snapshot.app_server_status.startswith(("ok", "partial"))
        if session_ok and account_ok:
            message = "●  本地会话 + 官方账户数据已连接"
            color = ACCENT_DARK
        elif session_ok:
            message = f"●  本地会话已连接 · 限额：{snapshot.app_server_status}"
            color = WARNING
        else:
            message = f"●  会话：{snapshot.session_status} · 限额：{snapshot.app_server_status}"
            color = DANGER
        if hasattr(self, "footer_status"):
            self.footer_status.config(text=_truncate_middle(message, 88), fg=color)

    def _tick(self) -> None:
        if self._exiting:
            return
        self._update_status_text()
        for label, resets_at, used_percent in tuple(self._limit_reset_labels):
            try:
                label.config(
                    text=f"已用 {used_percent:.0f}%  ·  {format_reset_countdown_cn(resets_at)}"
                )
            except tk.TclError:
                continue
        self._after(1_000, self._tick)

    def _expanded_height(self) -> int:
        try:
            screen_height = self.root.winfo_screenheight()
        except tk.TclError:
            screen_height = 900
        if not hasattr(self, "body"):
            requested = self._px(720)
        else:
            try:
                self.root.update_idletasks()
                requested = (
                    self.header.winfo_reqheight()
                    + self.body.content.winfo_reqheight()
                    + self.bottom_controls.winfo_reqheight()
                    + self._px(8)
                )
            except tk.TclError:
                requested = self._px(720)
        return min(max(self._px(480), requested), self._px(EXPANDED_MAX_HEIGHT), screen_height - self._px(36))

    def _resize_for_mode(self) -> None:
        if self._exiting:
            return
        try:
            current = self.root.geometry() or self._last_geometry
            target_width = self._px(COMPACT_WIDTH if self.compact_mode else WIDGET_WIDTH)
            target_height = self._px(COMPACT_HEIGHT) if self.compact_mode else self._expanded_height()
            geometry = geometry_with_size_on_screen(
                current,
                width=target_width,
                height=target_height,
                screen_width=self.root.winfo_screenwidth(),
                screen_height=self.root.winfo_screenheight(),
            )
            self.root.geometry(geometry)
            self._last_geometry = geometry
            self.root.attributes("-alpha", self._mode_opacity())
            if self.compact_mode:
                self.body.canvas.yview_moveto(0.0)
            self._after(0, self._apply_glass)
        except tk.TclError:
            return

    def toggle_details(self) -> None:
        self.compact_mode = not self.compact_mode
        if self.compact_mode:
            self.model_card.pack_forget()
            self.details_frame.pack_forget()
            self.details_button.config(text="⌄")
        else:
            self.model_card.pack(fill="x", padx=12, pady=(0, 8), before=self.limit_card)
            self.details_frame.pack(fill="x")
            self.details_button.config(text="⌃")
        self.settings = replace(self.settings, compact_mode=self.compact_mode)
        self._update_menu_labels()
        self._render_limits(self._snapshot.rate_limits)
        self._resize_for_mode()
        self._after(0, self._apply_glass)

    def select_session(self, index: int) -> None:
        self.coordinator.set_session_index(index)
        self.settings = replace(self.settings, session_index=max(0, int(index)))
        self.coordinator.request_refresh(include_account=False)

    def _cycle_session(self, delta: int) -> None:
        selected = self.coordinator.cycle_session(delta)
        self.settings = replace(self.settings, session_index=selected)
        self.coordinator.request_refresh(include_account=False)

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        if self.compact_mode:
            return
        delta = -1 if event.delta > 0 else 1
        self._scroll_units(delta * 3)

    def _scroll_units(self, units: int) -> None:
        if not self.compact_mode:
            self.body.canvas.yview_scroll(units, "units")

    def _refresh(self) -> None:
        if hasattr(self, "footer_status"):
            self.footer_status.config(text="●  正在刷新…", fg=ACCENT_DARK)
        self.coordinator.request_refresh(include_account=True)

    def _toggle_auto_refresh(self) -> None:
        enabled = self.auto_refresh_var.get()
        self.coordinator.set_auto_refresh(enabled)
        self.settings = replace(self.settings, auto_refresh=enabled)

    def _toggle_topmost(self) -> None:
        enabled = self.topmost_var.get()
        self.root.attributes("-topmost", enabled)
        self.settings = replace(self.settings, always_on_top=enabled)

    def _toggle_autostart(self) -> None:
        try:
            enabled = self.autostart.toggle()
        except OSError as exc:
            self.autostart_var.set(self.autostart.is_enabled())
            messagebox.showerror("Codex 监控器", str(exc), parent=self.root)
        else:
            self.autostart_var.set(enabled)

    def _set_opacity(self) -> None:
        opacity = self.opacity_var.get() / 100.0
        self.settings = replace(self.settings, opacity=opacity)
        self.root.attributes("-alpha", self._mode_opacity())

    def _open_sessions_folder(self) -> None:
        target = self.codex_home / "sessions"
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.spawnlp(os.P_NOWAIT, "open", "open", str(target))
            else:
                os.spawnlp(os.P_NOWAIT, "xdg-open", "xdg-open", str(target))
        except (OSError, AttributeError) as exc:
            messagebox.showerror("Codex 监控器", f"无法打开 {target}：{exc}", parent=self.root)

    def show_widget(self) -> None:
        if self._exiting:
            return
        try:
            if self._fallback_minimized:
                self.root.deiconify()
                self._restore_borderless_window()
            else:
                self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self._after(80, lambda: self.root.attributes("-topmost", self.topmost_var.get()))
            self._after(100, self._apply_glass)
        except tk.TclError:
            return

    def _on_window_mapped(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self._fallback_minimized and not self._exiting:
            self._after(0, self._restore_borderless_window)

    def _restore_borderless_window(self) -> None:
        if self._exiting or not self._fallback_minimized:
            return
        try:
            if self.root.state() == "iconic":
                return
            self.root.overrideredirect(True)
            self._fallback_minimized = False
            self.root.lift()
            self._apply_glass()
        except tk.TclError:
            return

    def hide_widget(self) -> None:
        if self._exiting:
            return
        self._save_settings()
        try:
            tray_available = bool(getattr(self.tray, "supported", False)) and not getattr(
                self.tray, "error", None
            )
            if tray_available:
                self.root.withdraw()
            else:
                # Development fallback: keep a recoverable taskbar entry when the
                # native Windows tray is unavailable.
                self.root.overrideredirect(False)
                self.root.iconify()
                self._fallback_minimized = True
        except tk.TclError:
            return

    def _save_settings(self) -> None:
        try:
            geometry = self.root.geometry() or self._last_geometry
            self._last_geometry = geometry
            self.settings = replace(
                self.settings,
                geometry=geometry,
                compact_mode=self.compact_mode,
                session_index=self.coordinator.session_index,
                auto_refresh=self.coordinator.auto_refresh,
                always_on_top=self.topmost_var.get(),
                opacity=self.opacity_var.get() / 100.0,
            )
            self.settings_store.save(self.settings)
        except Exception:
            pass

    def exit_app(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        self._save_settings()
        self.coordinator.remove_listener(self._receive_snapshot)
        self.coordinator.stop()
        for after_id in tuple(self._after_ids):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
            finally:
                self._after_ids.discard(after_id)
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # Backward-compatible explicit close method. The window close control itself
    # calls hide_widget so accidental clicks do not terminate monitoring.
    close = exit_app
