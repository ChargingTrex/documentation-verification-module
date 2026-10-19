"""
PP-OCRv5 vs PaddleOCR-VL 1.5 on the same synthetic cards.

    uv run python -m bench.ocr_bench [--engines pp-ocrv5,paddleocr-vl] [--cards DIR]

Reads every PNG in the card directory, parses it with the matching parser,
and scores each engine on: name exact match (case-insensitive), id_last4,
DOB, and seconds per image. Writes bench/results/ocr_bench.json and prints
a Markdown table for the README. PaddleOCR-VL needs the `ocr-vl` container:
`docker compose --profile vl up ocr-vl`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from app.ocr.aadhaar import parse_aadhaar
from app.ocr.engine import OCRError, PaddleOCREngine, PaddleOCRVLEngine
from app.ocr.pan import parse_pan

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CARDS = ROOT / "tests" / "fixtures" / "idcards"
RESULTS = ROOT / "bench" / "results"
PARSERS = {"aadhaar": parse_aadhaar, "pan": parse_pan}
ENGINES = {"paddleocr": PaddleOCREngine, "paddleocr-vl": PaddleOCRVLEngine}


def _same_name(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def run(engine_name: str, cards: Path) -> dict:
    engine = ENGINES[engine_name]()
    manifest = json.loads((cards / "manifest.json").read_text())
    rows = []
    for filename, expected in manifest.items():
        data = (cards / filename).read_bytes()
        started = time.perf_counter()
        try:
            lines = engine.read(data, filename)
            error = None
        except OCRError as exc:
            lines, error = [], str(exc)
        elapsed = time.perf_counter() - started
        facts = (
            PARSERS[expected["type"]](lines, engine_name=engine.name, engine_detail=getattr(engine, "detail", None)).as_dict()
            if not error else {}
        )
        rows.append(
            {
                "card": filename,
                "seconds": round(elapsed, 2),
                "error": error,
                "name_ok": _same_name(facts.get("full_name"), expected.get("full_name")),
                "last4_ok": facts.get("id_last4") == expected.get("id_last4"),
                "dob_ok": facts.get("dob") == expected.get("dob"),
                "read": {k: facts.get(k) for k in ("full_name", "id_last4", "dob")},
                "lines": facts.get("lines", []),
            }
        )
    total = len(rows)
    return {
        "engine": engine.name,
        "cards": total,
        "name_accuracy": sum(r["name_ok"] for r in rows) / total,
        "last4_accuracy": sum(r["last4_ok"] for r in rows) / total,
        "dob_accuracy": sum(r["dob_ok"] for r in rows) / total,
        "mean_seconds": round(statistics.mean(r["seconds"] for r in rows), 2),
        "errors": sum(1 for r in rows if r["error"]),
        "rows": rows,
    }


def table(results: list[dict]) -> str:
    head = "| Engine | Cards | Name | Last 4 | DOB | s/image | Errors |\n|---|---|---|---|---|---|---|\n"
    body = "".join(
        f"| {r['engine']} | {r['cards']} | {r['name_accuracy']:.0%} | {r['last4_accuracy']:.0%} | "
        f"{r['dob_accuracy']:.0%} | {r['mean_seconds']} | {r['errors']} |\n"
        for r in results
    )
    return head + body


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", default="paddleocr,paddleocr-vl")
    parser.add_argument("--cards", default=str(DEFAULT_CARDS))
    parser.add_argument("--det-model", default=None, help="PaddleOCR text detection model name")
    parser.add_argument("--rec-model", default=None, help="PaddleOCR text recognition model name")
    args = parser.parse_args()
    if args.det_model or args.rec_model:
        ENGINES["paddleocr"] = lambda: PaddleOCREngine(det_model=args.det_model, rec_model=args.rec_model)

    results = []
    for name in args.engines.split(","):
        name = name.strip()
        print(f"\n== {name} ==")
        try:
            result = run(name, Path(args.cards))
        except Exception as exc:  # an engine that cannot start is a result too
            print(f"   could not run: {exc}")
            continue
        for row in result["rows"]:
            flag = "ok " if row["name_ok"] and row["last4_ok"] else "MISS"
            print(f"   {flag} {row['card']:<26} {row['seconds']:>6.2f}s  read={row['read']}" + (f"  error={row['error']}" if row["error"] else ""))
        results.append(result)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "ocr_bench.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print("\n" + table(results))
