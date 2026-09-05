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


if __name__ == "__main__":
    unittest.main()
