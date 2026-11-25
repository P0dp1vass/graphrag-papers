import json
import laya

RELATION_TEXT = {
    "IMPROVES": "improves",
    "EXTENDS": "extends",
    "USES": "uses",
    "EVALUATED_ON": "is evaluated on",
    "PROPOSED_BY": "is proposed by",
    "APPLIED_TO": "is applied to",
    "RELATED_TO": "is related to",
}

if __name__ == "__main__":
    with open("data/laya_eval.json", encoding="utf-8") as f:
        examples = json.load(f)
    agent = laya.load("convaiinnovations/laya")
    questions = {
        "supported": {
            "type": "choice",
            "instructions": (
                "Is the claim supported by the abstract? "
                "Check the exact relation and its direction. "
                "Using a component does not by itself establish improvement. "
                "Outperforming a method does not mean extending that method."
            ),
            "criteria": {
                "A": "The abstract supports the claim.",
                "B": "The abstract does not support the claim.",
            },
        }
    }
    results = []
    for i, example in enumerate(examples, start=1):
        if example["expected"] == "U":
            continue
        verb = RELATION_TEXT[example["relation"]]
        claim = f"{example['head']} {verb} {example['tail']}."
        result = agent.predict(
            {
                "abstract": example["abstract"],
                "claim": claim,
            }, questions
        )
        answer = result["answers"]["supported"]
        predicted = answer["choice"]
        if predicted not in {"A", "B"}:
            raise ValueError(f"Unexpected prediction: {predicted}")
        row = {
            "example": i,
            "paper_id": example["paper_id"],
            "claim": claim,
            "expected": example["expected"],
            "predicted": predicted,
            "probabilities": answer["probabilities"]
        }
        results.append(row)
        print(
            f"{i}: expected={row['expected']}, " f"predicted={predicted} | {claim}",
            flush=True,
        )
    tp = sum(r["expected"] == "A" and r["predicted"] == "A" for r in results)
    fp = sum(r["expected"] == "B" and r["predicted"] == "A" for r in results)
    fn = sum(r["expected"] == "A" and r["predicted"] == "B" for r in results)
    tn = sum(r["expected"] == "B" and r["predicted"] == "B" for r in results)
    metrics = {
        "evaluated": len(results),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": (tp + tn) / len(results) if results else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }
    with open("data/laya_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(
            {"metrics": metrics, "results": results},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print("\nMETRICS:")
    print(json.dumps(metrics, indent=2))