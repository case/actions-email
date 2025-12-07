#!/usr/bin/env python3
"""Send emails via Postmark or Resend APIs."""

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
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode("utf-8"))
            print("Email sent successfully via Resend")
            print(f"Response: {json.dumps(body)}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        error(f"Resend API error (HTTP {e.code}): {body}")


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
        body = e.read().decode("utf-8")
        error(f"Postmark API error (HTTP {e.code}): {body}")


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


if __name__ == "__main__":
    main()
