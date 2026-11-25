"""Offline evidence for review; imports only pure extraction validation code."""

import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from extract_triplets import validate_triplets


def main():
    examples = {
        "non_string_entities_accepted": {
            "entities": [1, 2],
            "relations": [{"head": 1, "relation": "USES", "tail": 2}],
        },
        "unknown_relation_downgraded": {
            "entities": ["A", "B"],
            "relations": [{"head": "A", "relation": "INVENTED", "tail": "B"}],
        },
        "self_relation_accepted": {
            "entities": ["A"],
            "relations": [{"head": "A", "relation": "IMPROVES", "tail": "A"}],
        },
        "null_entities_crash": {"entities": None, "relations": []},
        "non_object_relation_crash": {"entities": ["A"], "relations": [42]},
    }
    validations = {}
    for name, value in examples.items():
        try:
            result = {"output": validate_triplets(value)}
        except Exception as error:
            result = {"error_type": type(error).__name__, "message": str(error)}
        validations[name] = {"input": value, **result}
    laya = json.loads((ROOT / "data/laya_eval_results.json").read_text())
    rows = laya["results"]
    counts = {
        key: sum(
            row["expected"] == expected and row["predicted"] == predicted
            for row in rows
        )
        for key, expected, predicted in (
            ("tp", "A", "A"),
            ("fp", "B", "A"),
            ("fn", "A", "B"),
            ("tn", "B", "B"),
        )
    }
    manifest = json.loads((ROOT / "review/checks/source_manifest.json").read_text())[
        "files"
    ]
    import hashlib

    changed = [
        name
        for name, metadata in manifest.items()
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != metadata["sha256"]
    ]
    report = {
        "scope": "Offline structural examples, saved Laya results, installed core dependency versions.",
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "fastapi",
                "neo4j",
                "requests",
                "sentence-transformers",
                "uvicorn",
            )
        },
        "validation_examples": validations,
        "laya_counts_recomputed": counts,
        "laya_saved_metrics_consistent": all(
            laya["metrics"][key] == value for key, value in counts.items()
        ),
        "source_files_checked": len(manifest),
        "changed_source_files": changed,
        "ruff": "Not installed; no Ruff lint run was performed.",
    }
    with (ROOT / "review/checks/extra_evidence.json").open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
