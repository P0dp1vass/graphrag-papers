import json
import os
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

URI = "bolt://localhost:7687"
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", ""))
MODEL_NAME = "all-MiniLM-L6-v2"

def create_index(driver, dim: int) -> None:
    query = """
    CREATE VECTOR INDEX entity_vec IF NOT EXISTS
    FOR (e:Entity) ON (e.embedding)
    OPTIONS {indexConfig: {
        `vector.dimensions`: $dim,
        `vector.similarity_function`: 'cosine'
    }}
    """
    with driver.session() as session:
        session.run(query, dim=dim)

def embed_entities(driver, model) -> None:
    with driver.session() as session:
        names = [
            r["name"] for r in session.run("MATCH (e:Entity) RETURN e.name AS name")
        ]
    print(f"Entity for embedding: {len(names)}")
    vectors = model.encode(names)
    pairs = [{"name": n, "vec": v.tolist()} for n, v in zip(names, vectors)]
    with driver.session() as session:
        session.run(
            """
            UNWIND $pairs AS pair
            MATCH (e:Entity {name: pair.name})
            SET e.embedding = pair.vec
            """, pairs=pairs
        )
    print(f'Saves vectors: {len(pairs)}')

def embed_papers(driver, model) -> None:
    with open("data/papers.json") as f:
        papers = json.load(f)
    abstracts = {p["id"]: p["abstract"] for p in papers}
    with driver.session() as session:
        rows = session.run("MATCH (p:Paper) RETURN p.id AS id, p.title AS title").data()
    texts = [f"{r['title']}. {abstracts.get(r['id'], '')}" for r in rows]
    vectors = model.encode(texts)
    pairs = [{"id": r["id"], "vec": v.tolist()} for r, v in zip(rows, vectors)]
    with driver.session() as session:
        session.run(
            """
            UNWIND $pairs AS pair
            MATCH (p:Paper {id: pair.id})
            SET p.embedding = pair.vec
            """,pairs=pairs
        )
    print(f"Saves vectors of papers: {len(pairs)}")

if __name__ == "__main__":
    driver = GraphDatabase.driver(URI, auth=AUTH)
    driver.verify_connectivity()
    model = SentenceTransformer(MODEL_NAME)
    create_index(driver, dim=384)
    embed_entities(driver, model)
    embed_papers(driver, model)
    driver.close()
    print("ok")
