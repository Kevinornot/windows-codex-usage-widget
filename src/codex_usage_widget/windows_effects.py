"""Optional Windows glass/acrylic effects for the borderless Tk window.

All helpers are best-effort. Unsupported Windows builds and non-Windows systems
simply keep the regular light Tk theme.
"""

from __future__ import annotations

import ctypes
import os
import re


def _top_level_hwnd(hwnd: int) -> int:
    if os.name != "nt" or not hwnd:
        return int(hwnd or 0)
    try:
        get_ancestor = ctypes.windll.user32.GetAncestor  # type: ignore[attr-defined]
        get_ancestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        get_ancestor.restype = ctypes.c_void_p
        return int(get_ancestor(ctypes.c_void_p(hwnd), 2) or hwnd)  # GA_ROOT
    except (AttributeError, OSError, ValueError):
        return int(hwnd)


def get_window_scale(hwnd: int) -> float:
    """Return the native monitor scale for a Tk child or top-level window."""

    if os.name != "nt" or not hwnd:
        return 1.0
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        getter = user32.GetDpiForWindow
        getter.argtypes = [ctypes.c_void_p]
        getter.restype = ctypes.c_uint
        dpi = int(getter(ctypes.c_void_p(_top_level_hwnd(hwnd))))
        return max(1.0, dpi / 96.0) if dpi else 1.0
    except (AttributeError, OSError, ValueError):
        return 1.0


def get_desktop_scale(hwnd: int) -> float:
    """Prefer the configured high-resolution desktop scale over virtual displays."""

    scale = get_window_scale(hwnd)
    if os.name != "nt":
        return scale
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop\WindowMetrics",
        ) as key:
            applied_dpi, _ = winreg.QueryValueEx(key, "AppliedDPI")
        scale = max(scale, int(applied_dpi) / 96.0)
    except (ImportError, OSError, TypeError, ValueError):
        pass
    return max(1.0, scale)


def enable_high_dpi_awareness() -> bool:
    """Use native per-monitor pixels so Windows never bitmap-scales the UI."""

    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        context = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(context):
            return True

        # A GUI library may already have fixed process awareness. Keep this
        # thread crisp as a safe fallback (and for embedded/test launches).
        thread_setter = user32.SetThreadDpiAwarenessContext
        thread_setter.argtypes = [ctypes.c_void_p]
        thread_setter.restype = ctypes.c_void_p
        return bool(thread_setter(context))
    except (AttributeError, OSError, ValueError):
        return False


def apply_rounded_window_region(
    hwnd: int,
    *,
    width: int,
    height: int,
    radius: int,
) -> bool:
    """Clip all four corners of a borderless native window."""

    if os.name != "nt" or not hwnd or width <= 0 or height <= 0 or radius <= 0:
        return False
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
        create_region = gdi32.CreateRoundRectRgn
        create_region.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        create_region.restype = ctypes.c_void_p
        set_region = user32.SetWindowRgn
        set_region.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        set_region.restype = ctypes.c_int
        region = create_region(0, 0, int(width) + 1, int(height) + 1, radius * 2, radius * 2)
        if not region:
            return False
        if set_region(ctypes.c_void_p(_top_level_hwnd(hwnd)), region, True):
            return True
        gdi32.DeleteObject(region)
    except (AttributeError, OSError, ValueError):
        pass
    return False


def pack_abgr(color: str, *, alpha: int) -> int:
    """Pack ``#RRGGBB`` and alpha as the ABGR DWORD used by Windows acrylic."""

    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ValueError("color must use #RRGGBB notation")
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    alpha = min(255, max(0, int(alpha)))
    return (alpha << 24) | (blue << 16) | (green << 8) | red


def apply_glass_effect(
    hwnd: int,
    *,
    tint: str = "#F4F8FB",
    tint_alpha: int = 218,
) -> bool:
    """Enable acrylic blur and rounded corners on a native Windows window handle."""

    if os.name != "nt" or not hwnd:
        return False

    hwnd = _top_level_hwnd(hwnd)

    class ACCENTPOLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", ctypes.c_int),
            ("AccentFlags", ctypes.c_int),
            ("GradientColor", ctypes.c_uint32),
            ("AnimationId", ctypes.c_int),
        ]

    class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", ctypes.c_int),
            ("Data", ctypes.c_void_p),
            ("SizeOfData", ctypes.c_size_t),
        ]

    applied = False
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        setter = user32.SetWindowCompositionAttribute
        policy = ACCENTPOLICY(
            AccentState=4,  # ACCENT_ENABLE_ACRYLICBLURBEHIND
            AccentFlags=2,
            GradientColor=pack_abgr(tint, alpha=tint_alpha),
            AnimationId=0,
        )
        data = WINDOWCOMPOSITIONATTRIBDATA(
            Attribute=19,  # WCA_ACCENT_POLICY
            Data=ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
            SizeOfData=ctypes.sizeof(policy),
        )
        applied = bool(setter(int(hwnd), ctypes.byref(data)))
    except (AttributeError, OSError, ValueError):
        applied = False

    # Windows 11 can round a borderless window even when acrylic is unavailable.
    try:
        dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(
            int(hwnd),
            33,  # DWMWA_WINDOW_CORNER_PREFERENCE
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
    except (AttributeError, OSError):
        pass

    return applied
