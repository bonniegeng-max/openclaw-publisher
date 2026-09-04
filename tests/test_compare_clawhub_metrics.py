import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "compare_clawhub_metrics.py"
SPEC = importlib.util.spec_from_file_location("compare_clawhub_metrics", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def snapshot(
    skills,
    collected_at="2026-09-05T00:00:00+00:00",
    active_install=False,
    method="clawhub inspect --json",
):
    return {
        "schemaVersion": 1,
        "collectedAt": collected_at,
        "method": method,
        "activeInstall": active_install,
        "skills": skills,
    }


def skill(
    slug,
    downloads=0,
    installs=0,
    stars=0,
    versions=1,
    latest="1.0.0",
    moderation="clean",
    display_name=None,
):
    return {
        "slug": slug,
        "displayName": display_name or slug,
        "latestVersion": latest,
        "moderation": moderation,
        "stats": {
            "downloads": downloads,
            "installs": installs,
            "stars": stars,
            "versions": versions,
        },
    }


class CompareClawHubMetricsTests(unittest.TestCase):
    def test_load_snapshot_rejects_unsupported_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(
                json.dumps({"schemaVersion": 2, "skills": []}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "不支持的 schemaVersion"):
                MODULE.load_snapshot(path)

    def test_index_skills_rejects_duplicate_slug(self):
        payload = snapshot([skill("same"), skill("same")])

        with self.assertRaisesRegex(ValueError, "Skill slug 重复"):
            MODULE.index_skills(payload, "fixture")

    def test_counter_growth_is_observed_not_attributed(self):
        previous = snapshot([skill("alpha", downloads=10)])
        current = snapshot(
            [skill("alpha", downloads=13)],
            collected_at="2026-09-12T00:00:00+00:00",
        )

        result = MODULE.compare_snapshots(previous, current)
        item = result["skills"][0]

        self.assertEqual(item["status"], "observe")
        self.assertEqual(item["metrics"]["downloads"]["delta"], 3)
        self.assertEqual(item["observedSignals"], ["downloads +3"])
        self.assertEqual(item["alerts"], [])
        self.assertIn("不能证明自然采用", result["attribution"])

    def test_version_change_requires_verification(self):
        previous = snapshot([skill("alpha", latest="1.0.0", versions=1)])
        current = snapshot([skill("alpha", latest="1.1.0", versions=2)])

        result = MODULE.compare_snapshots(previous, current)
        item = result["skills"][0]

        self.assertEqual(item["status"], "verify")
        self.assertTrue(
            any("E4 验收" in alert for alert in item["alerts"])
        )

    def test_non_clean_moderation_requires_verification(self):
        previous = snapshot([skill("alpha")])
        current = snapshot([skill("alpha", moderation="pending")])

        result = MODULE.compare_snapshots(previous, current)
        item = result["skills"][0]

        self.assertEqual(item["status"], "verify")
        self.assertTrue(any("moderation" in alert for alert in item["alerts"]))

    def test_counter_decrease_is_flagged_as_registry_correction(self):
        previous = snapshot([skill("alpha", downloads=10)])
        current = snapshot([skill("alpha", downloads=8)])

        result = MODULE.compare_snapshots(previous, current)
        item = result["skills"][0]

        self.assertEqual(item["status"], "verify")
        self.assertEqual(item["regressions"], ["downloads -2"])
        self.assertTrue(any("计数下降" in alert for alert in item["alerts"]))

    def test_added_and_removed_skills_require_verification(self):
        previous = snapshot([skill("removed")])
        current = snapshot([skill("added")])

        result = MODULE.compare_snapshots(previous, current)

        self.assertEqual(result["summary"]["verify"], 2)
        self.assertEqual(
            {item["slug"] for item in result["skills"]},
            {"added", "removed"},
        )

    def test_seven_day_clean_window_is_eligible(self):
        result = MODULE.compare_snapshots(
            snapshot([skill("alpha")]),
            snapshot(
                [skill("alpha")],
                collected_at="2026-09-12T00:00:00+00:00",
            ),
        )

        evidence = result["evidenceQuality"]
        self.assertEqual(evidence["status"], "eligible")
        self.assertTrue(evidence["decisionReady"])
        self.assertEqual(evidence["elapsedDays"], 7)

    def test_short_window_is_premature(self):
        result = MODULE.compare_snapshots(
            snapshot([skill("alpha")]),
            snapshot(
                [skill("alpha")],
                collected_at="2026-09-11T23:59:59+00:00",
            ),
        )

        evidence = result["evidenceQuality"]
        self.assertEqual(evidence["status"], "premature")
        self.assertFalse(evidence["decisionReady"])

    def test_active_install_marks_evidence_contaminated(self):
        result = MODULE.compare_snapshots(
            snapshot([skill("alpha")], active_install=True),
            snapshot(
                [skill("alpha")],
                collected_at="2026-09-12T00:00:00+00:00",
            ),
        )

        evidence = result["evidenceQuality"]
        self.assertEqual(evidence["status"], "contaminated")
        self.assertFalse(evidence["decisionReady"])

    def test_different_collection_methods_are_incomparable(self):
        result = MODULE.compare_snapshots(
            snapshot([skill("alpha")]),
            snapshot(
                [skill("alpha")],
                collected_at="2026-09-12T00:00:00+00:00",
                method="manual import",
            ),
        )

        evidence = result["evidenceQuality"]
        self.assertEqual(evidence["status"], "incomparable")
        self.assertFalse(evidence["decisionReady"])

    def test_reversed_timestamps_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "当前快照时间早于前次快照"):
            MODULE.compare_snapshots(
                snapshot(
                    [skill("alpha")],
                    collected_at="2026-09-12T00:00:00+00:00",
                ),
                snapshot([skill("alpha")]),
            )

    def test_unchanged_skill_is_classified(self):
        same_skill = skill("alpha", downloads=3)

        result = MODULE.compare_snapshots(
            snapshot([same_skill]),
            snapshot([same_skill], collected_at="2026-09-12T00:00:00+00:00"),
        )

        self.assertEqual(result["summary"]["unchanged"], 1)
        self.assertEqual(result["skills"][0]["status"], "unchanged")

    def test_markdown_contains_summary_and_alert(self):
        previous = snapshot([skill("alpha", latest="1.0.0")])
        current = snapshot(
            [skill("alpha", latest="1.1.0")],
            collected_at="2026-09-12T00:00:00+00:00",
        )

        report = MODULE.render_markdown(
            MODULE.compare_snapshots(previous, current)
        )

        self.assertIn("# ClawHub 指标变化", report)
        self.assertIn("1 个需验证", report)
        self.assertIn("1.0.0 → 1.1.0", report)
        self.assertIn("证据质量：`eligible`", report)
        self.assertIn("## 需处理", report)


if __name__ == "__main__":
    unittest.main()
