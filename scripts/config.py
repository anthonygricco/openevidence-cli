from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in [Path(__file__).resolve().parent] + list(Path(__file__).resolve().parents):
        if (parent / "tools" / "openevidence_skill_v2").is_dir():
            return parent
    raise RuntimeError(f"Could not locate repo root from {__file__}")


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.openevidence_skill_v2.config import build_runtime_context


_CTX = build_runtime_context(__file__)

RUNTIME_ID = _CTX.runtime_id
SKILL_DIR = _CTX.skill_dir
DATA_DIR = _CTX.data_dir
STATE_HOME = _CTX.state_home
PROFILE_ROOT = _CTX.profile_root
BROWSER_PROFILE_DIR = _CTX.local_profile_dir
SHARED_PROFILE_TEMPLATE_DIR = _CTX.shared_profile_template_dir
DIAGNOSTICS_DIR = _CTX.diagnostics_dir
LEGACY_BACKUP_DIR = _CTX.legacy_backup_dir
STATE_FILE = _CTX.state_file
STATE_JSON = STATE_FILE
AUTH_INFO_FILE = _CTX.auth_info_file
AUTH_INFO_JSON = AUTH_INFO_FILE
VENV_DIR = _CTX.venv_dir
