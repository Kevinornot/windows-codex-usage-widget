"""Native Windows system-tray integration.

The widget intentionally avoids third-party runtime dependencies. On Windows this
module creates a small notification-area icon with Show, Expand/Collapse, and Exit
commands. Other platforms expose a safe no-op object for development and tests.
"""

from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from typing import Callable

Callback = Callable[[], None]
StateReader = Callable[[], bool]


def tray_toggle_label(compact: bool) -> str:
    return "展开详情" if compact else "收起详情"


def _wndproc_parameter_types(wintypes_module: object) -> tuple[object, object, object, object]:
    """Return the native four-argument Win32 window-procedure signature."""

    return (
        getattr(wintypes_module, "HWND"),
        getattr(wintypes_module, "UINT"),
        getattr(wintypes_module, "WPARAM"),
        getattr(wintypes_module, "LPARAM"),
    )


class WindowsTrayIcon:
    """Small Win32 notification-area icon managed on its own message thread."""

    def __init__(
        self,
        *,
        title: str,
        icon_path: Path | None,
        on_show: Callback,
        on_toggle_details: Callback,
        on_exit: Callback,
        is_compact: StateReader,
    ) -> None:
        self.title = title[:127]
        self.icon_path = Path(icon_path) if icon_path is not None else None
        self.on_show = on_show
        self.on_toggle_details = on_toggle_details
        self.on_exit = on_exit
        self.is_compact = is_compact
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._hwnd: int | None = None
        self._error: str | None = None
        self._wndproc_ref: object | None = None
        self._class_name = f"CodexUsageWidgetTray_{os.getpid()}_{id(self):x}"

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        if not self.supported:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            name="codex-widget-tray",
            daemon=True,
        )
        self._thread.start()
        ready = self._ready.wait(timeout=2.0)
        if not ready:
            self._error = "系统托盘初始化超时"
        elif self._hwnd is None and self._error is None:
            self._error = "系统托盘窗口未创建"

    def stop(self) -> None:
        if not self.supported:
            return
        self._stop_requested.set()
        hwnd = self._hwnd
        if hwnd:
            try:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def _safe_call(self, callback: Callback) -> None:
        try:
            callback()
        except Exception:
            # Tray callbacks are convenience controls and must not terminate the
            # native message loop when the Tk window is already shutting down.
            return

    def _run(self) -> None:  # pragma: no cover - exercised on Windows builds.
        if os.name != "nt":
            self._ready.set()
            return

        from ctypes import wintypes

        WM_DESTROY = 0x0002
        WM_CLOSE = 0x0010
        WM_NULL = 0x0000
        WM_USER = 0x0400
        WM_APP = 0x8000
        WM_LBUTTONUP = 0x0202
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205
        WM_CONTEXTMENU = 0x007B
        NIN_SELECT = WM_USER
        CALLBACK_MESSAGE = WM_APP + 41

        NIM_ADD = 0x00000000
        NIM_DELETE = 0x00000002
        NIM_SETVERSION = 0x00000004
        NIF_MESSAGE = 0x00000001
        NIF_ICON = 0x00000002
        NIF_TIP = 0x00000004
        NOTIFYICON_VERSION_4 = 4

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        IDI_APPLICATION = 32512

        MF_STRING = 0x0000
        MF_SEPARATOR = 0x0800
        TPM_RIGHTBUTTON = 0x0002
        TPM_RETURNCMD = 0x0100
        TPM_NONOTIFY = 0x0080

        CMD_SHOW = 1001
        CMD_TOGGLE = 1002
        CMD_EXIT = 1003

        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            *_wndproc_parameter_types(wintypes),
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", POINT),
            ]

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        user32.DefWindowProcW.argtypes = list(_wndproc_parameter_types(wintypes))
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadIconW.restype = wintypes.HICON
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        nid: NOTIFYICONDATAW | None = None

        def remove_icon() -> None:
            if nid is not None:
                try:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                except (AttributeError, OSError):
                    pass

        def show_menu(hwnd: int) -> None:
            menu = user32.CreatePopupMenu()
            if not menu:
                return
            try:
                user32.AppendMenuW(menu, MF_STRING, CMD_SHOW, "显示小组件")
                user32.AppendMenuW(
                    menu,
                    MF_STRING,
                    CMD_TOGGLE,
                    tray_toggle_label(bool(self.is_compact())),
                )
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "退出")
                point = POINT()
                user32.GetCursorPos(ctypes.byref(point))
                user32.SetForegroundWindow(hwnd)
                command = user32.TrackPopupMenu(
                    menu,
                    TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                    point.x,
                    point.y,
                    0,
                    hwnd,
                    None,
                )
                user32.PostMessageW(hwnd, WM_NULL, 0, 0)
                if command == CMD_SHOW:
                    self._safe_call(self.on_show)
                elif command == CMD_TOGGLE:
                    self._safe_call(self.on_toggle_details)
                elif command == CMD_EXIT:
                    self._safe_call(self.on_exit)
            finally:
                user32.DestroyMenu(menu)

        @WNDPROC
        def wndproc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
            if message == CALLBACK_MESSAGE:
                event = int(lparam) & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK, NIN_SELECT):
                    self._safe_call(self.on_show)
                    return 0
                if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    show_menu(hwnd)
                    return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                remove_icon()
                user32.PostQuitMessage(0)
                return 0
            return int(user32.DefWindowProcW(hwnd, message, wparam, lparam))

        self._wndproc_ref = wndproc
        hinstance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = wndproc
        window_class.hInstance = hinstance
        window_class.lpszClassName = self._class_name
        window_class.hIcon = user32.LoadIconW(None, IDI_APPLICATION)

        try:
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise OSError(ctypes.get_last_error(), "RegisterClassW failed")
            hwnd = user32.CreateWindowExW(
                0,
                self._class_name,
                self.title,
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                hinstance,
                None,
            )
            if not hwnd:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
            self._hwnd = int(hwnd)

            icon = None
            if self.icon_path is not None and self.icon_path.exists():
                icon = user32.LoadImageW(
                    None,
                    str(self.icon_path),
                    IMAGE_ICON,
                    0,
                    0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )
            if not icon:
                icon = user32.LoadIconW(None, IDI_APPLICATION)

            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = CALLBACK_MESSAGE
            nid.hIcon = icon
            nid.szTip = self.title
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                raise OSError(ctypes.get_last_error(), "Shell_NotifyIconW failed")
            nid.uVersion = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
            self._ready.set()

            message = MSG()
            while not self._stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self._error = str(exc)
            self._ready.set()
        finally:
            remove_icon()
            if self._hwnd:
                try:
                    user32.DestroyWindow(self._hwnd)
                except (AttributeError, OSError):
                    pass
            self._hwnd = None
            try:
                user32.UnregisterClassW(self._class_name, hinstance)
            except (AttributeError, OSError):
                pass
            self._ready.set()
