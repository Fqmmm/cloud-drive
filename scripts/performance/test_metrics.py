"""Known-answer checks for window accounting and repeated-run summaries."""
import unittest

from analyze import aggregate, statistics_for


class MetricsTests(unittest.TestCase):
    def test_late_failure_is_counted_but_late_success_is_not_window_throughput(self):
        rows = [
            dict(phase="warmup", start_epoch="-1", end_epoch="0", latency_ms="1", success="1", payload_bytes="1024"),
            dict(phase="measure", start_epoch="1", end_epoch="2", latency_ms="1", success="1", payload_bytes="1024"),
            dict(phase="measure", start_epoch="119", end_epoch="121", latency_ms="20", success="1", payload_bytes="1024"),
            dict(phase="measure", start_epoch="119", end_epoch="150", latency_ms="30000", success="0", payload_bytes="0", error_category="timeout"),
            dict(phase="measure_drain", start_epoch="120", end_epoch="122", latency_ms="2", success="1", payload_bytes="1024"),
        ]
        result = statistics_for(rows, 0, 120)
        self.assertEqual(result["requests"], 3)
        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["timeouts"], 1)
        self.assertEqual(result["successful_completions_after_window"], 1)
        self.assertAlmostEqual(result["rps"], 1 / 120)
        self.assertAlmostEqual(result["success_rate"], 2 / 3)
        self.assertEqual(result["latency_ms"]["p50"], 20)
        self.assertAlmostEqual(result["latency_ms"]["p95"], 27002)

    def test_repeated_p95_uses_median_and_range_not_mean_or_pooled_label(self):
        rows = [dict(scenario="P1", vus=5, requests=10, failures=0, success_rate=1,
                     rps=1, iterations=dict(rps=1), latency_ms=dict(p95=value, p99=value), bytes_per_second=0,
                     resources={"file-service": dict(cpu_peak=1, memory_peak_bytes=1024)}) for value in [10, 100, 1000]]
        result = aggregate(rows)[0]
        self.assertEqual(result["p95_ms_median"], 100)
        self.assertEqual(result["p95_ms_min"], 10)
        self.assertEqual(result["p95_ms_max"], 1000)
        self.assertEqual(result["total_requests"], 30)


if __name__ == "__main__":
    unittest.main()
