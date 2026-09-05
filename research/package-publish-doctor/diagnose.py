#!/usr/bin/env python3
"""Compatibility forwarder to the draft Package Doctor implementation."""

import importlib.util
from pathlib import Path

_CANONICAL = Path(__file__).parent / "draft" / "scripts" / "diagnose.py"
_SPEC = importlib.util.spec_from_file_location(
    "package_publish_doctor_canonical",
    _CANONICAL,
)
_IMPL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPL)

FAILURE_LAYERS = _IMPL.FAILURE_LAYERS
EXECUTABLE_RULE_LAYERS = _IMPL.EXECUTABLE_RULE_LAYERS
CLASSIFICATION_ONLY_LAYERS = _IMPL.CLASSIFICATION_ONLY_LAYERS
InputContractError = _IMPL.InputContractError
diagnose = _IMPL.diagnose
main = _IMPL.main

if __name__ == "__main__":
    raise SystemExit(main())
