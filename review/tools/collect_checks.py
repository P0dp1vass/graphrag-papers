"""Read-only checks for the review package; never run ingestion or migrations.

Use a fresh output directory for another audit:
    python review/tools/collect_checks.py --output review/checks_second_run
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]


def save(folder, name, value):
    with (folder / name).open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def source_files():
    paths = [
        path
        for directory in ("scripts", "src", "tests")
        for path in (ROOT / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    paths.extend(
        ROOT / name
        for name in (
            ".gitignore",
            ".python-version",
            "pyproject.toml",
            "uv.lock",
            "README.md",
        )
        if (ROOT / name).is_file()
    )
    return sorted(paths)


def manifest():
    return {
        str(path.relative_to(ROOT)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "lines": len(path.read_text(encoding="utf-8").splitlines()),
        }
        for path in source_files()
    }


def execute(command, timeout=120, env=None):
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def syntax_checks():
    results = []
    for path in source_files():
        if path.suffix != ".py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        compile(tree, str(path), "exec")
        definitions = [
            {
                "name": node.name,
                "line": node.lineno,
                "kind": type(node).__name__,
            }
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        results.append(
            {
                "file": str(path.relative_to(ROOT)),
                "syntax": "ok",
                "definitions": definitions,
            }
        )
    return results


def input_data_checks():
    papers = json.loads((ROOT / "data/papers.json").read_text())
    records = [
        json.loads(line)
        for line in (ROOT / "data/triplets.jsonl").read_text().splitlines()
        if line.strip()
    ]
    from collections import Counter

    ids = Counter(record["paper_id"] for record in records)
    unique_relations = {
        (record["paper_id"], rel["head"], rel["relation"], rel["tail"])
        for record in records
        for rel in record["relations"]
    }
    return {
        "papers": len(papers),
        "triplet_records": len(records),
        "unique_paper_ids": len(ids),
        "paper_ids_with_repeated_records": sum(count > 1 for count in ids.values()),
        "relation_records": sum(len(record["relations"]) for record in records),
        "distinct_relations_per_paper": len(unique_relations),
        "paper_ids_missing_from_extraction": sorted(
            {paper["id"] for paper in papers} - set(ids)
        ),
    }


def graph_checks():
    from neo4j import GraphDatabase

    sys.path.insert(0, str(ROOT / "scripts"))
    from load_graph import URI, AUTH

    queries = {
        "nodes": "MATCH (n) RETURN labels(n) AS labels, count(n) AS count",
        "edges": "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count",
        "papers": """
            MATCH (p:Paper)
            RETURN count(p) AS count, count(p.abstract) AS with_abstract,
                   count(p.embedding) AS with_embedding
        """,
        "entities": """
            MATCH (e:Entity)
            RETURN count(e) AS count, count(e.embedding) AS with_embedding
        """,
        "sources": """
            MATCH ()-[r:R]->()
            RETURN count(r) AS count,
                   sum(CASE WHEN size(coalesce(r.source_ids, [])) > 0 THEN 1 ELSE 0 END)
                   AS with_nonempty_sources
        """,
        "self_edges": """
            MATCH (e:Entity)-[r:R]->(e)
            RETURN count(r) AS count
        """,
        "isolated_papers": """
            MATCH (p:Paper) WHERE NOT (p)--()
            RETURN count(p) AS count
        """,
        "name_variant_groups": """
            MATCH (e:Entity)
            WITH trim(toLower(replace(e.name, '_', ' '))) AS key, collect(e.name) AS names
            WHERE size(names) > 1
            RETURN key, names, size(names) AS variants
            ORDER BY variants DESC, key
        """,
        "constraints": """
            SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties
            RETURN name, type, labelsOrTypes, properties
        """,
        "indexes": """
            SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties
            RETURN name, type, state, labelsOrTypes, properties
        """,
        "canonical_actgcg": """
            MATCH (e:Entity) WHERE e.name IN ['ActGCG', 'ACTGCG']
            RETURN e.name AS name, e.aliases AS aliases, size(e.embedding) AS dimensions,
                   COUNT { (e)-[:R]-() } AS incident_facts
        """,
    }
    with GraphDatabase.driver(URI, auth=AUTH, connection_timeout=5) as driver:
        driver.verify_connectivity()
        with driver.session(default_access_mode="READ") as session:
            return {name: session.run(query).data() for name, query in queries.items()}


def mock_api_checks():
    """Contract checks with fake resources, not a live-model quality test."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    import app as api

    driver = MagicMock()
    with (
        patch.object(api.GraphDatabase, "driver", return_value=driver),
        patch.object(api, "SentenceTransformer", return_value=object()),
        patch.object(api, "ask", return_value="stub answer"),
        TestClient(api.app) as client,
    ):
        results = {
            "health": client.get("/health").status_code,
            "valid_ask": client.post(
                "/ask", json={"question": "Question?"}
            ).status_code,
            "missing_question": client.post("/ask", json={}).status_code,
            "empty_question": client.post("/ask", json={"question": ""}).status_code,
            "whitespace_question": client.post(
                "/ask", json={"question": "   "}
            ).status_code,
            "extra_field": client.post(
                "/ask", json={"question": "Question?", "extra": 1}
            ).status_code,
            "get_ask": client.get("/ask").status_code,
        }
    results["driver_closed_on_normal_shutdown"] = driver.close.called
    failed_driver = MagicMock()
    with (
        patch.object(api.GraphDatabase, "driver", return_value=failed_driver),
        patch.object(
            api,
            "SentenceTransformer",
            side_effect=RuntimeError("simulated load failure"),
        ),
    ):
        try:
            with TestClient(api.app):
                pass
        except RuntimeError:
            pass
    results["driver_closed_on_model_startup_failure"] = failed_driver.close.called
    results["scope"] = "Mocked dependencies; no HTTP request to Ollama or Neo4j."
    return results


def embedding_budget_check():
    """Only tokenize existing inputs; do not encode or change vectors."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True, device="cpu")
    papers = json.loads((ROOT / "data/papers.json").read_text())
    texts = [f"{paper['title']}. {paper['abstract']}" for paper in papers]
    lengths = [
        len(ids)
        for ids in model.tokenizer(texts, truncation=False, add_special_tokens=True)[
            "input_ids"
        ]
    ]
    return {
        "model": "all-MiniLM-L6-v2",
        "max_seq_length": model.max_seq_length,
        "papers_checked": len(texts),
        "texts_over_model_limit": sum(
            length > model.max_seq_length for length in lengths
        ),
        "longest_text_tokens": max(lengths),
        "note": "Tokenizer check, not inference. Full abstracts remain in QA context; this limit concerns the embedding inputs.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "review/checks")
    parser.add_argument("--watermark-tool-root", type=Path)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    before = manifest()
    save(
        folder,
        "source_manifest.json",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": before,
        },
    )
    save(folder, "syntax_and_definitions.json", syntax_checks())
    save(folder, "input_data.json", input_data_checks())
    for name, check in (
        ("graph", graph_checks),
        ("api_contract", mock_api_checks),
        ("embedding_budget", embedding_budget_check),
    ):
        try:
            value = check()
        except Exception as error:
            value = {
                "error": f"{type(error).__name__}: {error}",
                "status": "not_verified",
            }
        save(folder, f"{name}.json", value)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    tests = execute(
        [
            str(ROOT / ".venv/bin/python"),
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ],
        env=env,
    )
    save(folder, "unit_tests.json", tests)
    if args.watermark_tool_root:
        tool = args.watermark_tool_root.resolve()
        version = execute(["git", "-C", str(tool), "rev-parse", "HEAD"])
        scans = []
        for directory in ("scripts", "src", "tests"):
            run = execute(
                [
                    "python3",
                    "-B",
                    str(tool / "service/scripts/audit_dir.py"),
                    str(ROOT / directory),
                    "--json",
                    "--jobs",
                    "1",
                ],
                env=env,
            )
            if run["returncode"] in (0, 1, 3):
                run["report"] = json.loads(run.pop("stdout"))
            scans.append(run)
        save(
            folder,
            "watermark_audit.json",
            {
                "upstream_revision": version["stdout"].strip(),
                "mode": "Read-only Layer A audit. No prose/code rewriting; no network detectors.",
                "scans": scans,
            },
        )
    after = manifest()
    changed = sorted(
        name
        for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    )
    save(
        folder,
        "source_integrity.json",
        {
            "unchanged": not changed,
            "changed_files": changed,
            "scope": "scripts/, src/, tests/, and root project/config/lock files",
        },
    )
    if changed:
        raise RuntimeError(f"Source files changed during audit: {changed}")
    print(f"Checks saved to: {folder}")
    print(
        f"Source files unchanged: {len(before)}; unit-test exit: {tests['returncode']}"
    )


if __name__ == "__main__":
    main()
