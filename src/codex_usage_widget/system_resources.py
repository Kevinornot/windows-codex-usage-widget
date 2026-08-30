"""Best-effort local CPU, memory, GPU, and VRAM monitoring.

The Windows implementation uses only the Python standard library. CPU and memory
come from Win32 APIs; NVIDIA GPUs use ``nvidia-smi`` when available, and other
Windows GPUs fall back to PowerShell performance counters. Linux fallbacks are
included for development and tests.
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .models import SystemResourceSnapshot

MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CpuTimes:
    idle: int
    total: int


@dataclass(frozen=True, slots=True)
class MemorySample:
    used_bytes: int
    total_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class GpuSample:
    name: str | None = None
    utilization_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None


def cpu_percent_from_times(previous: CpuTimes | None, current: CpuTimes | None) -> float | None:
    """Calculate system CPU usage from two cumulative samples."""

    if previous is None or current is None:
        return None
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0 or idle_delta < 0:
        return None
    busy_delta = max(0, total_delta - idle_delta)
    return min(100.0, max(0.0, busy_delta / total_delta * 100.0))


def parse_proc_stat(text: str) -> CpuTimes | None:
    """Parse the aggregate ``cpu`` row from Linux ``/proc/stat``."""

    first = next((line for line in text.splitlines() if line.startswith("cpu ")), None)
    if first is None:
        return None
    parts = first.split()
    try:
        values = [int(value) for value in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return CpuTimes(idle=idle, total=sum(values))


def parse_meminfo(text: str) -> MemorySample | None:
    """Parse Linux ``/proc/meminfo`` using MemAvailable when present."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.strip().split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        values[key] = value * multiplier
    total = values.get("MemTotal")
    available = values.get("MemAvailable", values.get("MemFree"))
    if not total or available is None:
        return None
    used = max(0, total - available)
    percent = min(100.0, max(0.0, used / total * 100.0))
    return MemorySample(used_bytes=used, total_bytes=total, percent=percent)


def parse_nvidia_smi_output(output: str) -> tuple[GpuSample, ...]:
    """Parse ``name, utilization.gpu, memory.used, memory.total`` CSV output."""

    samples: list[GpuSample] = []
    for row in csv.reader(output.splitlines()):
        if len(row) != 4:
            continue
        try:
            name = row[0].strip()
            utilization = float(row[1].strip())
            used_mib = float(row[2].strip())
            total_mib = float(row[3].strip())
        except (TypeError, ValueError):
            continue
        if not name or used_mib < 0 or total_mib <= 0:
            continue
        samples.append(
            GpuSample(
                name=name,
                utilization_percent=min(100.0, max(0.0, utilization)),
                memory_used_bytes=int(used_mib * MIB),
                memory_total_bytes=int(total_mib * MIB),
            )
        )
    return tuple(samples)


def select_gpu_sample(samples: Iterable[GpuSample]) -> GpuSample | None:
    """Choose the most active GPU for the single-card widget display."""

    candidates = tuple(samples)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda sample: (
            sample.utilization_percent if sample.utilization_percent is not None else -1.0,
            sample.memory_used_bytes if sample.memory_used_bytes is not None else -1,
        ),
    )


def _filetime_value(value: object) -> int:
    return (int(getattr(value, "dwHighDateTime")) << 32) | int(
        getattr(value, "dwLowDateTime")
    )


def _read_windows_cpu_times() -> CpuTimes | None:
    if os.name != "nt":
        return None

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    try:
        success = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
    except (AttributeError, OSError):
        return None
    if not success:
        return None
    return CpuTimes(
        idle=_filetime_value(idle),
        total=_filetime_value(kernel) + _filetime_value(user),
    )


def _read_proc_cpu_times() -> CpuTimes | None:
    try:
        return parse_proc_stat(Path("/proc/stat").read_text(encoding="utf-8"))
    except OSError:
        return None


def _read_cpu_times() -> CpuTimes | None:
    return _read_windows_cpu_times() if os.name == "nt" else _read_proc_cpu_times()


class _CpuPercentReader:
    def __init__(self) -> None:
        self._previous = _read_cpu_times()

    def __call__(self) -> float | None:
        current = _read_cpu_times()
        result = cpu_percent_from_times(self._previous, current)
        self._previous = current
        return result


def _read_windows_memory() -> MemorySample | None:
    if os.name != "nt":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint32),
            ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
            ctypes.byref(status)
        )
    except (AttributeError, OSError):
        return None
    if not success or status.ullTotalPhys <= 0:
        return None
    total = int(status.ullTotalPhys)
    used = max(0, total - int(status.ullAvailPhys))
    return MemorySample(
        used_bytes=used,
        total_bytes=total,
        percent=min(100.0, max(0.0, float(status.dwMemoryLoad))),
    )


def _read_proc_memory() -> MemorySample | None:
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
    except OSError:
        return None


def _read_memory() -> MemorySample | None:
    return _read_windows_memory() if os.name == "nt" else _read_proc_memory()


def _nvidia_smi_path() -> str | None:
    located = shutil.which("nvidia-smi")
    if located:
        return located
    if os.name != "nt":
        return None
    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "NVIDIA Corporation"
        / "NVSMI"
        / "nvidia-smi.exe",
    )
    return next((str(path) for path in candidates if path.exists()), None)


def _run_hidden(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(command, **kwargs)  # type: ignore[arg-type]


def _read_nvidia_gpu() -> GpuSample | None:
    executable = _nvidia_smi_path()
    if executable is None:
        return None
    try:
        result = _run_hidden(
            [
                executable,
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            timeout=2.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return select_gpu_sample(parse_nvidia_smi_output(result.stdout))


def _read_windows_gpu_counters() -> GpuSample | None:
    """Read generic Windows GPU counters when NVIDIA tooling is unavailable."""

    if os.name != "nt":
        return None
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return None
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$gpuSamples = (Get-Counter '\GPU Engine(*)\Utilization Percentage').CounterSamples |
    Where-Object { $_.InstanceName -match 'engtype_3D' }
$gpu = ($gpuSamples | Measure-Object -Property CookedValue -Sum).Sum
$memory = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples |
    Measure-Object -Property CookedValue -Sum).Sum
$controllers = Get-CimInstance Win32_VideoController
$total = ($controllers | Where-Object { $_.AdapterRAM -gt 0 } |
    Measure-Object -Property AdapterRAM -Maximum).Maximum
$name = ($controllers | Select-Object -ExpandProperty Name) -join ' + '
[pscustomobject]@{ name=$name; gpu=$gpu; used=$memory; total=$total } |
    ConvertTo-Json -Compress
""".strip()
    try:
        result = _run_hidden(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=4.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        raw = json.loads(result.stdout)
        utilization = float(raw["gpu"]) if raw.get("gpu") is not None else None
        used = int(float(raw["used"])) if raw.get("used") is not None else None
        total = int(float(raw["total"])) if raw.get("total") is not None else None
        name = str(raw.get("name") or "").strip() or None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if utilization is None and used is None and total is None:
        return None
    return GpuSample(
        name=name,
        utilization_percent=(
            None if utilization is None else min(100.0, max(0.0, utilization))
        ),
        memory_used_bytes=used,
        memory_total_bytes=total,
    )


def _read_gpu() -> GpuSample | None:
    return _read_nvidia_gpu() or _read_windows_gpu_counters()


class SystemResourceReader:
    """Stateful sampler suitable for periodic calls from the coordinator thread."""

    def __init__(
        self,
        *,
        cpu_reader: Callable[[], float | None] | None = None,
        memory_reader: Callable[[], MemorySample | None] | None = None,
        gpu_reader: Callable[[], GpuSample | None] | None = None,
        clock: Callable[[], float] = time.time,
        gpu_refresh_seconds: float = 5.0,
    ) -> None:
        self.cpu_reader = cpu_reader or _CpuPercentReader()
        self.memory_reader = memory_reader or _read_memory
        self.gpu_reader = gpu_reader or _read_gpu
        self.clock = clock
        self.gpu_refresh_seconds = max(2.0, float(gpu_refresh_seconds))
        self._last_gpu: GpuSample | None = None
        self._last_gpu_at = float("-inf")

    def _gpu_sample(self, now: float) -> GpuSample | None:
        if now - self._last_gpu_at >= self.gpu_refresh_seconds:
            self._last_gpu = self.gpu_reader()
            self._last_gpu_at = now
        return self._last_gpu

    def read_snapshot(self) -> SystemResourceSnapshot:
        now = self.clock()
        errors: list[str] = []
        try:
            cpu = self.cpu_reader()
        except Exception as exc:  # pragma: no cover - defensive adapter boundary.
            cpu = None
            errors.append(f"CPU：{exc}")
        try:
            memory = self.memory_reader()
        except Exception as exc:  # pragma: no cover - defensive adapter boundary.
            memory = None
            errors.append(f"内存：{exc}")
        try:
            gpu = self._gpu_sample(now)
        except Exception as exc:  # pragma: no cover - defensive adapter boundary.
            gpu = None
            errors.append(f"GPU：{exc}")

        if cpu is None:
            errors.append("CPU 数据暂不可用")
        if memory is None:
            errors.append("内存数据暂不可用")
        if gpu is None:
            errors.append("GPU 数据暂不可用")

        available_count = sum((cpu is not None, memory is not None, gpu is not None))
        status = "ok" if available_count == 3 else ("partial" if available_count else "unavailable")
        return SystemResourceSnapshot(
            cpu_percent=cpu,
            memory_percent=memory.percent if memory else None,
            memory_used_bytes=memory.used_bytes if memory else None,
            memory_total_bytes=memory.total_bytes if memory else None,
            gpu_percent=gpu.utilization_percent if gpu else None,
            vram_used_bytes=gpu.memory_used_bytes if gpu else None,
            vram_total_bytes=gpu.memory_total_bytes if gpu else None,
            gpu_name=gpu.name if gpu else None,
            updated_at=now,
            status=status,
            error="；".join(dict.fromkeys(errors)) or None,
        )

    def __call__(self) -> SystemResourceSnapshot:
        return self.read_snapshot()


# Backward-compatible name used by early development builds.
SystemResourceMonitor = SystemResourceReader
