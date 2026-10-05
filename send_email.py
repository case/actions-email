#!/usr/bin/env python3
"""Send emails via Postmark or Resend APIs."""

import argparse
import email.utils
import http.client
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.request
from typing import NoReturn

# Seconds allowed for each connect or read, and for the whole send.
TIMEOUT = 30

RESEND_URL = "https://api.resend.com/emails"
POSTMARK_URL = "https://api.postmarkapp.com/email"

# Request fields whose content is replaced by its length in error output.
BODY_FIELDS = ("html", "text", "HtmlBody", "TextBody")


def get_env(name: str, required: bool = True) -> str:
    """Get environment variable, optionally required."""
    value = os.environ.get(name, "")
    if required and not value:
        error(f"Missing required environment variable: {name}")
    return value


def get_credential(name: str) -> str:
    """Get a required credential that is safe to put in an HTTP header."""
    value = get_env(name)
    if not (value.isascii() and value.isprintable()) or any(c.isspace() for c in value):
        error(f"{name} contains whitespace, control or non-ASCII characters")
    return value


def error(message: str) -> NoReturn:
    """Print a GitHub Actions error annotation and exit."""
    # Workflow command data must escape these, or a newline ends the annotation.
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error::{escaped}", flush=True)
    sys.exit(1)


def _mask(value: str) -> str:
    """Mask a string, showing only the first 3 and last 3 characters."""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def _format_body(raw: bytes) -> str:
    """Pretty-print a response body if it is JSON, else return it as text."""
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (ValueError, RecursionError):
        return text


def _escaped_forms(value: str) -> list[str]:
    """Return value as it may appear in output: raw, and JSON-escaped with and without ASCII escapes."""
    forms = {
        value,
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
    }
    return sorted(forms, key=len, reverse=True)


def _redact(text: str, credential: str, payload: dict) -> str:
    """Mask the credential and the from and to addresses wherever the provider echoed them."""
    for form in _escaped_forms(credential):
        text = text.replace(form, "***")
    values = [v for k, v in payload.items() if k.lower() in ("from", "to")]
    # The whole value, plus each bare address, since a provider may echo only that.
    candidates = set(values) | {addr for _, addr in email.utils.getaddresses(values)}
    for candidate in sorted(
        {c.strip() for c in candidates if c.strip()}, key=len, reverse=True
    ):
        for form in _escaped_forms(candidate):
            text = text.replace(form, _mask(candidate))
    return text


def _handle_http_error(
    provider: str,
    status: int,
    headers: object,
    raw_body: bytes,
    payload: dict,
    credential: str,
) -> NoReturn:
    """Log detailed error info and exit."""
    body_str = _redact(_format_body(raw_body), credential, payload)
    headers_str = _redact(str(headers), credential, payload)

    debug_payload = {}
    for key, value in payload.items():
        if key in BODY_FIELDS:
            debug_payload[key] = f"<{len(value)} characters>"
        elif isinstance(value, str) and ("@" in value or key.lower() in ("from", "to")):
            debug_payload[key] = _mask(value)
        else:
            debug_payload[key] = value

    # The provider's response is untrusted, so the runner must not act on its lines.
    token = secrets.token_hex(16)
    print(f"::group::{provider} API Error Details")
    print(f"::stop-commands::{token}")
    print(f"HTTP status: {status}")
    print(f"Response body:\n{body_str}")
    print(f"Response headers:\n{headers_str}")
    print(f"Request payload:\n{json.dumps(debug_payload, indent=2)}")
    print(f"::{token}::")
    print("::endgroup::")

    error(f"{provider} API error (HTTP {status}): {body_str}")


def _post(
    provider: str, url: str, headers: dict[str, str], payload: dict, credential: str
) -> None:
    """POST payload as JSON, then exit with an error unless the provider accepted it."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    outcome: dict = {}

    def send() -> None:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                outcome["body"] = response.read()
        except urllib.error.HTTPError as e:
            try:
                raw = e.read()
            except (OSError, http.client.HTTPException):
                raw = b""
            outcome["http_error"] = (e.code, e.headers, raw)
        except (OSError, http.client.HTTPException) as e:
            outcome["failure"] = e

    # urlopen's timeout bounds each socket operation; join() bounds the whole send.
    worker = threading.Thread(target=send, daemon=True)
    worker.start()
    worker.join(TIMEOUT)

    if worker.is_alive():
        error(f"{provider} request timed out after {TIMEOUT:g} seconds")
    if "http_error" in outcome:
        status, response_headers, raw_body = outcome["http_error"]
        _handle_http_error(
            provider, status, response_headers, raw_body, payload, credential
        )
    if "failure" in outcome:
        failure = outcome["failure"]
        reason = (
            failure.reason if isinstance(failure, urllib.error.URLError) else failure
        )
        if isinstance(reason, TimeoutError):
            error(f"{provider} request timed out after {TIMEOUT:g} seconds")
        error(f"{provider} request failed: {str(reason) or type(reason).__name__}")
    if "body" not in outcome:
        error(f"{provider} request failed unexpectedly")

    print(f"Email sent successfully via {provider}")
    # json.dumps keeps the response on one line, so it cannot start a workflow command.
    response_text = outcome["body"].decode("utf-8", errors="replace")
    try:
        response_line = json.dumps(json.loads(response_text))
    except (ValueError, RecursionError):
        response_line = json.dumps(response_text)
    print(f"Response: {response_line}")


def send_resend(
    from_addr: str, to_addr: str, subject: str, html_body: str, text_body: str
) -> None:
    """Send email via Resend API."""
    api_key = get_credential("RESEND_API_KEY")

    payload = {
        "from": from_addr,
        "to": to_addr,
        "subject": subject,
    }
    if html_body:
        payload["html"] = html_body
    if text_body:
        payload["text"] = text_body

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "resend-python:2.21.0",
    }
    _post("Resend", RESEND_URL, headers, payload, api_key)


def send_postmark(
    from_addr: str, to_addr: str, subject: str, html_body: str, text_body: str
) -> None:
    """Send email via Postmark API."""
    api_token = get_credential("POSTMARK_API_TOKEN")

    payload = {
        "From": from_addr,
        "To": to_addr,
        "Subject": subject,
    }
    if html_body:
        payload["HtmlBody"] = html_body
    if text_body:
        payload["TextBody"] = text_body

    headers = {
        "X-Postmark-Server-Token": api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    _post("Postmark", POSTMARK_URL, headers, payload, api_token)


def main() -> None:
    # Get inputs from environment
    provider = get_env("INPUT_PROVIDER")
    from_addr = get_env("EMAIL_FROM")
    to_addr = get_env("EMAIL_TO")
    subject = get_env("INPUT_SUBJECT")
    html_body = get_env("INPUT_BODY_HTML", required=False)
    text_body = get_env("INPUT_BODY_TEXT", required=False)

    # Validate provider
    if provider not in ("resend", "postmark"):
        error(f"Invalid provider '{provider}'. Must be 'resend' or 'postmark'.")

    # Validate body
    if not html_body and not text_body:
        error("At least one of html_body or text_body must be provided.")

    # Send email
    if provider == "resend":
        send_resend(from_addr, to_addr, subject, html_body, text_body)
    else:
        send_postmark(from_addr, to_addr, subject, html_body, text_body)


def test() -> None:
    """Send a test email via Resend from the command line."""
    parser = argparse.ArgumentParser(description="Send a test email via Resend")
    parser.add_argument("--test", action="store_true", required=True)
    parser.add_argument(
        "--from", dest="from_addr", required=True, help="Sender email address"
    )
    parser.add_argument("--to", required=True, help="Recipient email address")
    args = parser.parse_args()

    print(f"Sending test email from {args.from_addr} to {args.to}...")
    send_resend(
        from_addr=args.from_addr,
        to_addr=args.to,
        subject="actions-email test",
        html_body="",
        text_body="This is a test email from actions-email.",
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and "--test" in sys.argv:
        test()
    else:
        main()
