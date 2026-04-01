from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share"


def _default_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "state"


def _infer_runtime_id(script_path: Path) -> str:
    raw = str(script_path)
    explicit = os.environ.get("OPENEVIDENCE_RUNTIME_ID", "").strip()
    if explicit:
        return explicit
    lowered = raw.lower()
    if "/.codex/" in lowered:
        return "codex"
    if "/.claude/" in lowered:
        return "claude"
    if "/skills/claude-code/" in lowered:
        return "claude"
    if "/.config/alma/" in lowered or "/skills/alma/" in lowered:
        return "alma"
    if "/.openclaw/" in lowered or "/skills/openclaw/" in lowered:
        return "openclaw"
    return "openevidence"


def _find_repo_root(script_path: Path) -> Path:
    resolved = script_path.resolve()
    for parent in [resolved.parent] + list(resolved.parents):
        if (parent / "tools" / "openevidence_skill").is_dir():
            return parent
    raise RuntimeError(f"Could not locate repo root from {script_path}")


@dataclass(frozen=True)
class RuntimeContext:
    runtime_id: str
    repo_root: Path
    skill_dir: Path
    data_dir: Path
    state_home: Path
    profile_root: Path
    local_profile_dir: Path
    shared_profile_template_dir: Path
    diagnostics_dir: Path
    legacy_backup_dir: Path
    state_file: Path
    auth_info_file: Path
    venv_dir: Path
    scripts_dir: Path


def build_runtime_context(script_file: str) -> RuntimeContext:
    script_path = Path(script_file).absolute()
    skill_dir = script_path.parent.parent
    repo_root = _find_repo_root(script_path)
    runtime_id = _infer_runtime_id(script_path)

    data_dir_env = os.environ.get("OPENEVIDENCE_DATA_DIR", "").strip()
    state_home = _default_state_home() / "openevidence-skill"
    profile_root_env = os.environ.get("OPENEVIDENCE_PROFILE_ROOT", "").strip()
    if data_dir_env:
        data_dir = Path(data_dir_env).expanduser()
    else:
        data_dir = _default_data_home() / "openevidence-skill"
    if profile_root_env:
        profile_root = Path(profile_root_env).expanduser()
    else:
        profile_root = state_home / "profiles"

    profile_dir_override = os.environ.get("OPENEVIDENCE_PROFILE_DIR", "").strip()
    if profile_dir_override:
        local_profile_dir = Path(profile_dir_override).expanduser()
    else:
        local_profile_dir = profile_root / runtime_id

    return RuntimeContext(
        runtime_id=runtime_id,
        repo_root=repo_root,
        skill_dir=skill_dir,
        data_dir=data_dir,
        state_home=state_home,
        profile_root=profile_root,
        local_profile_dir=local_profile_dir,
        shared_profile_template_dir=state_home / "profile-template",
        diagnostics_dir=data_dir / "diagnostics",
        legacy_backup_dir=data_dir / "legacy_backups",
        state_file=data_dir / "state.json",
        auth_info_file=data_dir / "auth_info.json",
        venv_dir=data_dir / "venv",
        scripts_dir=skill_dir / "scripts",
    )
