#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in [Path(__file__).resolve().parent] + list(Path(__file__).resolve().parents):
        if (parent / "tools" / "openevidence_skill").is_dir():
            return parent
    raise RuntimeError(f"Could not locate repo root from {__file__}")


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.openevidence_skill.cli import main_auth_manager


if __name__ == "__main__":
    sys.exit(main_auth_manager(__file__, sys.argv[1:]))
