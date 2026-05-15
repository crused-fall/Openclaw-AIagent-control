import unittest

from openclaw_v2.usage_stats import compare_openclaw_usage, summarize_openclaw_usage


class UsageStatsTests(unittest.TestCase):
    def test_summarize_openclaw_usage_accumulates_summary_json_results(self) -> None:
        summary = {
            "results": [
                {
                    "artifacts": {
                        "openclaw_usage": {
                            "input": 120,
                            "output": 40,
                            "cacheRead": 800,
                            "cacheWrite": 0,
                            "total": 160,
                        },
                        "openclaw_last_call_usage": {
                            "input": 12,
                            "output": 4,
                            "cacheRead": 80,
                            "total": 16,
                        },
                    },
                },
                {
                    "artifacts": {
                        "openclaw_usage": {
                            "input": 80,
                            "output": 30,
                            "cacheRead": 200,
                            "cacheWrite": 10,
                            "total": 110,
                        },
                        "openclaw_last_call_usage": {
                            "input": 8,
                            "output": 3,
                            "cacheRead": 20,
                            "cacheWrite": 1,
                            "total": 11,
                        },
                    },
                },
                "ignore-me",
            ],
        }

        usage = summarize_openclaw_usage(summary)

        self.assertEqual(usage["resultCount"], 2)
        self.assertEqual(usage["openclawUsageCount"], 2)
        self.assertEqual(usage["openclawLastCallUsageCount"], 2)
        self.assertEqual(
            usage["openclawUsage"],
            {
                "input": 200,
                "output": 70,
                "cacheRead": 1000,
                "cacheWrite": 10,
                "total": 270,
            },
        )
        self.assertEqual(
            usage["openclawLastCallUsage"],
            {
                "input": 20,
                "output": 7,
                "cacheRead": 100,
                "cacheWrite": 1,
                "total": 27,
            },
        )

    def test_summarize_openclaw_usage_tolerates_missing_and_malformed_fields(self) -> None:
        summary = {
            "results": [
                {"artifacts": {"openclaw_usage": {"input": "bad", "total": 20}}},
                {"artifacts": {"openclaw_usage": None, "openclaw_last_call_usage": {"cacheRead": 5}}},
                {"artifacts": []},
            ]
        }

        usage = summarize_openclaw_usage(summary)

        self.assertEqual(usage["resultCount"], 3)
        self.assertEqual(usage["openclawUsageCount"], 1)
        self.assertEqual(usage["openclawLastCallUsageCount"], 1)
        self.assertEqual(
            usage["openclawUsage"],
            {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "total": 20,
            },
        )
        self.assertEqual(
            usage["openclawLastCallUsage"],
            {
                "input": 0,
                "output": 0,
                "cacheRead": 5,
                "cacheWrite": 0,
                "total": 5,
            },
        )

    def test_compare_openclaw_usage_calculates_deltas(self) -> None:
        left = {
            "resultCount": 2,
            "openclawUsageCount": 1,
            "openclawLastCallUsageCount": 1,
            "openclawUsage": {"input": 10, "output": 4, "cacheRead": 8, "cacheWrite": 1, "total": 14},
            "openclawLastCallUsage": {"input": 3, "output": 1, "cacheRead": 2, "cacheWrite": 0, "total": 4},
        }
        right = {
            "resultCount": 4,
            "openclawUsageCount": 3,
            "openclawLastCallUsageCount": 2,
            "openclawUsage": {"input": 30, "output": 12, "cacheRead": 18, "cacheWrite": 5, "total": 42},
            "openclawLastCallUsage": {"input": 6, "output": 2, "cacheRead": 4, "cacheWrite": 1, "total": 8},
        }

        comparison = compare_openclaw_usage(left, right)

        self.assertEqual(comparison["resultCountDelta"], 2)
        self.assertEqual(comparison["openclawUsageCountDelta"], 2)
        self.assertEqual(comparison["openclawLastCallUsageCountDelta"], 1)
        self.assertEqual(comparison["openclawUsageTotalDelta"], 28)
        self.assertEqual(comparison["openclawLastCallUsageTotalDelta"], 4)
        self.assertEqual(comparison["left"], left)
        self.assertEqual(comparison["right"], right)


if __name__ == "__main__":
    unittest.main()
