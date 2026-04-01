from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import RuntimeContext


SUPPORTED_SCRIPT_NAMES = (
    "auth_manager.py",
    "ask_question.py",
    "parallel_ask.py",
    "browser_launch_smoke_test.py",
)


@dataclass
class LegacyCandidate:
    runtime_id: str
    auth_info_file: Path
    state_file: Path
    profile_dir: Path | None
    last_auth: str
    timestamp: float


def ensure_runtime_directories(ctx: RuntimeContext) -> None:
    for path in (
        ctx.data_dir,
        ctx.state_home,
        ctx.profile_root,
        ctx.diagnostics_dir,
        ctx.legacy_backup_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _legacy_runtime_dirs(ctx: RuntimeContext) -> dict[str, Path]:
    repo_root = ctx.repo_root
    return {
        "codex": Path.home() / ".codex" / "skills" / "openevidence",
        "claude": Path.home() / ".claude" / "skills" / "openevidence",
        "alma": Path.home() / ".config" / "alma" / "skills" / "openevidence",
        "openclaw": Path.home() / ".openclaw" / "skills" / "openevidence",
        "repo-claude": repo_root / "skills" / "claude-code" / "openevidence",
        "repo-alma": repo_root / "skills" / "alma" / "openevidence",
    }


def _candidate_from_dir(runtime_id: str, skill_dir: Path) -> LegacyCandidate | None:
    auth_info_file = skill_dir / "data" / "auth_info.json"
    state_file = skill_dir / "data" / "browser_state" / "state.json"
    profile_dir = skill_dir / "data" / "browser_state" / "browser_profile"
    if not auth_info_file.exists() or not state_file.exists():
        return None
    try:
        info = json.loads(auth_info_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not info.get("authenticated"):
        return None
    last_auth = str(info.get("last_auth") or "")
    timestamp = auth_info_file.stat().st_mtime
    if last_auth:
        try:
            timestamp = datetime.fromisoformat(last_auth).timestamp()
        except ValueError:
            pass
    return LegacyCandidate(
        runtime_id=runtime_id,
        auth_info_file=auth_info_file,
        state_file=state_file,
        profile_dir=profile_dir if profile_dir.exists() else None,
        last_auth=last_auth,
        timestamp=timestamp,
    )


def _copy_tree_contents(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{dst.name}-tmp-", dir=str(dst.parent)))
    temp_target = temp_dir / dst.name
    try:
        shutil.copytree(
            src,
            temp_target,
            ignore=shutil.ignore_patterns("Singleton*", "lockfile", "Crashpad", "BrowserMetrics-*"),
        )
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        os.replace(temp_target, dst)
    finally:
        if temp_target.exists():
            shutil.rmtree(temp_target, ignore_errors=True)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def backup_legacy_candidate(ctx: RuntimeContext, candidate: LegacyCandidate) -> None:
    stamp = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{os.getpid()}"
    backup_dir = ctx.legacy_backup_dir / candidate.runtime_id / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate.auth_info_file, backup_dir / "auth_info.json")
    shutil.copy2(candidate.state_file, backup_dir / "state.json")
    if candidate.profile_dir and candidate.profile_dir.exists():
        _copy_tree_contents(candidate.profile_dir, backup_dir / "browser_profile")


def migrate_legacy_state(ctx: RuntimeContext) -> None:
    ensure_runtime_directories(ctx)
    candidates = []
    for runtime_id, skill_dir in _legacy_runtime_dirs(ctx).items():
        candidate = _candidate_from_dir(runtime_id, skill_dir)
        if candidate:
            candidates.append(candidate)

    if not candidates:
        return

    best = max(candidates, key=lambda item: item.timestamp)
    needs_state = not ctx.state_file.exists()
    needs_auth = not ctx.auth_info_file.exists()
    needs_template = not ctx.shared_profile_template_dir.exists()
    if not any((needs_state, needs_auth, needs_template)):
        return

    backup_legacy_candidate(ctx, best)

    if needs_state:
        shutil.copy2(best.state_file, ctx.state_file)

    if needs_auth:
        raw_info = json.loads(best.auth_info_file.read_text(encoding="utf-8"))
        migrated = {
            "authenticated": bool(raw_info.get("authenticated")),
            "provider": raw_info.get("provider", "apple"),
            "last_auth": raw_info.get("last_auth"),
            "last_validation": None,
            "last_successful_runtime": best.runtime_id,
            "last_failure_reason": None,
            "migrated_from": best.runtime_id,
        }
        ctx.auth_info_file.write_text(json.dumps(migrated, indent=2), encoding="utf-8")

    if needs_template and best.profile_dir and best.profile_dir.exists():
        _copy_tree_contents(best.profile_dir, ctx.shared_profile_template_dir)


def _venv_python(ctx: RuntimeContext) -> Path:
    if sys.platform == "win32":
        return ctx.venv_dir / "Scripts" / "python.exe"
    return ctx.venv_dir / "bin" / "python"


def _venv_pip(ctx: RuntimeContext) -> Path:
    if sys.platform == "win32":
        return ctx.venv_dir / "Scripts" / "pip.exe"
    return ctx.venv_dir / "bin" / "pip"


def ensure_shared_venv(ctx: RuntimeContext) -> Path:
    ensure_runtime_directories(ctx)
    migrate_legacy_state(ctx)

    if not ctx.venv_dir.exists():
        subprocess.run([sys.executable, "-m", "venv", str(ctx.venv_dir)], check=True)

    pip = _venv_pip(ctx)
    python = _venv_python(ctx)
    requirements = ctx.repo_root / "tools" / "openevidence_skill" / "requirements.txt"
    patchright_ok = subprocess.run(
        [str(pip), "show", "patchright"],
        capture_output=True,
        text=True,
    ).returncode == 0
    if not patchright_ok:
        subprocess.run([str(pip), "install", "-r", str(requirements)], check=True)

    sentinel = ctx.data_dir / ".chromium-installed"
    if not sentinel.exists():
        subprocess.run([str(python), "-m", "patchright", "install", "chromium"], check=True)
        sentinel.write_text(datetime.now().isoformat(), encoding="utf-8")
    return python


def _patchright_importable() -> bool:
    try:
        import patchright.sync_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def maybe_reexec_into_shared_venv(ctx: RuntimeContext, script_file: str, argv: list[str]) -> int | None:
    if _patchright_importable():
        return None
    if os.environ.get("OPENEVIDENCE_IN_SHARED_VENV") == "1":
        raise RuntimeError("patchright is unavailable inside the shared OpenEvidence environment")

    python = ensure_shared_venv(ctx)
    env = os.environ.copy()
    env["OPENEVIDENCE_IN_SHARED_VENV"] = "1"
    existing_pythonpath = env.get("PYTHONPATH", "")
    repo_root = str(ctx.repo_root)
    env["PYTHONPATH"] = repo_root if not existing_pythonpath else f"{repo_root}{os.pathsep}{existing_pythonpath}"
    command = [str(python), script_file] + argv
    result = subprocess.run(command, env=env)
    return result.returncode


def run_script_from_wrapper(ctx: RuntimeContext, script_name: str, args: list[str]) -> int:
    if script_name not in SUPPORTED_SCRIPT_NAMES:
        print(f"Script not found: {script_name}")
        print("Available scripts:")
        for name in SUPPORTED_SCRIPT_NAMES:
            print(f"  - {name}")
        return 1

    script_path = ctx.scripts_dir / script_name
    if not script_path.exists():
        print(f"Script not found: {script_path}")
        return 1

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(ctx.repo_root)
        if not env.get("PYTHONPATH")
        else f"{ctx.repo_root}{os.pathsep}{env['PYTHONPATH']}"
    )

    if any(arg in {"-h", "--help"} for arg in args):
        result = subprocess.run([sys.executable, str(script_path)] + args, env=env, cwd=str(ctx.scripts_dir))
        return result.returncode

    python = ensure_shared_venv(ctx)
    env["OPENEVIDENCE_IN_SHARED_VENV"] = "1"
    env["PYTHONPATH"] = (
        str(ctx.repo_root)
        if not env.get("PYTHONPATH")
        else f"{ctx.repo_root}{os.pathsep}{env['PYTHONPATH']}"
    )
    result = subprocess.run([str(python), str(script_path)] + args, env=env, cwd=str(ctx.scripts_dir))
    return result.returncode
