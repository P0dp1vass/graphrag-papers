import json
import laya

if __name__ == "__main__":
    with open("data/papers.json", encoding="utf-8") as f:
        papers = json.load(f)
    abstracts = {p["id"]: p["abstract"] for p in papers}
    cases = [
        (
            "http://arxiv.org/abs/2611.17788v1",
            "RAG-FGO uses an elite-preserving memory pool.",
            "A",
        ),
        (
            "http://arxiv.org/abs/2611.17788v1",
            "RAG-FGO improves the elite-preserving memory pool itself.",
            "B",
        ),
        (
            "http://arxiv.org/abs/2611.19862v1",
            "Bioformer-RetroMAE outperforms PubMedBERT on biomedical retrieval.",
            "A",
        ),
        (
            "http://arxiv.org/abs/2611.19862v1",
            "Bioformer-RetroMAE is an extension of BM25.",
            "B",
        ),
    ]
    questions = {
        "supported": {
            "type": "choice",
            "instructions": (
                "Is the claim supported by the abstract? "
                "Check the relation and its direction."
            ),
            "criteria": {
                "A": "The abstract supports the claim.",
                "B": "The abstract does not support the claim.",
            },
        }
    }
    agent = laya.load("convaiinnovations/laya")
    for paper_id, claim, expected in cases:
        result = agent.predict({"abstract": abstracts[paper_id], "claim": claim},questions)
        answer = result["answers"]["supported"]
        print(f"\n Claim: {claim}")
        print(f"Expected: {expected}")
        print(json.dumps(answer, ensure_ascii=False, indent=2))