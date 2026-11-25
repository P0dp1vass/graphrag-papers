import json
import random
from pathlib import Path

if __name__ == "__main__":
    with open("data/papers.json", encoding="utf-8") as f:
        abstracts = {p["id"]: p["abstract"] for p in json.load(f)}
    unique = {}
    with open("data/triplets.jsonl", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            for rel in record["relations"]:
                key = (
                    record["paper_id"],
                    rel["head"],
                    rel["relation"],
                    rel["tail"],
                )
                unique[key] = {
                    "paper_id": record["paper_id"],
                    "abstract": abstracts[record["paper_id"]],
                    **rel,
                    "expected": None,
                }
    candidates = sorted(
        unique.values(),
        key=lambda row: (row["paper_id"], row["head"], row["relation"], row["tail"])
    )
    sample = random.Random(42).sample(candidates, min(20, len(candidates)))
    path = Path("data/laya_eval.json")
    with path.open("x", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
    print(f"Examples created: {len(sample)}")
    print(path)