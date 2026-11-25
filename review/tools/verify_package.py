"""Cross-check documents, cards, exports, saved evidence and source integrity.

Uses only the standard library, except the project's existing unittest suite.
Writes review/checks/final_verification.json; never runs ingestion or generation.
"""

import ast
from collections import Counter
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "review/checks/final_verification.json"
EVAL_NAME = "graph_eval_20261125_152620_112169"


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_html(value):
    return html.escape(value, quote=True).replace("\n", "<br>")


def verify():
    cleanup_report = ROOT / "review/checks/code_cleanup/processing_report.json"
    cleanup = json.loads(cleanup_report.read_text(encoding="utf-8"))
    assert cleanup["all_python_asts_equal"]
    assert cleanup["runtime_string_values_equal"]
    # Final published state: the author hand-edited scripts/*.py after the
    # skill pass (docstrings/comments removed, formatting adjusted); src/,
    # tests/ and most review tools still match the processing report.
    baseline_file = "review/checks/final_state.json"
    final_state = read_json(baseline_file)
    baseline = final_state["files"]
    changed = [
        name
        for name, value in baseline.items()
        if digest(ROOT / name) != value["sha256"]
    ]
    assert not changed, changed
    for name in final_state["unchanged_since_processing"]:
        if name in cleanup["files"]:
            expected_hash = cleanup["files"][name]["after_sha256"]
        else:
            expected_hash = cleanup["original_scope_after"][name]["sha256"]
        assert digest(ROOT / name) == expected_hash, name
    assert final_state["unit_tests"] == 36
    baseline_python = [name for name in baseline if name.endswith(".py")]
    syntax_paths = sorted(
        {ROOT / name for name in baseline_python}
        | set((ROOT / "review/tools").glob("*.py"))
    )
    for path in syntax_paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    data = read_json("review/anki/cards.json")
    cards = data["cards"]
    for field in ("id", "q"):
        normalized = [row[field].strip().casefold() for row in cards]
        assert len(set(normalized)) == len(cards), f"duplicate {field}"
    assert len(cards) == 154
    core = sum("priority::core" in row["tags"] for row in cards)
    assert core == 83
    for row in cards:
        assert all(
            isinstance(row[key], str) and row[key].strip()
            for key in ("id", "q", "a", "source")
        )
        assert all(not any(char.isspace() for char in tag) for tag in row["tags"])
        for part in row["source"].split(";"):
            part = part.strip()
            match = re.match(
                r"((?:scripts/|tests/|review/|data/|src/)[^ :;§]*|pyproject\.toml|uv\.lock|\.gitignore)",
                part,
            )
            assert match, f"unresolved source: {part}"
            path = ROOT / match[1]
            assert path.exists(), path
            line = re.match(r":(\d+)", part[match.end() :])
            if line:
                # Card/walkthrough line numbers point at the audited snapshot;
                # scripts/*.py were hand-edited afterwards, so accept any
                # historical length recorded for that file.
                history_lines = [
                    len(path.read_text(encoding="utf-8").splitlines()),
                    read_json("review/checks/source_manifest.json")["files"]
                    .get(match[1], {})
                    .get("lines", 0),
                    cleanup["original_scope_after"].get(match[1], {}).get("lines", 0),
                ]
                assert int(line[1]) <= max(history_lines), part

    export = read_json("review/anki/export_manifest.json")
    assert export["source_sha256"] == digest(ROOT / "review/anki/cards.json")
    assert export["cards"] == len(cards) and export["core_cards"] == core
    for name, value in export["outputs"].items():
        assert digest(ROOT / "review/anki" / name) == value["sha256"], name
    assert set(export["outputs"]) == {
        "graphrag_review_ru.tsv",
        "graphrag_review_ru.apkg",
    }

    with (ROOT / "review/anki/graphrag_review_ru.tsv").open(
        encoding="utf-8", newline=""
    ) as f:
        rows = list(
            csv.reader((line for line in f if not line.startswith("#")), delimiter="\t")
        )
    assert len(rows) == len(cards)
    for row, card in zip(rows, cards):
        assert len(row) == 3
        assert row[0] == text_html(card["q"])
        assert (
            row[1]
            == text_html(card["a"])
            + "<br><br><small>Источник: "
            + text_html(card["source"])
            + "</small>"
        )
        assert row[2].split() == ["graphrag_review", *card["tags"]]

    with zipfile.ZipFile(ROOT / "review/anki/graphrag_review_ru.apkg") as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"collection.anki2", "media"}
        assert json.loads(archive.read("media")) == {}
        with tempfile.TemporaryDirectory(
            prefix="graphrag-anki-check-", dir="/tmp/opencode"
        ) as folder:
            db_path = Path(folder) / "collection.anki2"
            db_path.write_bytes(archive.read("collection.anki2"))
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                notes = db.execute("SELECT id, guid, tags, flds FROM notes").fetchall()
                card_rows = db.execute("SELECT nid, ord FROM cards").fetchall()
                assert len(notes) == len(card_rows) == len(cards)
                assert len({note[1] for note in notes}) == len(notes)
                assert Counter(row[0] for row in card_rows) == Counter(
                    note[0] for note in notes
                )
                assert all(row[1] == 0 for row in card_rows)
                by_id = {note[3].split("\x1f")[0]: note for note in notes}
                assert set(by_id) == {card["id"] for card in cards}
                for card in cards:
                    note = by_id[card["id"]]
                    assert note[3].split("\x1f") == [
                        card["id"],
                        text_html(card["q"]),
                        text_html(card["a"]),
                        text_html(card["source"]),
                    ]
                    assert set(note[2].split()) == {"graphrag_review", *card["tags"]}
                models, decks = db.execute("SELECT models, decks FROM col").fetchone()
                model = next(iter(json.loads(models).values()))
                assert [field["name"] for field in model["flds"]] == [
                    "ID",
                    "Question",
                    "Answer",
                    "Source",
                ]
                assert len(model["tmpls"]) == 1
                assert "{{Question}}" in model["tmpls"][0]["qfmt"]
                assert any(
                    deck["name"] == "GraphRAG Papers — Review RU"
                    for deck in json.loads(decks).values()
                )

    graph = read_json("review/checks/graph.json")
    inputs = read_json("review/checks/input_data.json")
    assert inputs["papers"] == 500 and inputs["unique_paper_ids"] == 498
    assert (
        inputs["triplet_records"] == 522
        and inputs["paper_ids_with_repeated_records"] == 24
    )
    assert (
        inputs["relation_records"] == 3113
        and inputs["distinct_relations_per_paper"] == 3004
    )
    assert graph["papers"][0] == {
        "count": 498,
        "with_abstract": 498,
        "with_embedding": 498,
    }
    assert graph["entities"][0] == {"count": 2690, "with_embedding": 2690}
    assert {row["type"]: row["count"] for row in graph["edges"]} == {
        "R": 3004,
        "MENTIONS": 3121,
    }
    assert graph["sources"][0] == {"count": 3004, "with_nonempty_sources": 3004}
    assert (
        graph["self_edges"][0]["count"] == 16
        and graph["isolated_papers"][0]["count"] == 13
    )
    budget = read_json("review/checks/embedding_budget.json")
    assert (
        budget["max_seq_length"],
        budget["texts_over_model_limit"],
        budget["longest_text_tokens"],
    ) == (256, 388, 547)
    api = read_json("review/checks/api_contract.json")
    assert api["empty_question"] == api["whitespace_question"] == 200
    assert api["missing_question"] == 422 and api["get_ask"] == 405
    assert (
        api["driver_closed_on_normal_shutdown"]
        and not api["driver_closed_on_model_startup_failure"]
    )
    watermark = read_json("review/checks/watermark_audit.json")
    assert sum(scan["report"]["files_scanned"] for scan in watermark["scans"]) == 24
    for scan in watermark["scans"]:
        assert scan["returncode"] == 0
        assert not scan["report"]["files_skipped"]
        assert scan["report"]["summary"]["actionable_files"] == 0
        assert scan["report"]["summary"]["with_suspicious_text"] == 0

    laya = read_json("data/laya_eval_results.json")
    labels = Counter(row["expected"] for row in read_json("data/laya_eval.json"))
    assert labels == {"A": 3, "B": 15, "U": 2}
    counts = {
        key: sum(
            row["expected"] == expected and row["predicted"] == predicted
            for row in laya["results"]
        )
        for key, expected, predicted in (
            ("tp", "A", "A"),
            ("fp", "B", "A"),
            ("fn", "A", "B"),
            ("tn", "B", "B"),
        )
    }
    assert counts == {"tp": 3, "fp": 8, "fn": 0, "tn": 7}
    assert all(laya["metrics"][key] == value for key, value in counts.items())
    assert math.isclose(laya["metrics"]["precision"], 3 / 11)

    raw = read_json(f"data/evaluations/{EVAL_NAME}.json")
    assessed = read_json(f"data/evaluations/{EVAL_NAME}.review.json")
    assert len(raw["results"]) == 5
    assert sum(row["retrieval_hit"] is True for row in raw["results"]) == 4
    timings = {"retrieval_only": [], "graph_enriched": []}
    cited = Counter()
    for row in raw["results"]:
        a = row["answers"]["retrieval_only"]
        b = row["answers"]["graph_enriched"]
        assert (
            b["prompt"].replace("\n".join(row["context"]["facts"]), "") == a["prompt"]
        )
        for mode, answer in row["answers"].items():
            assert "error" not in answer and not answer["truncated"]
            timings[mode].append(answer["wall_seconds"])
            if (
                row["expected_source_ids"]
                and answer["citations"]["retrieved_source_cited"]
            ):
                cited[mode] += 1
    for mode, values in timings.items():
        assert math.isclose(
            sum(values) / len(values),
            assessed["summary"]["mean_generation_wall_seconds"][mode],
        )
        assert cited[mode] == 1

    # Published connection settings must read the password from the environment.
    for name in ("app", "qa", "load_graph", "embeddings", "eval"):
        tree = ast.parse((ROOT / f"scripts/{name}.py").read_text())
        auth_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "AUTH"
                for target in node.targets
            )
        )
        expected = ast.parse(
            '("neo4j", os.environ.get("NEO4J_PASSWORD", ""))', mode="eval"
        ).body
        assert ast.dump(auth_node.value) == ast.dump(expected), name
    documents = sorted((ROOT / "review").glob("*.md")) + [
        ROOT / "review/anki/README.md"
    ]
    checked_links = 0
    for path in documents:
        text = path.read_text(encoding="utf-8")
        assert text.count("```") % 2 == 0, path
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if target.startswith(("https://", "http://", "#")):
                continue
            target_path = (path.parent / target.split("#")[0]).resolve()
            assert target_path.exists() or target_path == REPORT, (path, target)
            checked_links += 1
    # Ensure the key coverage categories are represented, not just file counts.
    walkthrough = (ROOT / "review/CODE_WALKTHROUGH_RU.md").read_text()
    original_python = sorted(
        name for name in cleanup["original_scope_after"] if name.endswith(".py")
    )
    assert all(Path(name).name in walkthrough for name in original_python)

    tests = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert tests.returncode == 0, tests.stderr
    assert "Ran 36 tests" in tests.stderr
    changed_after = [
        name
        for name, value in baseline.items()
        if digest(ROOT / name) != value["sha256"]
    ]
    assert not changed_after, changed_after
    return {
        "status": "passed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files_verified": len(baseline),
        "source_baseline": baseline_file,
        "source_files_unchanged_since_selected_baseline": len(baseline),
        "original_python_files_syntax_ok": len(original_python),
        "review_tool_python_files_syntax_ok": sum(
            path.parent == ROOT / "review/tools" for path in syntax_paths
        ),
        "unique_cards": len(cards),
        "core_cards": core,
        "tsv_rows_match_json": True,
        "apkg_notes_and_cards_match_json": True,
        "apkg_sqlite_integrity": "ok",
        "export_hashes_match": True,
        "markdown_local_links_checked": checked_links,
        "walkthrough_covers_all_original_python_files": True,
        "review_artifact_sha256": {
            str(path.relative_to(ROOT)): digest(path)
            for path in [
                *documents,
                ROOT / "review/anki/cards.json",
                ROOT / "review/anki/graphrag_review_ru.tsv",
                ROOT / "review/anki/graphrag_review_ru.apkg",
                *sorted((ROOT / "review/tools").glob("*.py")),
            ]
        },
        "saved_graph_input_embedding_api_numbers_verified": True,
        "laya_confusion_matrix_recomputed": counts,
        "mini_eval_prompt_pairs_timings_and_url_counts_rechecked": True,
        "unit_tests": {
            "returncode": tests.returncode,
            "count": 36,
            "stderr": tests.stderr,
        },
        "limitations": [
            "No live Anki GUI import was performed; APKG was checked through ZIP/SQLite.",
            "No new LLM generation, ingestion, Laya inference, migration, image/audio/video processing or proprietary watermark detection.",
            "scripts/*.py carry the author's post-audit hand edit; walkthrough line numbers and quotes describe the audited snapshot.",
            "Saved Neo4j/API/embedding evidence is a snapshot; no fresh live database checks in this verifier.",
            "Mechanical consistency checks do not replace independent semantic/human review.",
            "Ruff was not installed and no Ruff lint run was performed.",
        ],
    }


def main():
    report = verify()
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "unit_tests"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
