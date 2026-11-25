"""Pure migration tests: no Neo4j connection or graph changes."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from merge_actgcg import build_plan, merge_edge_properties


def sample_snapshot():
    return {
        "nodes": [
            {
                "id": "old",
                "labels": ["Entity"],
                "properties": {"name": "ACTGCG", "embedding": [1.0, 0.0]},
            },
            {
                "id": "canonical",
                "labels": ["Entity"],
                "properties": {"name": "ActGCG", "embedding": [0.0, 1.0]},
            },
        ],
        "edges": [
            {
                "id": "out",
                "head": "old",
                "head_labels": ["Entity"],
                "tail": "method",
                "tail_labels": ["Entity"],
                "kind": "R",
                "properties": {"type": "EXTENDS", "source_ids": ["paper-1"]},
            },
            {
                "id": "in",
                "head": "component",
                "head_labels": ["Entity"],
                "tail": "old",
                "tail_labels": ["Entity"],
                "kind": "R",
                "properties": {"type": "APPLIED_TO", "source_ids": ["paper-2"]},
            },
            {
                "id": "mention",
                "head": "paper",
                "head_labels": ["Paper"],
                "tail": "old",
                "tail_labels": ["Entity"],
                "kind": "MENTIONS",
                "properties": {},
            },
        ],
    }


class MergeActGCGTests(unittest.TestCase):
    def test_direction_sources_embedding_and_input_preserved(self):
        before = sample_snapshot()
        original = copy.deepcopy(before)
        plan = build_plan(before)
        self.assertEqual(plan["properties"]["embedding"], [0.0, 1.0])
        self.assertEqual(plan["properties"]["aliases"], ["ACTGCG"])
        edges = {(e["head"], e["kind"], e["tail"]): e for e in plan["edges"]}
        self.assertEqual(
            edges["canonical", "R", "method"]["properties"]["source_ids"],
            ["paper-1"],
        )
        self.assertIn(("component", "R", "canonical"), edges)
        self.assertIn(("paper", "MENTIONS", "canonical"), edges)
        self.assertEqual(before, original)

    def test_duplicate_edges_union_sources(self):
        before = sample_snapshot()
        duplicate = copy.deepcopy(before["edges"][0])
        duplicate.update(id="duplicate", head="canonical")
        duplicate["properties"]["source_ids"] = ["paper-2", "paper-1"]
        before["edges"].append(duplicate)
        plan = build_plan(before)
        outgoing = next(e for e in plan["edges"] if e["tail"] == "method")
        self.assertEqual(outgoing["properties"]["source_ids"], ["paper-1", "paper-2"])
        self.assertEqual(len(plan["edges"]), 3)

    def test_duplicate_mentions_collapse(self):
        before = sample_snapshot()
        duplicate = copy.deepcopy(before["edges"][2])
        duplicate.update(id="duplicate", tail="canonical")
        before["edges"].append(duplicate)
        self.assertEqual(len(build_plan(before)["edges"]), 3)

    def test_reverse_relationship_is_not_collapsed(self):
        before = sample_snapshot()
        reverse = copy.deepcopy(before["edges"][0])
        reverse.update(id="reverse", head="method", tail="canonical")
        before["edges"].append(reverse)
        self.assertEqual(len(build_plan(before)["edges"]), 4)

    def test_self_relationship_is_not_silently_discarded(self):
        before = sample_snapshot()
        before["edges"][0]["tail"] = "canonical"
        plan = build_plan(before)
        self.assertTrue(
            any(e["head"] == e["tail"] == "canonical" for e in plan["edges"])
        )

    def test_unknown_relationship_aborts(self):
        before = sample_snapshot()
        before["edges"][0]["kind"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            build_plan(before)

    def test_conflicting_metadata_aborts(self):
        with self.assertRaises(ValueError):
            merge_edge_properties({"score": 0.1}, {"score": 0.9})

    def test_invalid_sources_abort(self):
        with self.assertRaises(ValueError):
            merge_edge_properties({}, {"source_ids": "not-a-list"})

    def test_conflicting_node_metadata_aborts(self):
        before = sample_snapshot()
        before["nodes"][0]["properties"]["description"] = "one"
        before["nodes"][1]["properties"]["description"] = "another"
        with self.assertRaises(ValueError):
            build_plan(before)

    def test_already_merged_is_noop(self):
        before = sample_snapshot()
        before["nodes"] = [before["nodes"][1]]
        before["edges"] = []
        self.assertIsNone(build_plan(before))

    def test_missing_canonical_aborts(self):
        before = sample_snapshot()
        before["nodes"] = [before["nodes"][0]]
        with self.assertRaises(ValueError):
            build_plan(before)


if __name__ == "__main__":
    unittest.main()
