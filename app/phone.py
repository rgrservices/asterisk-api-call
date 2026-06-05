import re
from typing import Final

_E164_BODY: Final[re.Pattern[str]] = re.compile(r"^[1-9]\d{7,14}$")
_BR_CC: Final[str] = "55"


def normalize_e164_input(raw: str) -> str:
    s = raw.strip().replace(" ", "")
    if s.startswith("+"):
        s = s[1:]
    if not s.isdigit():
        raise ValueError("to_number must contain only digits (optional leading +)")
    return s


def validate_e164(digits: str) -> None:
    if not _E164_BODY.match(digits):
        raise ValueError(
            "to_number must be E.164: 8–15 digits, country code 1–3 digits (no leading 0)"
        )


def to_trunk_dial_string(e164_digits: str, dial_prefix: str) -> str:
    if len(dial_prefix) != 4 or not dial_prefix.isdigit():
        raise ValueError("dial_prefix must be exactly 4 digits")

    if not e164_digits.startswith(_BR_CC):
        raise ValueError(
            f"unsupported country code: only {_BR_CC} (Brazil) is supported in this phase"
        )

    national = e164_digits[len(_BR_CC) :]
    if not national:
        raise ValueError("invalid number after removing country code")

    return f"{dial_prefix}{national}"
