import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DRAFT = ROOT / "research" / "package-publish-doctor" / "draft"
SKILL = DRAFT / "SKILL.md"


def frontmatter(text):
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md frontmatter missing")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


class PackagePublishDoctorDraftTests(unittest.TestCase):
    def test_draft_has_complete_skill_package_structure(self):
        required = {
            "SKILL.md",
            "CHANGELOG.md",
            ".clawhubignore",
            "references/failure-map.md",
            "templates/package_diagnosis_report.md",
            "examples/three_layer_diagnosis.md",
        }
        present = {
            path.relative_to(DRAFT).as_posix()
            for path in DRAFT.rglob("*")
            if path.is_file()
        }
        self.assertTrue(required.issubset(present), required - present)

    def test_frontmatter_uses_safe_draft_identity(self):
        values = frontmatter(SKILL.read_text(encoding="utf-8"))

        self.assertEqual(values["name"], "ClawHub Package Publish Doctor")
        self.assertEqual(values["slug"], "package-publish-doctor")
        self.assertEqual(values["version"], "0.1.0")
        self.assertLessEqual(len(values["description"]), 200)
        self.assertFalse(values["slug"].startswith("clawhub-"))
        self.assertFalse(values["slug"].endswith("-clawhub"))

    def test_draft_is_not_publishable_from_current_catalog(self):
        catalog = json.loads(
            (ROOT / ".clawhub" / "skill-catalog.json").read_text(
                encoding="utf-8"
            )
        )
        serialized = json.dumps(catalog)

        self.assertNotIn("package-publish-doctor", serialized)
        self.assertFalse((ROOT / "skills" / "package-publish-doctor").exists())

    def test_skill_declares_core_safety_boundaries(self):
        text = SKILL.read_text(encoding="utf-8")
        required_phrases = [
            "Do not publish, install, download, or mutate registry state",
            "Do not bypass Plugin Inspector",
            "Do not widen permissions",
            "Do not expose secrets",
            "Do not recommend an unreleased `main` commit",
            "return `UNKNOWN`",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_bundled_resource_links_resolve(self):
        text = SKILL.read_text(encoding="utf-8")
        references = re.findall(
            r"`((?:references|templates|examples)/[^`]+)`",
            text,
        )

        self.assertTrue(references)
        for relative in references:
            with self.subTest(relative=relative):
                self.assertTrue((DRAFT / relative).is_file())


if __name__ == "__main__":
    unittest.main()
