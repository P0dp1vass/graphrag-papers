"""Mini-eval invariants: equal inputs, no reference leakage, honest metrics."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_graph
import qa

PAPERS = [
    {
        "id": "http://arxiv.org/abs/2611.17788v1",
        "title": "Test paper",
        "abstract": "Evidence shared between both evaluation arms.",
        "score": 0.7,
    }
]
FACTS = ["Method -USES-> Memory (sources: http://arxiv.org/abs/2611.17788v1)"]


class EvalGraphTests(unittest.TestCase):
    def test_prompts_only_differ_by_graph_facts(self):
        plain = qa.build_prompt("Question?", PAPERS, [])
        graph = qa.build_prompt("Question?", PAPERS, FACTS)
        self.assertEqual(graph.replace("\n".join(FACTS), ""), plain)
        self.assertIn(PAPERS[0]["abstract"], plain)
        self.assertIn(PAPERS[0]["id"], plain)

    def test_prepare_cases_retrieves_once_per_question(self):
        context = {"papers": copy.deepcopy(PAPERS), "facts": list(FACTS)}
        with patch.object(
            eval_graph, "prepare_context", return_value=context
        ) as prepare:
            results = eval_graph.prepare_cases(object(), object())
        self.assertEqual(prepare.call_count, len(eval_graph.CASES))
        self.assertEqual(len(results), len(eval_graph.CASES))
        for row in results:
            self.assertEqual(row["answers"], {})
            self.assertNotIn("reference_facts", row["context"])

    def test_citations_are_not_treated_as_entailment(self):
        result = eval_graph.citation_diagnostics(
            "Claim https://arxiv.org/abs/2611.17788v1", PAPERS
        )
        self.assertTrue(result["retrieved_source_cited"])
        self.assertNotIn("correct", result)
        self.assertNotIn("groundedness", result)

    def test_unknown_citation_detected(self):
        result = eval_graph.citation_diagnostics(
            "Claim http://arxiv.org/abs/2611.99999v1", PAPERS
        )
        self.assertFalse(result["retrieved_source_cited"])
        self.assertEqual(result["unretrieved_arxiv_ids"], ["2611.99999v1"])

    def test_versionless_citation_allowed_but_other_version_not_assumed(self):
        self.assertTrue(
            eval_graph.citation_diagnostics("https://arxiv.org/abs/2611.17788", PAPERS)[
                "retrieved_source_cited"
            ]
        )
        self.assertFalse(
            eval_graph.citation_diagnostics(
                "https://arxiv.org/abs/2611.17788v2", PAPERS
            )["retrieved_source_cited"]
        )

    def test_citation_domain_is_not_a_substring_match(self):
        result = eval_graph.citation_diagnostics(
            "https://arxiv.org.example.com/abs/2611.17788v1", PAPERS
        )
        self.assertFalse(result["retrieved_source_cited"])

    def test_empty_summary_does_not_invent_quality_or_metrics(self):
        summary = eval_graph.summarize([])
        self.assertIsNone(summary["retrieval_hit_at_3"])
        self.assertIn("Pending", summary["quality_conclusion"])
        self.assertEqual(summary["modes"]["retrieval_only"]["completed"], 0)

    def test_generation_keeps_usage_and_flags_truncation(self):
        with patch.object(qa.requests, "post") as post:
            post.return_value.json.return_value = {
                "message": {"content": "Partial answer"},
                "done_reason": "length",
                "eval_count": 256,
            }
            result = qa.generate_answer("Test prompt")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["ollama"]["eval_count"], 256)
        self.assertEqual(
            post.call_args.kwargs["json"]["options"], qa.GENERATION_OPTIONS
        )
        post.return_value.raise_for_status.assert_called_once()

    def test_api_ask_still_returns_string(self):
        with (
            patch.object(
                qa, "prepare_context", return_value={"papers": PAPERS, "facts": FACTS}
            ),
            patch.object(qa, "generate_answer", return_value={"answer": "Answer"}),
        ):
            self.assertEqual(qa.ask("Question?", object(), object()), "Answer")

    def test_retrieval_only_ask_excludes_graph_facts(self):
        with (
            patch.object(
                qa, "prepare_context", return_value={"papers": PAPERS, "facts": FACTS}
            ),
            patch.object(
                qa, "generate_answer", return_value={"answer": "Answer"}
            ) as generate,
        ):
            qa.ask("Question?", object(), object(), use_graph=False)
        self.assertNotIn(FACTS[0], generate.call_args.args[0])

    def test_runner_alternates_order_and_never_sends_reference_answers(self):
        report = {
            "results": [
                {
                    "id": f"case-{i}",
                    "question": f"Question {i}?",
                    "expected_source_ids": [PAPERS[0]["id"]],
                    "reference_facts": ["SECRET REFERENCE ANSWER"],
                    "context": {"papers": PAPERS, "facts": FACTS},
                    "retrieval_hit": True,
                    "answers": {},
                }
                for i in range(2)
            ]
        }

        def generated(prompt):
            return {
                "answer": "Answer",
                "truncated": False,
                "wall_seconds": 0.1,
                "ollama": {},
            }

        with (
            patch.object(
                eval_graph, "generate_answer", side_effect=generated
            ) as generate,
            patch.object(eval_graph, "save_report") as save,
            patch("builtins.print"),
        ):
            eval_graph.run_answers(report, Path("unused.json"))
        prompts = [call.args[0] for call in generate.call_args_list]
        self.assertEqual(len(prompts), 4)
        self.assertNotIn(FACTS[0], prompts[0])
        self.assertIn(FACTS[0], prompts[1])
        self.assertIn(FACTS[0], prompts[2])
        self.assertNotIn(FACTS[0], prompts[3])
        for prompt in prompts:
            self.assertIn(PAPERS[0]["abstract"], prompt)
            self.assertNotIn("SECRET REFERENCE ANSWER", prompt)
        self.assertEqual(save.call_count, 4)

    def test_generation_error_is_not_counted_as_an_abstention_or_success(self):
        report = {
            "results": [
                {
                    "id": "failure",
                    "question": "Question?",
                    "expected_source_ids": [],
                    "context": {"papers": PAPERS, "facts": FACTS},
                    "retrieval_hit": None,
                    "answers": {},
                }
            ]
        }
        with (
            patch.object(
                eval_graph, "generate_answer", side_effect=TimeoutError("offline")
            ),
            patch.object(eval_graph, "save_report"),
            patch("builtins.print"),
        ):
            eval_graph.run_answers(report, Path("unused.json"))
        summary = eval_graph.summarize(report["results"])
        for mode in eval_graph.MODES:
            self.assertEqual(summary["modes"][mode]["errors"], 1)
            self.assertEqual(summary["modes"][mode]["completed"], 0)
            self.assertEqual(summary["modes"][mode]["quality_reviews_completed"], 0)

    def test_resume_does_not_regenerate_saved_answers(self):
        report = {
            "results": [
                {
                    "id": "finished",
                    "context": {"papers": PAPERS, "facts": FACTS},
                    "answers": {
                        mode: {"answer": "Already saved"} for mode in eval_graph.MODES
                    },
                }
            ]
        }
        with patch.object(eval_graph, "generate_answer") as generate:
            eval_graph.run_answers(report, Path("unused.json"))
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
