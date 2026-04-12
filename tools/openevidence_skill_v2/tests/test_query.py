from __future__ import annotations

import io
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import tempfile
from pathlib import Path

from tools.openevidence_skill_v2.artifacts import generate_gallery_html
from tools.openevidence_skill_v2.cli import main_ask_question
from tools.openevidence_skill_v2.query import QueryOptions, format_text_result, response_ready_to_return, run_query_with_retries, sanitize_answer_text
from tools.openevidence_skill_v2.render import RenderOptions, format_chatwise_result


class ResponseReadinessTests(TestCase):
    def test_sanitize_answer_text_strips_finished_thinking_prefix(self) -> None:
        answer = "Finished thinking\n\nFinished thinking\n\nActual answer starts here."
        self.assertEqual(sanitize_answer_text(answer), "Actual answer starts here.")

    def test_blocks_short_answer_after_brief_pause(self) -> None:
        answer = "Short answer. Still streaming."
        self.assertFalse(
            response_ready_to_return(
                answer,
                stable_count=4,
                stable_checks=3,
                first_seen_at=100.0,
                last_change_at=103.0,
                now=106.0,
                loading_visible=False,
                min_visible_seconds=3.0,
                min_quiet_seconds=3.0,
            )
        )

    def test_accepts_substantive_answer_with_citation_cues(self) -> None:
        answer = (
            "Concurrent chemoradiation remains standard for unresected stage III NSCLC. "
            "The PACIFIC strategy then adds durvalumab in eligible patients with improved PFS and OS. "
            "NCCN and ASCO guidelines support this approach, and key randomized data are frequently cited as [1] and [2]."
        )
        self.assertTrue(
            response_ready_to_return(
                answer,
                stable_count=4,
                stable_checks=3,
                first_seen_at=100.0,
                last_change_at=103.0,
                now=106.5,
                loading_visible=False,
                min_visible_seconds=3.0,
                min_quiet_seconds=3.0,
            )
        )

    def test_accepts_shorter_answer_after_long_quiet_window(self) -> None:
        answer = "No adjuvant radiation is recommended after a clear-margin R0 resection in this setting."
        self.assertTrue(
            response_ready_to_return(
                answer,
                stable_count=6,
                stable_checks=3,
                first_seen_at=100.0,
                last_change_at=104.0,
                now=109.5,
                loading_visible=False,
                min_visible_seconds=3.0,
                min_quiet_seconds=3.0,
            )
        )


class ReliableModeSelectionTests(TestCase):
    def test_reliable_mode_prefers_more_complete_success(self) -> None:
        results = [
            {"ok": True, "question": "q", "answer": "Brief answer."},
            {
                "ok": True,
                "question": "q",
                "answer": (
                    "Hypofractionated whole-breast radiation is supported by randomized trials and modern guidelines. "
                    "The evidence base includes START and Canadian trials, and current NCCN/ASTRO guidance supports moderate "
                    "hypofractionation for most patients [1][2]."
                ),
            },
        ]
        options = QueryOptions(mode="reliable", output_format="text", show_browser=False, debug=False)

        with patch("tools.openevidence_skill_v2.query.run_single_query", side_effect=results) as mocked:
            result = run_query_with_retries(SimpleNamespace(), "q", options)

        self.assertIn("Hypofractionated", result["answer"])
        self.assertEqual(mocked.call_count, 2)

    def test_text_format_lists_artifacts_when_present(self) -> None:
        rendered = format_text_result(
            {
                "ok": True,
                "answer": "Evidence-backed answer.",
                "artifacts": {
                    "answer_screenshot": "/tmp/answer.png",
                    "page_screenshot": "/tmp/page.png",
                    "inline_images": [{"path": "/tmp/inline-image-01.png"}],
                    "gallery": "/tmp/gallery.html",
                    "manifest": "/tmp/artifacts.json",
                    "errors": [],
                },
            }
        )
        # answer_screenshot should NOT appear in rendered output
        self.assertNotIn("answer_screenshot", rendered)
        # inline images should be listed
        self.assertIn("inline_image_1: /tmp/inline-image-01.png", rendered)
        self.assertIn("artifact_manifest: /tmp/artifacts.json", rendered)
        self.assertIn("IMAGE ARTIFACTS", rendered)
        # Gallery open instruction
        self.assertIn("ACTION REQUIRED", rendered)
        self.assertIn('open "/tmp/gallery.html"', rendered)

    def test_chatwise_format_embeds_small_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "answer.png"
            image_path.write_bytes(b"small-image")
            rendered = format_chatwise_result(
                {
                    "ok": True,
                    "answer": "Evidence-backed answer.",
                    "artifacts": {
                        "answer_screenshot": str(image_path),
                        "page_screenshot": None,
                        "inline_images": [],
                        "manifest": str(Path(temp_dir) / "artifacts.json"),
                        "errors": [],
                    },
                },
                RenderOptions(embed_artifacts=True, max_embed_bytes=1024),
            )
        self.assertIn("## OpenEvidence Response", rendered)
        self.assertIn("data:image/png;base64,", rendered)
        self.assertIn(":::collapsible", rendered)

    def test_chatwise_format_uses_file_uri_when_not_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "answer.png"
            image_path.write_bytes(b"small-image")
            rendered = format_chatwise_result(
                {
                    "ok": True,
                    "answer": "Evidence-backed answer.",
                    "artifacts": {
                        "answer_screenshot": str(image_path),
                        "page_screenshot": None,
                        "inline_images": [],
                        "manifest": str(Path(temp_dir) / "artifacts.json"),
                        "errors": [],
                    },
                },
                RenderOptions(embed_artifacts=False),
            )
        self.assertIn(image_path.resolve().as_uri(), rendered)

    def test_generate_gallery_html_creates_self_contained_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir)
            # Create fake PNGs
            img1 = bundle / "inline-image-01.png"
            img2 = bundle / "inline-image-02.png"
            img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

            inline_images = [
                {"path": str(img1), "src": "https://example.com/fig1.png", "alt": "Figure 1", "width": 600, "height": 400},
                {"path": str(img2), "src": "", "alt": "", "width": 500, "height": 300},
            ]
            result = generate_gallery_html(bundle, inline_images, "What are the NCCN guidelines?")

            self.assertIsNotNone(result)
            gallery_path = Path(result)
            self.assertTrue(gallery_path.exists())

            html_content = gallery_path.read_text(encoding="utf-8")
            self.assertIn("base64,", html_content)
            self.assertIn("What are the NCCN guidelines?", html_content)
            self.assertIn("Images captured from OpenEvidence", html_content)
            self.assertIn("https://example.com/fig1.png", html_content)
            self.assertIn("Figure 2", html_content)  # fallback label for empty src

    def test_generate_gallery_html_returns_none_for_empty_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_gallery_html(Path(temp_dir), [], "Some question")
            self.assertIsNone(result)

    def test_main_ask_question_auto_embeds_artifacts_for_chatwise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "answer.png"
            image_path.write_bytes(b"small-image")
            stdout = io.StringIO()
            with (
                patch("tools.openevidence_skill_v2.cli._ctx", return_value=SimpleNamespace()),
                patch("tools.openevidence_skill_v2.cli.maybe_reexec_into_shared_venv", return_value=None),
                patch(
                    "tools.openevidence_skill_v2.cli.run_query_with_retries",
                    return_value={
                        "ok": True,
                        "question": "q",
                        "answer": "Evidence-backed answer.",
                        "artifacts": {
                            "answer_screenshot": str(image_path),
                            "page_screenshot": None,
                            "inline_images": [],
                            "manifest": str(Path(temp_dir) / "artifacts.json"),
                            "errors": [],
                        },
                    },
                ),
                patch("sys.stdout", stdout),
            ):
                exit_code = main_ask_question(
                    "/tmp/ask_question.py",
                    ["--question", "q", "--format", "chatwise", "--save-answer-screenshot"],
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("data:image/png;base64,", stdout.getvalue())
