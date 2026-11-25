import json
from datetime import datetime
from pathlib import Path
from neo4j import GraphDatabase
from load_graph import URI, AUTH

if __name__ == "__main__":
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session(default_access_mode="READ") as session:
            relations = session.run("""
                MATCH (a:Entity)-[r:R]->(b:Entity)
                RETURN a.name AS head,
                       b.name AS tail,
                       properties(r) AS properties
                """).data()
    Path("data/backups").mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(f"data/backups/relations_{timestamp}.json")
    with path.open("x", encoding="utf-8") as f:
        json.dump(relations, f, ensure_ascii=False, indent=2)
    print(f"Connections saved: {len(relations)}")
    print(f"File: {path}")
