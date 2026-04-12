from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MAX_EMBED_BYTES = 1_000_000


@dataclass(frozen=True)
class RenderOptions:
    embed_artifacts: bool = False
    max_embed_bytes: int = DEFAULT_MAX_EMBED_BYTES


def _path_markdown(path: str, label: str) -> str:
    return f"- {label}: `{path}`"


def _mime_type_for_path(file_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return mime_type or "application/octet-stream"


def _image_markdown(path: str, label: str, options: RenderOptions) -> tuple[str | None, str | None]:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return None, f"- {label}: file missing at `{path}`"

    if options.embed_artifacts:
        try:
            file_size = file_path.stat().st_size
        except OSError:
            file_size = options.max_embed_bytes + 1
        if file_size <= options.max_embed_bytes:
            encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
            mime_type = _mime_type_for_path(file_path)
            return f"![{label}](data:{mime_type};base64,{encoded})", _path_markdown(str(file_path), label)

    return f"![{label}]({file_path.resolve().as_uri()})", _path_markdown(str(file_path), label)


def _artifact_markdown(artifacts: dict[str, object], options: RenderOptions) -> str:
    lines = [':::collapsible{title="Saved artifacts"}']
    answer_screenshot = artifacts.get("answer_screenshot")
    if isinstance(answer_screenshot, str) and answer_screenshot:
        image_md, path_md = _image_markdown(answer_screenshot, "Answer screenshot", options)
        if image_md:
            lines.append(image_md)
        if path_md:
            lines.append(path_md)

    page_screenshot = artifacts.get("page_screenshot")
    if isinstance(page_screenshot, str) and page_screenshot:
        image_md, path_md = _image_markdown(page_screenshot, "Page screenshot", options)
        if image_md:
            lines.append(image_md)
        if path_md:
            lines.append(path_md)

    inline_images = artifacts.get("inline_images") or []
    for index, item in enumerate(inline_images, start=1):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        alt = str(item.get("alt") or "") or f"Inline image {index}"
        image_md, path_md = _image_markdown(path, alt, options)
        if image_md:
            lines.append(image_md)
        if path_md:
            lines.append(path_md)

    manifest = artifacts.get("manifest")
    if isinstance(manifest, str) and manifest:
        lines.append(f"- Artifact manifest: `{manifest}`")

    for error in artifacts.get("errors") or []:
        lines.append(f"- Artifact warning: {error}")

    lines.append(":::")
    return "\n".join(lines)


def format_text_result(result: dict[str, object]) -> str:
    if not result.get("ok"):
        return json.dumps(result, indent=2)
    body = (
        "=" * 60
        + "\nOPENEVIDENCE RESPONSE [PRESENT VERBATIM - DO NOT SUMMARIZE]\n"
        + "=" * 60
        + "\n\n"
        + str(result["answer"])
        + "\n\n"
        + "-" * 60
        + "\nSource: OpenEvidence (https://www.openevidence.com)\n"
        + "-" * 60
    )
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        return body

    # Collect inline image paths (exclude answer_screenshot from display)
    image_paths: list[tuple[str, str]] = []
    inline_images = artifacts.get("inline_images") or []
    for idx, image in enumerate(inline_images, start=1):
        if isinstance(image, dict) and image.get("path"):
            image_paths.append((f"inline_image_{idx}", str(image["path"])))

    lines = [body]

    if image_paths:
        lines.append("")
        lines.append("=" * 60)
        lines.append("IMAGE ARTIFACTS")
        lines.append("=" * 60)
        lines.append("")
        lines.append(
            "The following inline figure files were captured from the OpenEvidence answer."
        )
        lines.append("")
        for label, path in image_paths:
            lines.append(f"{label}: {path}")

    gallery = artifacts.get("gallery")
    if isinstance(gallery, str) and gallery:
        lines.append("")
        lines.append("=" * 60)
        lines.append("ACTION REQUIRED: Open the image gallery for the user")
        lines.append("=" * 60)
        lines.append("Run this command to show the captured figures in the browser:")
        lines.append(f'open "{gallery}"')

    # Keep metadata section for manifest / errors
    meta_lines: list[str] = []
    manifest = artifacts.get("manifest")
    if manifest:
        meta_lines.append(f"artifact_manifest: {manifest}")
    for error in artifacts.get("errors") or []:
        meta_lines.append(f"artifact_warning: {error}")
    if meta_lines:
        lines.append("")
        lines.extend(meta_lines)

    return "\n".join(lines)


def format_chatwise_result(result: dict[str, object], options: RenderOptions) -> str:
    if not result.get("ok"):
        return json.dumps(result, indent=2)

    lines = [
        "## OpenEvidence Response",
        "",
        str(result["answer"]),
        "",
        "_Source: OpenEvidence_",
    ]
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        lines.extend(["", _artifact_markdown(artifacts, options)])
    return "\n".join(lines)
