import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "skills"


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def frontmatter_version(relative):
    text = read(relative)
    match = re.search(r"^version:\s*(\S+)$", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"version missing in {relative}")
    return match.group(1)


class SkillContentContractTests(unittest.TestCase):
    def test_skills_readme_matches_repository_publish_contract(self):
        readme = read("skills/README.md")
        for phrase in (
            "`SKILL.md`",
            "`CHANGELOG.md`",
            "`.clawhubignore`",
            "`.clawhub/skill-catalog.json`",
            "--slug",
            "--name",
            "`E4`",
            "只有达到 `E4` 才能声明“已上线、可下载使用”",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)

    def test_all_published_skill_directories_satisfy_required_files_and_catalog(self):
        catalog = json.loads(
            read(".clawhub/skill-catalog.json")
        )
        skill_dirs = {
            path.parent.relative_to(ROOT).as_posix()
            for path in SKILLS.glob("*/SKILL.md")
        }

        self.assertEqual(set(catalog), skill_dirs)
        for relative in sorted(skill_dirs):
            skill_dir = ROOT / relative
            with self.subTest(skill=relative):
                self.assertTrue((skill_dir / "SKILL.md").is_file())
                self.assertTrue((skill_dir / "CHANGELOG.md").is_file())
                self.assertTrue((skill_dir / ".clawhubignore").is_file())

    def test_target_versions_and_readme_are_in_sync(self):
        expected = {
            "skill-portfolio-growth-audit": "1.0.2",
            "skill-publish-readiness": "1.0.9",
            "skill-launch-checklist": "1.0.3",
            "release-proof-builder": "1.0.3",
        }
        readme = read("README.md")
        for slug, version in expected.items():
            with self.subTest(slug=slug):
                self.assertEqual(
                    frontmatter_version(f"skills/{slug}/SKILL.md"),
                    version,
                )
                self.assertIn(f"## {version}", read(f"skills/{slug}/CHANGELOG.md"))
                self.assertIn(version, readme)

    def test_portfolio_decision_gate_and_template_cover_all_inputs(self):
        skill = read("skills/skill-portfolio-growth-audit/SKILL.md")
        template = read(
            "skills/skill-portfolio-growth-audit/templates/"
            "portfolio_growth_report.md"
        )
        required = [
            "evidenceQuality.decisionReady",
            "采集方法",
            "activeInstall: false",
            "至少 7 天",
            "query 文本",
            "`limit`",
            "query set",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
                self.assertIn(phrase, template)
        self.assertIn("继续观察", template)
        self.assertIn("修复数据质量", template)

    def test_skill_publish_commands_use_explicit_slug_and_name(self):
        for slug in ("skill-publish-readiness", "skill-launch-checklist"):
            for path in sorted((SKILLS / slug).rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                for match in re.finditer(r"clawhub skill publish", text):
                    end = text.find("\n\n", match.start())
                    window = text[match.start() : end if end != -1 else len(text)]
                    with self.subTest(path=path.relative_to(ROOT)):
                        self.assertIn("--slug", window)
                        self.assertIn("--name", window)

    def test_readiness_has_plugin_package_output_branch(self):
        skill = read("skills/skill-publish-readiness/SKILL.md")
        template = read(
            "skills/skill-publish-readiness/templates/publish_review_report.md"
        )
        self.assertIn("Plugin 输出独立的", skill)
        self.assertIn("### Plugin 分支", template)
        self.assertIn("clawhub package validate <path>", template)
        self.assertIn("clawhub package publish <path> --dry-run", template)

    def test_release_proof_levels_require_success_clean_and_pollution_log(self):
        evidence = read(
            "skills/release-proof-builder/references/evidence_levels.md"
        )
        template = read(
            "skills/release-proof-builder/templates/release_proof_report.md"
        )
        self.assertIn("对应 workflow 已完成且结论为成功", evidence)
        self.assertIn("`moderation.verdict` 明确为 `clean`", evidence)
        for phrase in ("安装时间", "slug", "版本", "验收原因", "主动安装污染"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, evidence + template)


if __name__ == "__main__":
    unittest.main()
