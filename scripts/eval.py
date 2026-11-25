import json
import os
import requests
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from qa import ask

OLLAMA_URL = "http://localhost:11434/api/chat"
LLM = "qwen2.5:7b-instruct-q4_K_M"
URI = "bolt://localhost:7687"
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", ""))

QUESTIONS = [
    "Какие методы улучшают RAG?",
    "Что такое GraphRAG?",
    "Какие подходы используются для post-training языковых моделей?",
    "Связан ли retrieval с reasoning?",
    "Какие модели применяются для агентов?",
]


def ask_baseline(question: str) -> str:
    payload = {
        "model": LLM,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": question}],
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=180)
    r.raise_for_status()
    return r.json()["message"]["content"]


def sample_triplets(n: int = 20) -> list[dict]:
    with open("data/triplets.jsonl") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    flat = []
    for rec in recs:
        for rel in rec["relations"]:
            flat.append({"paper": rec["title"][:70], **rel})
    import random

    random.seed(42)
    return random.sample(flat, n)


if __name__ == "__main__":
    driver = GraphDatabase.driver(URI, auth=AUTH)
    driver.verify_connectivity()
    model = SentenceTransformer("all-MiniLM-L6-v2")
    results = []
    for q in QUESTIONS:
        baseline = ask_baseline(q)
        graphrag = ask(q, driver, model)
        print(q)
        print("\n", baseline[:700])
        print("\n", graphrag[:700])
        results.append({"question": q, "baseline": baseline, "graphrag": graphrag})

    with open("data/eval_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    for t in sample_triplets(20):
        print(f"  {t['head']} -[{t['relation']}]-> {t['tail']}   ({t['paper']})")
    driver.close()
