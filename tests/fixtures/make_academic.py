"""
Synthetic marksheets and a transcript for tests and manual runs.

A CBSE-style 10th marksheet and a Tamil Nadu state-board-style 12th
marksheet as PNGs (the drawn lines embedded for the stub OCR engine), and a
university transcript as a text PDF. Fake people, fake numbers.

    uv run python -m tests.fixtures.make_academic [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent / "academic"


@dataclass
class Sheet:
    key: str
    type: str
    lines: list[str]
    expected: dict
    format: str = "png"           # png | pdf
    size: tuple[int, int] = (1400, 1000)
    extra: dict = field(default_factory=dict)


SHEETS: list[Sheet] = [
    Sheet(
        key="aarav_10th",
        type="marksheet_10",
        lines=[
            "CENTRAL BOARD OF SECONDARY EDUCATION",
            "SECONDARY SCHOOL EXAMINATION (CLASS X) 2019",
            "MARKS STATEMENT",
            "Roll No: 1234567",
            "Candidate's Name: AARAV MEHTA",
            "Mother's Name: PRIYA MEHTA",
            "Father's Name: RAJESH MEHTA",
            "Date of Birth: 12/03/2003",
            "School: DELHI PUBLIC SCHOOL, CHENNAI",
            "SUBJECT MARKS GRADE",
            "ENGLISH 091 A2",
            "HINDI 088 B1",
            "MATHEMATICS 095 A1",
            "SCIENCE 094 A1",
            "SOCIAL SCIENCE 092 A2",
            "Total: 460/500",
            "Percentage: 92.0%",
            "Result: PASS",
        ],
        expected={
            "detected_type": "marksheet_10", "full_name": "AARAV MEHTA", "father_name": "RAJESH MEHTA",
            "mother_name": "PRIYA MEHTA", "roll_last4": "4567", "dob": "2003-03-12", "year": 2019,
            "subjects": 5, "total_marks": 460.0, "max_total": 500.0, "percentage": 92.0,
            "percentage_source": "stated", "percentage_computed": 92.0, "result": "PASS",
            "board_contains": "central board of secondary education",
            "checks": {"document_type_matches": True, "percentage_matches_rows": True},
        },
    ),
    Sheet(
        key="aarav_12th",
        type="marksheet_12",
        lines=[
            "STATE BOARD OF SCHOOL EXAMINATIONS, TAMIL NADU",
            "HIGHER SECONDARY COURSE CERTIFICATE",
            "MARCH 2021",
            "Name of the Candidate: AARAV MEHTA",
            "Register No: 2101234",
            "Date of Birth: 12/03/2003",
            "SUBJECT MARKS",
            "LANGUAGE - TAMIL 085",
            "ENGLISH 089",
            "MATHEMATICS 097",
            "PHYSICS 091",
            "CHEMISTRY 088",
            "COMPUTER SCIENCE 096",
            "TOTAL 546 / 600",
            "RESULT: PASS",
        ],
        expected={
            "detected_type": "marksheet_12", "full_name": "AARAV MEHTA", "roll_last4": "1234",
            "dob": "2003-03-12", "year": 2021, "subjects": 6, "total_marks": 546.0, "max_total": 600.0,
            "percentage": 91.0, "percentage_source": "computed", "result": "PASS",
            "board_contains": "state board of school examinations",
            "checks": {"document_type_matches": True},
        },
    ),
    Sheet(
        key="aarav_transcript",
        type="transcript",
        format="pdf",
        lines=[
            "ANNA UNIVERSITY, CHENNAI",
            "CONSOLIDATED STATEMENT OF GRADES",
            "Name: AARAV MEHTA",
            "Register Number: 311521104001",
            "Degree & Branch: B.E. COMPUTER SCIENCE AND ENGINEERING",
            "Date of Birth: 12-03-2003",
            "Semester 1 SGPA: 8.2",
            "Semester 2 SGPA: 8.6",
            "Semester 3 SGPA: 8.4",
            "Semester 4 SGPA: 8.4",
            "CGPA: 8.40",
            "Month & Year of Passing: May 2026",
            "Result: PASS",
        ],
        expected={
            "detected_type": "transcript", "full_name": "AARAV MEHTA", "roll_last4": "4001",
            "dob": "2003-03-12", "year": 2026, "cgpa": 8.4, "sgpa": [8.2, 8.6, 8.4, 8.4], "result": "PASS",
            "institution_contains": "anna university",
            "checks": {"document_type_matches": True, "cgpa_matches_sgpa": True},
        },
    ),
    Sheet(
        key="sana_12th_inflated",
        type="marksheet_12",
        lines=[
            "CENTRAL BOARD OF SECONDARY EDUCATION",
            "SENIOR SCHOOL CERTIFICATE EXAMINATION (CLASS XII) 2020",
            "Roll No: 7654321",
            "Candidate's Name: SANA QURESHI",
            "Father's Name: IMRAN QURESHI",
            "Date of Birth: 25/11/2002",
            "ENGLISH CORE 082",
            "PHYSICS 078",
            "CHEMISTRY 075",
            "MATHEMATICS 088",
            "COMPUTER SCIENCE 090",
            "Percentage: 88.5%",
            "Result: PASS",
        ],
        expected={
            # The rows add up to 82.6%, not the 88.5% printed: the sheet itself is inconsistent.
            "detected_type": "marksheet_12", "full_name": "SANA QURESHI", "percentage": 88.5,
            "percentage_source": "stated", "percentage_computed": 82.6, "year": 2020,
            "checks": {"document_type_matches": True, "percentage_matches_rows": False},
        },
    ),
]


def render_png(sheet: Sheet, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

    width, height = sheet.size
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width, 60], fill=(60, 90, 160))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 30)
    except OSError:
        font = ImageFont.load_default(size=30)
    y = 90
    for line in sheet.lines:
        draw.text((60, y), line, fill="black", font=font)
        y += 46
    info = PngImagePlugin.PngInfo()
    info.add_text("ocr_lines", json.dumps(sheet.lines, ensure_ascii=False))
    image.save(path, pnginfo=info)


def render_pdf(sheet: Sheet, path: Path) -> None:
    from tests.fixtures.make_resumes import write_pdf

    write_pdf(path, sheet.lines)


def render_sheets(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written, manifest = [], {}
    for sheet in SHEETS:
        path = out_dir / f"{sheet.key}.{sheet.format}"
        (render_pdf if sheet.format == "pdf" else render_png)(sheet, path)
        written.append(path)
        manifest[path.name] = {"type": sheet.type, **sheet.expected}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    for written in render_sheets(Path(args.out)):
        print(f"  {written.name:<30} {written.stat().st_size:>7} bytes")
