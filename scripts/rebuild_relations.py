import json
from neo4j import GraphDatabase
from entity_names import canonicalize_entity
from load_graph import URI, AUTH

def rebuild(tx, relations: list[dict]) -> int:
    tx.run("MATCH (:Entity)-[r:R]->(:Entity) DELETE r").consume()
    result = tx.run(
        """
        UNWIND $relations AS item
        MATCH (a:Entity {name: item.head})
        MATCH (b:Entity {name: item.tail})
        MERGE (a)-[r:R {type: item.relation}]->(b)
        SET r.source_ids =
            CASE
                WHEN item.paper_id IN coalesce(r.source_ids, [])
                THEN r.source_ids
                ELSE coalesce(r.source_ids, []) + [item.paper_id]
            END
        RETURN count(*) AS processed
        """,
        relations=relations
    ).single()
    processed = result["processed"]
    if processed != len(relations):
        raise ValueError("Not all tail finds")
    return processed

if __name__ == "__main__":
    with open(
        "data/backups/relations_20261125_162658.json",
        encoding="utf-8",
    ) as f:
        backup = json.load(f)
    if not backup:
        raise ValueError("Empty backup")
    with open("data/triplets.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    relations = [
        {
            "head": canonicalize_entity(rel["head"]),
            "relation": rel["relation"],
            "tail": canonicalize_entity(rel["tail"]),
            "paper_id": rec["paper_id"],
        }
        for rec in records
        for rel in rec["relations"]
    ]
    if not relations:
        raise ValueError("No relations for recovery")
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            processed = session.execute_write(rebuild, relations)
    print(f"Saves relations: {processed}")
