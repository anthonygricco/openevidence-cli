from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tools.openevidence_skill.query import QueryOptions, response_ready_to_return, run_query_with_retries, sanitize_answer_text


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

        with patch("tools.openevidence_skill.query.run_single_query", side_effect=results) as mocked:
            result = run_query_with_retries(SimpleNamespace(), "q", options)

        self.assertIn("Hypofractionated", result["answer"])
        self.assertEqual(mocked.call_count, 2)
