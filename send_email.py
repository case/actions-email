#!/usr/bin/env python3
"""Send emails via Postmark or Resend APIs."""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def get_env(name: str, required: bool = True) -> str:
    """Get environment variable, optionally required."""
    value = os.environ.get(name, "")
    if required and not value:
        error(f"Missing required environment variable: {name}")
    return value


def error(message: str) -> None:
    """Print GitHub Actions error and exit."""
    print(f"::error::{message}")
    sys.exit(1)


def _mask(value: str) -> str:
    """Mask a string, showing only the first 3 and last 3 characters."""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def _handle_http_error(provider: str, e: urllib.error.HTTPError, payload: dict) -> None:
    """Log detailed error info and exit."""
    raw_body = e.read().decode("utf-8")

    # Try to parse as JSON for structured error info
    try:
        error_json = json.loads(raw_body)
        body_str = json.dumps(error_json, indent=2)
    except (json.JSONDecodeError, ValueError):
        body_str = raw_body

    # Log everything useful for debugging
    print(f"::group::{provider} API Error Details")
    print(f"HTTP status: {e.code}")
    print(f"Response body:\n{body_str}")
    print(f"Response headers:\n{e.headers}")

    # Log the request payload with sensitive fields masked
    debug_payload = {}
    for key, value in payload.items():
        if isinstance(value, str) and ("@" in value or key.lower() in ("from", "to")):
            debug_payload[key] = _mask(value)
        else:
            debug_payload[key] = value
    print(f"Request payload:\n{json.dumps(debug_payload, indent=2)}")
    print("::endgroup::")

    error(f"{provider} API error (HTTP {e.code}): {body_str}")


def send_resend(from_addr: str, to_addr: str, subject: str, html_body: str, text_body: str) -> None:
    """Send email via Resend API."""
    api_key = get_env("RESEND_API_KEY")

    payload = {
        "from": from_addr,
        "to": to_addr,
        "subject": subject,
    }
    if html_body:
        payload["html"] = html_body
    if text_body:
        payload["text"] = text_body

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "resend-python:2.21.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode("utf-8"))
            print("Email sent successfully via Resend")
            print(f"Response: {json.dumps(body)}")
    except urllib.error.HTTPError as e:
        _handle_http_error("Resend", e, payload)


def send_postmark(from_addr: str, to_addr: str, subject: str, html_body: str, text_body: str) -> None:
    """Send email via Postmark API."""
    api_token = get_env("POSTMARK_API_TOKEN")

    payload = {
        "From": from_addr,
        "To": to_addr,
        "Subject": subject,
    }
    if html_body:
        payload["HtmlBody"] = html_body
    if text_body:
        payload["TextBody"] = text_body

    request = urllib.request.Request(
        "https://api.postmarkapp.com/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "X-Postmark-Server-Token": api_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode("utf-8"))
            print("Email sent successfully via Postmark")
            print(f"Response: {json.dumps(body)}")
    except urllib.error.HTTPError as e:
        _handle_http_error("Postmark", e, payload)


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
    parser.add_argument("--from", dest="from_addr", required=True, help="Sender email address")
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
