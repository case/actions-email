"""Reads the request the stub urlopen recorded and checks what send_email.py sent."""

import json

RESEND_URL = "https://api.resend.com/emails"
POSTMARK_URL = "https://api.postmarkapp.com/email"
TIMEOUT = 30


def load_record(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def problems(record: dict, url: str, expected_body: dict[str, str]) -> list[str]:
    """Returns one message per mismatch, empty when the request is right."""
    found = []
    if record.get("url") != url:
        found.append(f"request went to {record.get('url')!r}, not {url!r}")
    if record.get("method") != "POST":
        found.append(f"request method was {record.get('method')!r}, not POST")
    if record.get("timeout") != TIMEOUT:
        found.append(f"urlopen timeout was {record.get('timeout')!r}, not {TIMEOUT}")
    body = record.get("body") or {}
    for name, value in expected_body.items():
        if body.get(name) != value:
            found.append(f"body field {name!r} did not arrive verbatim")
    extra = set(body) - set(expected_body)
    if extra:
        found.append(f"body has unexpected fields {sorted(extra)}")
    return found
