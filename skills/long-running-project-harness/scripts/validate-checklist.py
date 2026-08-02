#!/usr/bin/env python3
"""Thin loader for the canonical checklist validator.

The single semantic implementation lives at
references/scripts/validate_checklist.py. This top-level script only
locates it and delegates, keeping stdout/stderr/exit-code parity with the
canonical CLI. Do not add a second validation implementation here.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_canonical():
    canonical_path = (
        Path(__file__).resolve().parents[1] / "references" / "scripts" / "validate_checklist.py"
    )
    if not canonical_path.is_file():
        print(f"ERROR: canonical validator not found: {canonical_path}", file=sys.stderr)
        raise SystemExit(2)
    spec = importlib.util.spec_from_file_location(
        "validate_checklist_canonical", canonical_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    canonical = _load_canonical()
    return canonical.main()


if __name__ == "__main__":
    raise SystemExit(main())
