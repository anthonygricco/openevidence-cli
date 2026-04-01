from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import RuntimeContext


def write_failure_bundle(
    ctx: RuntimeContext,
    reason: str,
    snapshot: dict[str, object] | None = None,
    page: object | None = None,
    extra: dict[str, object] | None = None,
) -> Path:
    ctx.diagnostics_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle_dir = ctx.diagnostics_dir / f"{stamp}-{ctx.runtime_id}-{reason}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "reason": reason,
        "runtime_id": ctx.runtime_id,
        "timestamp": datetime.now().isoformat(),
        "snapshot": snapshot or {},
        "extra": extra or {},
    }
    (bundle_dir / "metadata.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    if page is not None:
        try:
            page.screenshot(path=str(bundle_dir / "page.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
    return bundle_dir
