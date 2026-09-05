import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowActionVersionTests(unittest.TestCase):
    def test_checkout_uses_node24_compatible_release(self):
        references = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "uses: actions/checkout@" in line:
                    references.append((path.name, line.strip()))

        self.assertTrue(references)
        self.assertTrue(
            all(line == "- uses: actions/checkout@v7.0.1" for _, line in references),
            references,
        )

    def test_setup_python_uses_node24_compatible_release(self):
        references = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "uses: actions/setup-python@" in line:
                    references.append((path.name, line.strip()))

        self.assertTrue(references)
        self.assertTrue(
            all(line == "- uses: actions/setup-python@v7.0.0" for _, line in references),
            references,
        )

    def test_plugin_publish_grants_reusable_workflow_actions_read(self):
        workflow = (WORKFLOWS / "clawhub-plugin-publish.yml").read_text(
            encoding="utf-8"
        )
        permissions_block = workflow.split("permissions:", 1)[1].split(
            "concurrency:", 1
        )[0]
        self.assertIn("actions: read", permissions_block)

    def test_metrics_ci_compiles_all_python_sources_and_tests(self):
        workflow = (WORKFLOWS / "metrics-tools-ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python -m py_compile scripts/*.py tests/*.py",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
