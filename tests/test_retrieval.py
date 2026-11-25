"""Test title-aware retrieval without loading an LLM or accessing Neo4j."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from retrieval import (
    extract_title_terms,
    rank_candidates,
    retrieve_papers,
    title_pattern,
)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def data(self):
        return self.rows


class FakeSession:
    def __init__(self, vector_hits, title_hits=()):
        self.responses = [vector_hits, list(title_hits)]
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult(self.responses.pop(0))


class RetrievalTests(unittest.TestCase):
    def test_extract_method_names(self):
        self.assertEqual(
            extract_title_terms("What does RAG-FGO optimize?"),
            ["rag-fgo"],
        )
        self.assertEqual(
            extract_title_terms("Compare Bioformer-RetroMAE and PubMedBERT."),
            ["bioformer-retromae", "pubmedbert"],
        )
        self.assertEqual(extract_title_terms("What is GraphRAG?"), ["graphrag"])

    def test_case_insensitive_hyphenated_name(self):
        self.assertEqual(extract_title_terms("what does rag-fgo do?"), ["rag-fgo"])

    def test_general_questions_keep_semantic_search(self):
        self.assertEqual(
            extract_title_terms(
                "Which methods improve retrieval-augmented generation (RAG)?"
            ),
            [],
        )

    def test_patterns_match_boundaries_and_separator_variants(self):
        pattern = title_pattern("rag-fgo")
        for title in ("RAG-FGO: Dynamic Optimization", "A study of RAG_FGO", "RAG FGO"):
            self.assertIsNotNone(re.fullmatch(pattern, title))
        for title in ("RAG-FGOther method", "OtherRAG-FGO", "RAG alone"):
            self.assertIsNone(re.fullmatch(pattern, title))

    def test_patterns_do_not_inject_regex_syntax(self):
        self.assertIsNone(re.fullmatch(title_pattern("X+(Y)"), "XXXXY"))

    def test_title_hit_can_recover_paper_outside_vector_top_k(self):
        vector = [{"id": "unrelated", "score": 0.9}]
        exact = [{"id": "method", "score": 0.6, "matched_names": ["rag-fgo"]}]
        result = rank_candidates(vector, exact, 2)
        self.assertEqual([r["id"] for r in result], ["method", "unrelated"])
        self.assertEqual(result[0]["score"], 0.6)

    def test_deduplicate_by_paper_id(self):
        vector = [{"id": "method", "score": 0.7}]
        exact = [{"id": "method", "score": 0.7, "matched_names": ["rag-fgo"]}]
        self.assertEqual(len(rank_candidates(vector, exact, 3)), 1)

    def test_semantic_score_breaks_title_match_ties(self):
        hits = [
            {"id": "second", "score": 0.5, "matched_names": ["method"]},
            {"id": "first", "score": 0.8, "matched_names": ["method"]},
        ]
        self.assertEqual(rank_candidates([], hits, 1)[0]["id"], "first")

    def test_no_named_method_uses_only_vector_query(self):
        hits = [{"id": "paper", "score": 0.7}]
        session = FakeSession(hits)
        self.assertEqual(
            retrieve_papers(session, [0.1], 3, "Which approaches improve retrieval?"),
            hits,
        )
        self.assertEqual(len(session.calls), 1)

    def test_missing_exact_name_falls_back_to_vectors(self):
        session = FakeSession([{"id": "paper", "score": 0.7}])
        result = retrieve_papers(session, [0.1], 3, "What is MissingMethod?")
        self.assertEqual(result[0]["id"], "paper")
        self.assertEqual(len(session.calls), 2)

    def test_name_query_is_parameterized(self):
        session = FakeSession([])
        retrieve_papers(session, [0.1], 3, "What does RAG-FGO optimize?")
        query, params = session.calls[1]
        self.assertNotIn("rag-fgo", query)
        self.assertEqual(params["terms"][0]["name"], "rag-fgo")

    def test_invalid_k(self):
        with self.assertRaises(ValueError):
            retrieve_papers(FakeSession([]), [0.1], 0, "What is GraphRAG?")


if __name__ == "__main__":
    unittest.main()
