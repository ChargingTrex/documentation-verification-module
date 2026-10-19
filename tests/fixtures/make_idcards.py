"""
Synthetic Aadhaar and PAN card images for tests and the OCR benchmark.

Fake people, fake numbers (the Aadhaar numbers do pass the Verhoeff check,
so the checksum path is exercised). Each PNG carries the exact lines it was
drawn with in an `ocr_lines` text chunk -- the stub engine reads that, the
real engines read the pixels -- and `manifest.json` records the expected
values for every card.

    uv run python -m tests.fixtures.make_idcards [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ocr import verhoeff

DEFAULT_OUT = Path(__file__).resolve().parent / "idcards"


def aadhaar_number(seed: str) -> str:
    """A Verhoeff-valid 12-digit number from an 11-digit seed."""
    assert len(seed) == 11 and seed.isdigit() and seed[0] != "0"
    return seed + verhoeff.check_digit(seed)


def spaced(number: str) -> str:
    return f"{number[:4]} {number[4:8]} {number[8:]}"


@dataclass
class Card:
    key: str
    type: str                 # aadhaar | pan
    lines: list[str]          # what is drawn, top to bottom
    expected: dict
    variant: str = "clean"    # clean | rotated | blurred
    size: tuple[int, int] = (1260, 700)
    extra: dict = field(default_factory=dict)


AARAV = aadhaar_number("23456789012")
SANA = aadhaar_number("34567890123")
KABIR = aadhaar_number("45678901234")


def aadhaar_front(key, name, hindi, dob_line, gender, number, variant="clean") -> Card:
    return Card(
        key=key,
        type="aadhaar",
        variant=variant,
        lines=[
            "GOVERNMENT OF INDIA",
            hindi,
            name,
            dob_line,
            gender,
            spaced(number),
            "Mera Aadhaar, Meri Pehchaan",
        ],
        expected={
            "full_name": name,
            "id_last4": number[-4:],
            "gender": {"MALE": "M", "FEMALE": "F"}[gender],
            "dob": None,
            "checks": {"aadhaar_number_found": True, "aadhaar_checksum": True},
        },
    )


CARDS: list[Card] = []

_c = aadhaar_front("aarav_aadhaar", "Aarav Mehta", "आरव मेहता", "DOB: 12/03/2003", "MALE", AARAV)
_c.expected["dob"] = "2003-03-12"
CARDS.append(_c)

_c = aadhaar_front("sana_aadhaar", "Sana Qureshi", "सना कुरैशी", "DOB: 25/11/2002", "FEMALE", SANA)
_c.expected["dob"] = "2002-11-25"
CARDS.append(_c)

_c = aadhaar_front("kabir_aadhaar", "Kabir Nair", "कबीर नायर", "Year of Birth: 2004", "MALE", KABIR, variant="rotated")
_c.expected["year_of_birth"] = 2004
CARDS.append(_c)

CARDS.append(
    Card(
        key="aarav_aadhaar_back",
        type="aadhaar",
        lines=[
            "Unique Identification Authority of India",
            "Address:",
            "S/O: Rajesh Mehta, 12 Gandhi Street,",
            "T Nagar, Chennai,",
            "Tamil Nadu - 600017",
            spaced(AARAV),
            "help@uidai.gov.in  www.uidai.gov.in  1947",
        ],
        expected={
            "full_name": None,
            "id_last4": AARAV[-4:],
            "address_pincode": "600017",
            "address_state": "Tamil Nadu",
            "checks": {"aadhaar_number_found": True, "aadhaar_checksum": True},
        },
    )
)

CARDS.append(
    Card(
        key="aarav_pan",
        type="pan",
        lines=[
            "INCOME TAX DEPARTMENT",
            "GOVT. OF INDIA",
            "Permanent Account Number Card",
            "ABCPM1234F",
            "Name",
            "AARAV MEHTA",
            "Father's Name",
            "RAJESH MEHTA",
            "Date of Birth",
            "12/03/2003",
        ],
        expected={
            "full_name": "AARAV MEHTA",
            "father_name": "RAJESH MEHTA",
            "id_last4": "234F",
            "dob": "2003-03-12",
            "checks": {"pan_format": True, "pan_individual": True},
        },
    )
)

CARDS.append(
    Card(
        key="sana_pan",
        type="pan",
        variant="blurred",
        lines=[
            "आयकर विभाग  INCOME TAX DEPARTMENT",
            "भारत सरकार  GOVT. OF INDIA",
            "Permanent Account Number Card",
            "ABCPQ5678K",
            "नाम / Name: SANA QURESHI",
            "पिता का नाम / Father's Name: IMRAN QURESHI",
            "जन्म की तारीख / Date of Birth: 25/11/2002",
        ],
        expected={
            "full_name": "SANA QURESHI",
            "father_name": "IMRAN QURESHI",
            "id_last4": "678K",
            "dob": "2002-11-25",
            "checks": {"pan_format": True, "pan_individual": True},
        },
    )
)

CARDS.append(
    Card(
        key="kabir_pan_old",
        type="pan",
        lines=[
            "INCOME TAX DEPARTMENT",
            "GOVT. OF INDIA",
            "KABIR NAIR",
            "SURESH NAIR",
            "04/07/2004",
            "Permanent Account Number",
            "ABCPN9012D",
            "Signature",
        ],
        expected={
            "full_name": "KABIR NAIR",
            "father_name": "SURESH NAIR",
            "id_last4": "012D",
            "dob": "2004-07-04",
            "checks": {"pan_format": True, "pan_individual": True},
        },
    )
)


def render(card: Card, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, PngImagePlugin

    width, height = card.size
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    accent = (200, 60, 60) if card.type == "aadhaar" else (40, 70, 160)
    draw.rectangle([0, 0, width, 70], fill=accent)
    draw.rectangle([40, 120, 260, 400], outline=(120, 120, 120), width=3)  # photo box

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 36)
    except OSError:
        font = ImageFont.load_default(size=36)

    y = 100
    for line in card.lines:
        is_latin = all(ord(ch) < 0x0900 or ord(ch) > 0x097F for ch in line)
        draw.text((300, y), line, fill="black" if is_latin else (80, 80, 80), font=font)
        y += 60

    if card.variant == "rotated":
        image = image.rotate(3, expand=True, fillcolor="white")
    elif card.variant == "blurred":
        image = image.filter(ImageFilter.GaussianBlur(1.2))

    info = PngImagePlugin.PngInfo()
    info.add_text("ocr_lines", json.dumps(card.lines, ensure_ascii=False))
    image.save(path, pnginfo=info)


def render_cards(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    manifest = {}
    for card in CARDS:
        path = out_dir / f"{card.key}.png"
        render(card, path)
        written.append(path)
        manifest[path.name] = {"type": card.type, "variant": card.variant, **card.expected}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    for written in render_cards(Path(args.out)):
        print(f"  {written.name:<28} {written.stat().st_size:>7} bytes")
