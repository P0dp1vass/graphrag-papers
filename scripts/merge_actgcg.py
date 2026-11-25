import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from neo4j import GraphDatabase
from entity_names import ALIASES
from load_graph import AUTH, URI

ALIAS = "ACTGCG"
CANONICAL = "ActGCG"
ROOT = Path(__file__).resolve().parents[1]

def snapshot(tx) -> dict:
    nodes = tx.run(
        """
        MATCH (e:Entity)
        WHERE e.name IN $names
        RETURN elementId(e) AS id, labels(e) AS labels,
               properties(e) AS properties
        ORDER BY id
        """,
        names=[ALIAS, CANONICAL]
    ).data()
    edges = tx.run(
        """
        MATCH (a)-[r]->(b)
        WHERE elementId(a) IN $ids OR elementId(b) IN $ids
        RETURN elementId(r) AS id,
               elementId(a) AS head, labels(a) AS head_labels,
               properties(a) AS head_properties,
               elementId(b) AS tail, labels(b) AS tail_labels,
               properties(b) AS tail_properties,
               type(r) AS kind, properties(r) AS properties
        ORDER BY id
        """,
        ids=[node["id"] for node in nodes]
    ).data()
    return {"nodes": nodes, "edges": edges}

def merge_edge_properties(left: dict, right: dict) -> dict:
    merged = dict(left)
    for key, value in right.items():
        if key == "source_ids":
            existing = merged.get(key, [])
            if not isinstance(existing, list) or not isinstance(value, list):
                raise ValueError("source_ids must be lists.")
            if not all(isinstance(item, str) for item in existing + value):
                raise ValueError("Every source_id must be a string.")
            merged[key] = sorted(set(existing + value))
        elif key in merged and merged[key] != value:
            raise ValueError(f"Conflicting edge property: {key}")
        else:
            merged[key] = value
    return merged

def edge_key(edge: dict) -> tuple:
    return (
        edge["head"],
        edge["kind"],
        edge["properties"].get("type", ""),
        edge["tail"]
    )

def build_plan(before: dict) -> dict | None:
    if ALIASES.get(ALIAS) != CANONICAL:
        raise ValueError("The alias must be explicitly approved in entity_names.py.")
    by_name = {}
    for node in before["nodes"]:
        name = node["properties"]["name"]
        if name in by_name:
            raise ValueError(f"Duplicate node name: {name}")
        by_name[name] = node
    if CANONICAL not in by_name:
        raise ValueError("Canonical ActGCG node is missing; no changes made.")
    if ALIAS not in by_name:
        return None
    old, target = by_name[ALIAS], by_name[CANONICAL]
    if any(set(node["labels"]) != {"Entity"} for node in (old, target)):
        raise ValueError("Unexpected node labels; manual review required.")
    properties = dict(target["properties"])
    for key, value in old["properties"].items():
        if key in {"name", "embedding", "aliases"}:
            continue
        if key in properties and properties[key] != value:
            raise ValueError(f"Conflicting node property: {key}")
        properties[key] = value
    aliases = []
    for node in (old, target):
        values = node["properties"].get("aliases", [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise ValueError("aliases must be a list of strings.")
        aliases.extend(values)
    properties["aliases"] = sorted((set(aliases) | {ALIAS}) - {CANONICAL})

    grouped = {}
    ids = {old["id"], target["id"]}
    for edge in before["edges"]:
        if edge["kind"] == "R":
            if not all("Entity" in edge[f"{end}_labels"] for end in ("head", "tail")):
                raise ValueError("Unexpected endpoints of an R edge.")
            relation_type = edge["properties"].get("type")
            if not isinstance(relation_type, str) or not relation_type:
                raise ValueError("An R edge has no valid type property.")
        elif edge["kind"] == "MENTIONS":
            if "Paper" not in edge["head_labels"] or edge["tail"] not in ids:
                raise ValueError("Unexpected MENTIONS direction or endpoints.")
        else:
            raise ValueError(f"Unsupported relationship: {edge['kind']}")
        mapped = {
            "head": target["id"] if edge["head"] == old["id"] else edge["head"],
            "tail": target["id"] if edge["tail"] == old["id"] else edge["tail"],
            "kind": edge["kind"],
            "properties": merge_edge_properties({}, edge["properties"]),
        }
        key = edge_key(mapped)
        if key in grouped:
            mapped["properties"] = merge_edge_properties(
                grouped[key]["properties"], mapped["properties"]
            )
        grouped[key] = mapped
    return {
        "old_id": old["id"],
        "target_id": target["id"],
        "properties": properties,
        "edges": sorted(grouped.values(), key=edge_key)
    }

def apply_plan(tx, before: dict, plan: dict) -> dict:
    tx.run(
        """
        MATCH (e:Entity) WHERE elementId(e) IN $ids
        SET e.name = e.name
        """,
        ids=[plan["old_id"], plan["target_id"]]
    ).consume()
    if snapshot(tx) != before:
        raise ValueError("The subgraph changed after backup; migration cancelled.")
    deleted = tx.run(
        """
        MATCH ()-[r]->() WHERE elementId(r) IN $ids
        WITH collect(r) AS edges
        FOREACH (edge IN edges | DELETE edge)
        RETURN size(edges) AS deleted
        """,
        ids=[edge["id"] for edge in before["edges"]],
    ).single()["deleted"]
    if deleted != len(before["edges"]):
        raise ValueError("Could not replace all backed-up edges.")
    tx.run(
        """
        MATCH (e:Entity) WHERE elementId(e) = $id
        SET e = $properties
        """,
        id=plan["target_id"],
        properties=plan["properties"]
    ).consume()
    for kind in ("R", "MENTIONS"):
        edges = [edge for edge in plan["edges"] if edge["kind"] == kind]
        pattern = (
            "MERGE (a)-[r:R {type: item.properties.type}]->(b)"
            if kind == "R"
            else "MERGE (a)-[r:MENTIONS]->(b)"
        )
        processed = tx.run(
            """
            UNWIND $edges AS item
            MATCH (a) WHERE elementId(a) = item.head
            MATCH (b) WHERE elementId(b) = item.tail
            """
            + pattern
            + """
            SET r = item.properties
            RETURN count(r) AS processed
            """,
            edges=edges
        ).single()["processed"]
        if processed != len(edges):
            raise ValueError("Not all relationships were restored.")
    tx.run(
        "MATCH (e:Entity) WHERE elementId(e) = $id DELETE e",
        id=plan["old_id"],
    ).consume()
    after = snapshot(tx)
    if len(after["nodes"]) != 1:
        raise ValueError("Expected exactly one remaining ActGCG node.")
    if after["nodes"][0]["properties"] != plan["properties"]:
        raise ValueError("Canonical node properties were not preserved.")
    actual_edges = [
        {key: edge[key] for key in ("head", "tail", "kind", "properties")}
        for edge in after["edges"]
    ]
    if sorted(actual_edges, key=edge_key) != plan["edges"]:
        raise ValueError("Relationship verification failed; changes rolled back.")
    return {
        "nodes_before": len(before["nodes"]),
        "nodes_after": len(after["nodes"]),
        "incident_edges_before": len(before["edges"]),
        "incident_edges_after": len(after["edges"]),
    }

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Back up and apply; default is dry-run."
    )
    args = parser.parse_args()
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            before = session.execute_read(snapshot)
            plan = build_plan(before)
            if plan is None:
                print("Already merged: ACTGCG is absent; ActGCG exists.")
                return
            print(f"Reviewed alias: {ALIAS} -> {CANONICAL}")
            print(f"Incident edges: {len(before['edges'])} -> {len(plan['edges'])}")
            if not args.apply:
                print("Dry-run only. Use --apply to create a backup and migrate.")
                return
            folder = ROOT / "data" / "backups"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            backup = folder / f"actgcg_before_merge_{stamp}.json"
            with backup.open("x", encoding="utf-8") as f:
                json.dump(
                    {"alias": ALIAS, "canonical": CANONICAL, **before},
                    f,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                f.flush()
                os.fsync(f.fileno())
            print(f"Backup: {backup}", flush=True)
            result = session.execute_write(apply_plan, before, plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()