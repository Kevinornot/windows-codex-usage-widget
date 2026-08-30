from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_usage_widget.system_resources import (  # noqa: E402
    CpuTimes,
    GpuSample,
    MemorySample,
    SystemResourceReader,
    cpu_percent_from_times,
    parse_meminfo,
    parse_nvidia_smi_output,
    parse_proc_stat,
    select_gpu_sample,
)


class CpuParsingTests(unittest.TestCase):
    def test_parses_proc_stat_and_calculates_usage(self) -> None:
        previous = parse_proc_stat("cpu  100 20 30 400 10 0 0 0 0 0\n")
        current = parse_proc_stat("cpu  150 30 40 450 10 0 0 0 0 0\n")

        self.assertEqual(previous, CpuTimes(idle=410, total=560))
        self.assertEqual(current, CpuTimes(idle=460, total=680))
        self.assertAlmostEqual(cpu_percent_from_times(previous, current), 58.333333, places=5)

    def test_first_cpu_sample_is_unavailable(self) -> None:
        current = CpuTimes(idle=40, total=100)
        self.assertIsNone(cpu_percent_from_times(None, current))


class MemoryParsingTests(unittest.TestCase):
    def test_parses_linux_meminfo_using_available_memory(self) -> None:
        sample = parse_meminfo(
            "MemTotal:       16384000 kB\n"
            "MemFree:         1000000 kB\n"
            "MemAvailable:    4096000 kB\n"
        )

        self.assertEqual(
            sample,
            MemorySample(
                used_bytes=(16_384_000 - 4_096_000) * 1024,
                total_bytes=16_384_000 * 1024,
                percent=75.0,
            ),
        )


class NvidiaParsingTests(unittest.TestCase):
    def test_parses_multiple_gpus_and_selects_most_active(self) -> None:
        samples = parse_nvidia_smi_output(
            "NVIDIA RTX 4060, 17, 3891, 8192\n"
            "NVIDIA RTX 4090, 63, 8120, 24564\n"
        )

        self.assertEqual(len(samples), 2)
        selected = select_gpu_sample(samples)
        self.assertEqual(selected.name, "NVIDIA RTX 4090")
        self.assertEqual(selected.utilization_percent, 63.0)
        self.assertEqual(selected.memory_used_bytes, 8120 * 1024 * 1024)
        self.assertEqual(selected.memory_total_bytes, 24564 * 1024 * 1024)

    def test_parser_ignores_malformed_lines(self) -> None:
        samples = parse_nvidia_smi_output("not supported\nGPU, xx, 1, 2\n")
        self.assertEqual(samples, ())


class ResourceReaderTests(unittest.TestCase):
    def test_reader_combines_cpu_memory_and_gpu(self) -> None:
        reader = SystemResourceReader(
            cpu_reader=lambda: 23.4,
            memory_reader=lambda: MemorySample(
                used_bytes=9 * 1024**3,
                total_bytes=16 * 1024**3,
                percent=61.0,
            ),
            gpu_reader=lambda: GpuSample(
                name="RTX Test",
                utilization_percent=17.0,
                memory_used_bytes=3800 * 1024**2,
                memory_total_bytes=8000 * 1024**2,
            ),
            clock=lambda: 123.0,
        )

        snapshot = reader.read_snapshot()

        self.assertEqual(snapshot.cpu_percent, 23.4)
        self.assertEqual(snapshot.memory_percent, 61.0)
        self.assertEqual(snapshot.gpu_percent, 17.0)
        self.assertEqual(snapshot.gpu_name, "RTX Test")
        self.assertEqual(snapshot.updated_at, 123.0)
        self.assertEqual(snapshot.status, "ok")

    def test_reader_is_partial_when_gpu_is_unavailable(self) -> None:
        reader = SystemResourceReader(
            cpu_reader=lambda: 10.0,
            memory_reader=lambda: MemorySample(used_bytes=2, total_bytes=10, percent=20.0),
            gpu_reader=lambda: None,
            clock=lambda: 123.0,
        )

        snapshot = reader.read_snapshot()

        self.assertEqual(snapshot.status, "partial")
        self.assertIsNone(snapshot.gpu_percent)
        self.assertIn("GPU", snapshot.error)


if __name__ == "__main__":
    unittest.main()
