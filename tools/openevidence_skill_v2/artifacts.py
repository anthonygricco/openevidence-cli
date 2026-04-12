from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .extract import CandidateText


MIN_IMAGE_WIDTH = 48
MIN_IMAGE_HEIGHT = 48
MAX_NEARBY_IMAGE_VERTICAL_GAP = 2400
MAX_NEARBY_IMAGE_HORIZONTAL_GAP = 720


@dataclass(frozen=True)
class ArtifactOptions:
    save_answer_screenshot: bool = False
    save_page_screenshot: bool = False
    save_inline_images: bool = False
    artifact_dir: Path | None = None

    def enabled(self) -> bool:
        return self.save_answer_screenshot or self.save_page_screenshot or self.save_inline_images


def _question_slug(question: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")
    if not slug:
        return "query"
    return slug[:max_length].rstrip("-") or "query"


def _selected_candidate(snapshot: dict[str, object]) -> CandidateText | None:
    selected = snapshot.get("selected_candidate")
    if isinstance(selected, CandidateText):
        return selected
    if isinstance(selected, dict):
        try:
            return CandidateText(
                selector=str(selected.get("selector")),
                index=int(selected.get("index", 0)),
                text=str(selected.get("text", "")),
            )
        except Exception:  # noqa: BLE001
            return None
    return None


def _artifact_bundle_dir(ctx: object, question: str, override_dir: Path | None) -> Path:
    base_dir = override_dir or (Path(getattr(ctx, "data_dir")) / "artifacts_v2")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runtime_id = str(getattr(ctx, "runtime_id", "openevidencev2"))
    bundle_dir = base_dir / f"{stamp}-{runtime_id}-{_question_slug(question)}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    return bundle_dir


def _answer_locator(page: object, snapshot: dict[str, object]) -> object | None:
    selected = _selected_candidate(snapshot)
    if selected is None:
        return None
    return page.locator(selected.selector).nth(selected.index)


def _capture_root_locator(answer_locator: object) -> object:
    for selector in (
        'xpath=ancestor-or-self::*[@data-testid="assistant-message" or @data-testid="ai-message"][1]',
        'xpath=ancestor-or-self::*[self::article or @role="article" or contains(@class, "assistant") or contains(@class, "message")][1]',
        "xpath=ancestor-or-self::*[.//img][1]",
    ):
        try:
            root = answer_locator.locator(selector)
            if root.count() > 0:
                return root.first
        except Exception:  # noqa: BLE001
            continue
    try:
        root = answer_locator.locator("xpath=ancestor-or-self::*[self::section or self::main or self::div][1]")
        if root.count() > 0:
            return root.first
    except Exception:  # noqa: BLE001
        pass
    return answer_locator


def _inline_image_metadata(root_locator: object) -> list[dict[str, object]]:
    payload = root_locator.locator("img").evaluate_all(
        """
        (nodes) => nodes.map((node, index) => {
          const rect = node.getBoundingClientRect();
          const style = window.getComputedStyle(node);
          const visible = rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
          return {
            index,
            src: node.currentSrc || node.getAttribute("src") || "",
            alt: node.getAttribute("alt") || "",
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            visible,
          };
        })
        """
    )
    return [item for item in payload if isinstance(item, dict)]


def _answer_bounding_box(answer_locator: object) -> dict[str, float] | None:
    try:
        box = answer_locator.bounding_box()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(box, dict):
        return None

    width = float(box.get("width") or 0.0)
    height = float(box.get("height") or 0.0)
    if width <= 0 or height <= 0:
        return None

    return {
        "x": float(box.get("x") or 0.0),
        "y": float(box.get("y") or 0.0),
        "width": width,
        "height": height,
    }


def _page_image_candidates(page: object, answer_bbox: dict[str, float] | None) -> list[dict[str, object]]:
    try:
        payload = page.locator("img").evaluate_all(
            """
            (nodes) => nodes.map((node, index) => {
              const rect = node.getBoundingClientRect();
              const style = window.getComputedStyle(node);
              const visible = rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
              return {
                index,
                src: node.currentSrc || node.getAttribute("src") || "",
                alt: node.getAttribute("alt") || "",
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                visible,
              };
            })
            """
        )
    except Exception:  # noqa: BLE001
        return []

    if not isinstance(payload, list):
        return []

    candidates: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("visible")):
            continue
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            continue

        if answer_bbox is not None:
            x = float(item.get("x") or 0.0)
            y = float(item.get("y") or 0.0)
            image_right = x + width
            image_bottom = y + height
            answer_left = answer_bbox["x"]
            answer_right = answer_bbox["x"] + answer_bbox["width"]
            answer_top = answer_bbox["y"]
            answer_bottom = answer_bbox["y"] + answer_bbox["height"]

            if image_bottom < answer_top - 80:
                continue
            horizontal_overlap = max(0.0, min(image_right, answer_right) - max(x, answer_left))
            vertical_overlap = max(0.0, min(image_bottom, answer_bottom) - max(y, answer_top))
            horizontal_gap = 0.0 if horizontal_overlap > 0 else min(abs(x - answer_right), abs(answer_left - image_right))
            vertical_gap = 0.0 if vertical_overlap > 0 else min(abs(y - answer_bottom), abs(answer_top - image_bottom))
            if vertical_gap > MAX_NEARBY_IMAGE_VERTICAL_GAP:
                continue
            if horizontal_gap > MAX_NEARBY_IMAGE_HORIZONTAL_GAP and horizontal_overlap <= 0:
                continue
            overlap_ratio = horizontal_overlap / max(1.0, min(float(width), answer_bbox["width"]))
            score = overlap_ratio * 1000.0 - vertical_gap - (horizontal_gap * 0.35)
            if y >= answer_top:
                score += 120.0
        else:
            score = float(width * height)

        enriched = dict(item)
        enriched["_score"] = score
        candidates.append(enriched)

    candidates.sort(key=lambda item: float(item.get("_score") or 0.0), reverse=True)
    return candidates


def _save_page_image_fallback(
    page: object,
    bundle_dir: Path,
    answer_bbox: dict[str, float] | None,
    existing_images: list[dict[str, object]],
    artifacts: dict[str, object],
) -> list[dict[str, object]]:
    candidates = _page_image_candidates(page, answer_bbox)
    if not candidates:
        return existing_images

    saved_images = list(existing_images)
    seen_sources = {str(item.get("src") or "") for item in saved_images if isinstance(item, dict)}
    page_images = page.locator("img")
    for item in candidates:
        if len(saved_images) >= 4:
            break
        src = str(item.get("src") or "")
        if src and src in seen_sources:
            continue
        image_index = int(item.get("index") or 0)
        image_path = bundle_dir / f"inline-image-{len(saved_images) + 1:02d}.png"
        try:
            page_images.nth(image_index).screenshot(path=str(image_path))
            saved_images.append(
                {
                    "path": str(image_path),
                    "src": src,
                    "alt": str(item.get("alt") or ""),
                    "width": int(item.get("width") or 0),
                    "height": int(item.get("height") or 0),
                    "capture_scope": "page-near-answer",
                }
            )
            if src:
                seen_sources.add(src)
        except Exception as exc:  # noqa: BLE001
            artifacts["errors"].append(f"could not save nearby page image {image_index}: {exc}")
    return saved_images


def generate_gallery_html(
    bundle_dir: Path, inline_images: list[dict], question: str
) -> str | None:
    """Generate a self-contained HTML gallery of inline images."""
    if not inline_images:
        return None

    image_sections: list[str] = []
    for idx, item in enumerate(inline_images, start=1):
        path = Path(str(item.get("path", "")))
        if not path.exists():
            continue
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        src_url = str(item.get("src") or "")
        label = src_url if src_url else f"Figure {idx}"
        image_sections.append(
            f'<div class="figure">'
            f'<img src="data:{mime_type};base64,{encoded}" alt="{label}">'
            f'<p class="caption">{label}</p>'
            f"</div>"
        )

    if not image_sections:
        return None

    from html import escape

    html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "<title>OpenEvidence Figures</title>\n"
        "<style>\n"
        "  body { background: #1a1a2e; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 2rem; }\n"
        "  h1 { color: #e0e0e0; font-size: 1.3rem; font-weight: 500; max-width: 900px; margin: 0 auto 0.5rem; }\n"
        "  .note { color: #888; font-size: 0.85rem; max-width: 900px; margin: 0 auto 2rem; }\n"
        "  .figure { max-width: 900px; margin: 1.5rem auto; text-align: center; }\n"
        "  .figure img { max-width: 100%; height: auto; border-radius: 6px; border: 1px solid #333; }\n"
        "  .caption { color: #aaa; font-size: 0.8rem; margin-top: 0.5rem; word-break: break-all; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{escape(question)}</h1>\n"
        '<p class="note">Images captured from OpenEvidence</p>\n'
        + "\n".join(image_sections)
        + "\n</body>\n</html>\n"
    )

    gallery_path = bundle_dir / "gallery.html"
    gallery_path.write_text(html, encoding="utf-8")
    return str(gallery_path)


def _write_manifest(bundle_dir: Path, artifacts: dict[str, object]) -> str:
    manifest_path = bundle_dir / "artifacts.json"
    manifest_path.write_text(json.dumps(artifacts, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(manifest_path)


def capture_query_artifacts(
    page: object,
    ctx: object,
    question: str,
    snapshot: dict[str, object],
    options: ArtifactOptions,
) -> dict[str, object] | None:
    if not options.enabled():
        return None

    bundle_dir = _artifact_bundle_dir(ctx, question, options.artifact_dir)
    artifacts: dict[str, object] = {
        "dir": str(bundle_dir),
        "answer_screenshot": None,
        "page_screenshot": None,
        "inline_images": [],
        "errors": [],
    }

    answer_locator = None
    capture_root = None
    answer_bbox = None
    if options.save_answer_screenshot or options.save_inline_images:
        try:
            answer_locator = _answer_locator(page, snapshot)
            if answer_locator is not None:
                capture_root = _capture_root_locator(answer_locator)
                answer_bbox = _answer_bounding_box(answer_locator)
        except Exception as exc:  # noqa: BLE001
            artifacts["errors"].append(f"could not resolve answer element: {exc}")

    screenshot_root = capture_root or answer_locator
    if options.save_answer_screenshot and screenshot_root is not None:
        answer_path = bundle_dir / "answer.png"
        try:
            screenshot_root.screenshot(path=str(answer_path))
            artifacts["answer_screenshot"] = str(answer_path)
        except Exception as exc:  # noqa: BLE001
            artifacts["errors"].append(f"could not save answer screenshot: {exc}")

    if options.save_page_screenshot:
        page_path = bundle_dir / "page.png"
        try:
            page.screenshot(path=str(page_path), full_page=True)
            artifacts["page_screenshot"] = str(page_path)
        except Exception as exc:  # noqa: BLE001
            artifacts["errors"].append(f"could not save page screenshot: {exc}")

    image_root = capture_root or answer_locator
    if options.save_inline_images and image_root is not None:
        try:
            images = _inline_image_metadata(image_root)
        except Exception as exc:  # noqa: BLE001
            images = []
            artifacts["errors"].append(f"could not inspect inline images: {exc}")

        saved_images: list[dict[str, object]] = []
        for item in images:
            visible = bool(item.get("visible"))
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if not visible or width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
                continue
            image_index = int(item.get("index") or 0)
            image_path = bundle_dir / f"inline-image-{len(saved_images) + 1:02d}.png"
            try:
                image_root.locator("img").nth(image_index).screenshot(path=str(image_path))
                saved_images.append(
                    {
                        "path": str(image_path),
                        "src": str(item.get("src") or ""),
                        "alt": str(item.get("alt") or ""),
                        "width": width,
                        "height": height,
                        "capture_scope": "answer-root",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                artifacts["errors"].append(f"could not save inline image {image_index}: {exc}")
        if not saved_images and answer_locator is not None:
            saved_images = _save_page_image_fallback(page, bundle_dir, answer_bbox, saved_images, artifacts)
        artifacts["inline_images"] = saved_images

    inline_images = artifacts.get("inline_images") or []
    if inline_images:
        gallery_path = generate_gallery_html(bundle_dir, inline_images, question)
        if gallery_path:
            artifacts["gallery"] = gallery_path

    artifacts["manifest"] = _write_manifest(bundle_dir, artifacts)
    return artifacts
