from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .bootstrap import ensure_shared_venv
from .browser import sync_profile_from_template
from .config import RuntimeContext


@dataclass(frozen=True)
class ParallelTask:
    index: int
    question: str
    extra_flags: list[str]
    ctx: RuntimeContext


def _run_worker(task: ParallelTask) -> dict[str, object]:
    python = ensure_shared_venv(task.ctx)
    temp_root = task.ctx.state_home / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_profile = Path(tempfile.mkdtemp(prefix=f"{task.ctx.runtime_id}-worker-", dir=temp_root))
    sync_profile_from_template(task.ctx, temp_profile)

    ask_script = task.ctx.scripts_dir / "ask_question.py"
    env = os.environ.copy()
    env["OPENEVIDENCE_IN_SHARED_VENV"] = "1"
    env["PYTHONPATH"] = (
        str(task.ctx.repo_root)
        if not env.get("PYTHONPATH")
        else f"{task.ctx.repo_root}{os.pathsep}{env['PYTHONPATH']}"
    )
    env["OPENEVIDENCE_PROFILE_DIR"] = str(temp_profile)

    command = [str(python), str(ask_script), "--question", task.question, "--format", "json"] + task.extra_flags
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=300)
        if result.returncode != 0:
            return {
                "_index": task.index,
                "ok": False,
                "question": task.question,
                "error": (result.stdout + "\n" + result.stderr).strip(),
            }
        payload = json.loads(result.stdout)
        payload["_index"] = task.index
        return payload
    except Exception as exc:  # noqa: BLE001
        return {
            "_index": task.index,
            "ok": False,
            "question": task.question,
            "error": str(exc),
        }
    finally:
        shutil.rmtree(temp_profile, ignore_errors=True)


def run_parallel_queries(
    ctx: RuntimeContext,
    questions: list[str],
    *,
    max_parallel: int,
    extra_flags: list[str],
) -> list[dict[str, object]]:
    tasks = [ParallelTask(index=i, question=question, extra_flags=extra_flags, ctx=ctx) for i, question in enumerate(questions)]
    results: list[dict[str, object]] = [None] * len(tasks)  # type: ignore[list-item]
    with ProcessPoolExecutor(max_workers=min(max_parallel, len(tasks))) as executor:
        future_map = {executor.submit(_run_worker, task): task.index for task in tasks}
        for future in as_completed(future_map):
            result = future.result()
            index = int(result.pop("_index"))
            results[index] = result
    return results
