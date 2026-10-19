"""
The Verhoeff checksum Aadhaar numbers carry.

The twelfth digit of an Aadhaar number is a Verhoeff check digit over the
first eleven. A number that fails it is an OCR misread (or not an Aadhaar
number at all) -- useful because a card photo is rarely read perfectly.
"""

from __future__ import annotations

_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def validate(number: str) -> bool:
    """True when the digit string's last digit is its Verhoeff check digit."""
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        return False
    check = 0
    for index, digit in enumerate(reversed(digits)):
        check = _D[check][_P[index % 8][int(digit)]]
    return check == 0


def check_digit(number: str) -> str:
    """The check digit to append to `number`."""
    digits = "".join(ch for ch in number if ch.isdigit())
    check = 0
    for index, digit in enumerate(reversed(digits)):
        check = _D[check][_P[(index + 1) % 8][int(digit)]]
    return str(_INV[check])
