import json
import time
import laya

THRESHOLD = 0.5
IN_FILE = "data/triplets.jsonl"
OUT_FILE = "data/triplets_filtered.jsonl"

def build_questions() -> dict:
    return {
        "supported": {
            "type": "noul",
            "instructions": "Is this relation stated or implied by the text?"
        }
    }

def load_abstracts() -> dict[str, str]:
    with open("data/papers.json") as f:
        papers = json.load(f)
    return {p["id"]: p["abstract"] for p in papers}

def filter_relations(agent, questions: dict) -> tuple[int, int]:
    with open(IN_FILE) as f:
        records = [json.loads(line) for line in f if line.strip()]
    abstracts = load_abstracts()
    total_in = 0
    total_out = 0
    with open(OUT_FILE, "w") as out:
        for i, rec in enumerate(records):
            kept = []
            for rel in rec["relations"]:
                state = {
                    "text": abstracts.get(rec["paper_id"], rec["title"]),
                    "relation": f"{rel['head']} {rel['relation']} {rel['tail']}",
                }
                res = agent.predict(state, questions)
                prob = res["answers"]["supported"]["noul"]
                total_in += 1
                if prob >= THRESHOLD:
                    kept.append(rel)
                    total_out += 1
            if kept:
                used = {r["head"] for r in kept} | {r["tail"] for r in kept}
                out.write(
                    json.dumps(
                        {**rec, "entities": sorted(used), "relations": kept},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            if i % 50 == 0:
                print(f"[{i}/{len(records)}] connections have passed: {total_out}/{total_in}")
    return total_in, total_out

if __name__ == "__main__":
    t0 = time.time()
    agent = laya.load("convaiinnovations/laya")
    questions = build_questions()
    before, after = filter_relations(agent, questions)
    kept_pct = 100 * after / max(before, 1)
    print(f"\nThere were connections: {before}, left: {after} ({kept_pct:.0f}%)")