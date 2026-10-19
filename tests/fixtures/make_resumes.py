"""
Render the reference resumes in `samples.py` into real PDF and DOCX files,
so the file-parsing path is exercised against actual binaries rather than
against strings.

    uv run python -m tests.fixtures.make_resumes [--out DIR]

The tests render them into a temp dir; running this by hand refreshes the
committed copies under tests/fixtures/resumes/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.fixtures.samples import SAMPLE_JOB_DESCRIPTION, SAMPLE_RESUMES

DEFAULT_OUT = Path(__file__).resolve().parent / "resumes"


def write_pdf(path: Path, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    width, height = A4
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setFont("Helvetica", 10.5)

    y = height - 60
    for line in lines:
        if y < 60:  # new page
            pdf.showPage()
            pdf.setFont("Helvetica", 10.5)
            y = height - 60
        pdf.drawString(56, y, line)
        y -= 15
    pdf.save()


def write_docx(path: Path, lines: list[str]) -> None:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))


def render_samples(out_dir: Path) -> list[Path]:
    """Write every sample resume into `out_dir`. Returns the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    for sample in SAMPLE_RESUMES:
        path = out_dir / sample.filename
        if sample.format == "pdf":
            write_pdf(path, list(sample.lines))
        else:
            write_docx(path, list(sample.lines))
        written.append(path)

    (out_dir / "job_description.txt").write_text(SAMPLE_JOB_DESCRIPTION, encoding="utf-8")

    # The hand-checked reference, in a form a human can diff against.
    reference = {
        sample.filename: {
            "experience_years": sample.expected_experience_years,
            "education_levels": sorted(sample.expected_education_levels),
            "relevant_to_job_description": sample.relevant,
        }
        for sample in SAMPLE_RESUMES
    }
    (out_dir / "reference.json").write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    for written in render_samples(Path(args.out)):
        print(f"  {written.name:<36} {written.stat().st_size:>7} bytes")
