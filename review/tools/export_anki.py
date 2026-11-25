"""Export reviewed cards to HTML-safe TSV and optionally a genanki APKG.

Standard-library TSV only:
    python review/tools/export_anki.py
APKG (genanki must be installed in the interpreter's isolated environment):
    /tmp/opencode/graphrag-review-export/bin/python review/tools/export_anki.py --apkg
"""

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "review/anki"
DECK_NAME = "GraphRAG Papers — Review RU"
MODEL_ID = 1732550721
DECK_ID = 1732550722


def text_html(value):
    return html.escape(value, quote=True).replace("\n", "<br>")


def load_cards():
    data = json.loads((FOLDER / "cards.json").read_text(encoding="utf-8"))
    cards = data["cards"]
    for field in ("id", "q"):
        values = [row[field].strip() for row in cards]
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate {field}")
    for row in cards:
        if not all(
            isinstance(row.get(key), str) and row[key].strip()
            for key in ("id", "q", "a", "source")
        ):
            raise ValueError("Every card needs nonempty id/q/a/source strings.")
        if not row.get("tags") or any(
            any(char.isspace() for char in tag) for tag in row["tags"]
        ):
            raise ValueError("Tags must be nonempty and contain no whitespace.")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apkg", action="store_true")
    args = parser.parse_args()
    data = load_cards()
    cards = data["cards"]
    with (FOLDER / "graphrag_review_ru.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        f.write("#separator:Tab\n#html:true\n#tags column:3\n")
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        for row in cards:
            back = (
                text_html(row["a"])
                + "<br><br><small>Источник: "
                + text_html(row["source"])
                + "</small>"
            )
            writer.writerow(
                [text_html(row["q"]), back, " ".join(["graphrag_review", *row["tags"]])]
            )
    if args.apkg:
        import genanki

        model = genanki.Model(
            MODEL_ID,
            "GraphRAG Review RU",
            fields=[{"name": name} for name in ("ID", "Question", "Answer", "Source")],
            templates=[
                {
                    "name": "Вопрос → ответ",
                    "qfmt": "{{Question}}",
                    "afmt": '{{FrontSide}}<hr id="answer">{{Answer}}<br><br><div class="source">Источник: {{Source}}</div>',
                }
            ],
            css=".card { font-family: Arial; font-size: 21px; text-align: left; color: #222; background: #fff; line-height: 1.45; } .source { font-size: 14px; color: #666; } .nightMode .card { color: #ddd; background: #222; }",
        )
        deck = genanki.Deck(DECK_ID, DECK_NAME, description=data["disclosure"])
        for row in cards:
            deck.add_note(
                genanki.Note(
                    model=model,
                    fields=[
                        row["id"],
                        text_html(row["q"]),
                        text_html(row["a"]),
                        text_html(row["source"]),
                    ],
                    tags=["graphrag_review", *row["tags"]],
                    guid=genanki.guid_for("graphrag-review-ru-v1", row["id"]),
                )
            )
        genanki.Package(deck).write_to_file(str(FOLDER / "graphrag_review_ru.apkg"))
    outputs = [FOLDER / "graphrag_review_ru.tsv"]
    if args.apkg:
        outputs.append(FOLDER / "graphrag_review_ru.apkg")
    report = {
        "cards": len(cards),
        "core_cards": sum("priority::core" in row["tags"] for row in cards),
        "source_sha256": hashlib.sha256(
            (FOLDER / "cards.json").read_bytes()
        ).hexdigest(),
        "outputs": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in outputs
        },
    }
    (FOLDER / "export_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
