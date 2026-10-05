"""Tests send_email.py and action.yml. Run with bin/test."""

import http.server
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from email_request import POSTMARK_URL, RESEND_URL, load_record, problems

REPO = Path(__file__).resolve().parent.parent
STUB_DIR = REPO / "test" / "stub"
SEND = REPO / "send_email.py"
# Above send_email.py's own 30 second deadline, so a harness kill never masks it.
HARNESS_TIMEOUT = 60
# Deadline tests lower send_email.TIMEOUT to this, so they finish in seconds.
SHORT_TIMEOUT = 1

RESEND_KEY = "re_test_key_0123456789"
POSTMARK_TOKEN = "pm-test-token-0123456789"
FROM = "sender@example.com"
TO = "recipient@example.com"

RESEND = {
    "INPUT_PROVIDER": "resend",
    "EMAIL_FROM": FROM,
    "EMAIL_TO": TO,
    "INPUT_SUBJECT": "subject",
    "INPUT_BODY_TEXT": "text body",
    "RESEND_API_KEY": RESEND_KEY,
}
POSTMARK = {
    **RESEND,
    "INPUT_PROVIDER": "postmark",
    "POSTMARK_API_TOKEN": POSTMARK_TOKEN,
}
del POSTMARK["RESEND_API_KEY"]

SCRUBBED_PREFIXES = ("RESEND_", "POSTMARK_", "EMAIL_", "INPUT_", "PYTHON")
PROXY_VARS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}


def run_send(
    record: Path,
    inputs: dict[str, str],
    forward_url: str | None = None,
    deadline: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Runs send_email.py with the stub urlopen loaded and only the given inputs set.
    With deadline, lowers send_email.TIMEOUT to it first."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(SCRUBBED_PREFIXES) and k.lower() not in PROXY_VARS
    }
    env.update(inputs)
    env["PYTHONPATH"] = str(STUB_DIR)
    env["EMAIL_STUB_RECORD"] = str(record)
    # A request that bypasses the stub fails on a closed local port, never the internet.
    env["HTTPS_PROXY"] = env["https_proxy"] = "http://127.0.0.1:9"
    if forward_url:
        env["EMAIL_STUB_FORWARD_URL"] = forward_url

    if deadline is None:
        argv = [sys.executable, str(SEND)]
    else:
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import send_email; "
            "send_email.TIMEOUT = float(sys.argv[2]); send_email.main()"
        )
        argv = [sys.executable, "-c", code, str(REPO), str(deadline)]
    return subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=HARNESS_TIMEOUT,
        check=False,
    )


@contextmanager
def fake_provider(
    status: int = 200, body: bytes = b"{}", mode: str = "reply"
) -> Generator[str, None, None]:
    """Serves POSTs on 127.0.0.1 and yields the URL. mode is "reply" (status and body),
    "hang" (never answers) or "drip" (headers, then one byte every 0.2 seconds)."""
    release = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                if mode == "hang":
                    release.wait()
                    return
                if mode == "drip":
                    self.send_response(200)
                    self.send_header("Content-Length", "100000")
                    self.end_headers()
                    while not release.wait(0.2):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                    return
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                # The client gave up first, which is what the deadline tests want.
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        release.set()
        server.shutdown()
        thread.join()
        server.server_close()


def closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/"


def commands_outside_stop_blocks(stdout: str) -> list[str]:
    """Returns the workflow commands the runner would act on, skipping stop-commands blocks."""
    commands = []
    resume = None
    for line in stdout.splitlines():
        stripped = line.lstrip()
        if resume is not None:
            if stripped == resume:
                resume = None
            continue
        match = re.match(r"::stop-commands::(.+)$", stripped)
        if match:
            resume = f"::{match.group(1)}::"
        elif stripped.startswith("::"):
            commands.append(stripped)
    return commands


class ActionTest(unittest.TestCase):
    def test_action_yml_has_no_expression_in_run(self) -> None:
        # An expression in run: is spliced into the script text before bash parses it.
        lines = (REPO / "action.yml").read_text(encoding="utf-8").splitlines()
        starts = [i for i, line in enumerate(lines) if re.match(r"\s*run:", line)]
        self.assertTrue(starts, "action.yml has no run: line")
        after_run = lines[starts[0] :]
        self.assertFalse(
            any("${{" in line for line in after_run),
            "action.yml has a ${{ }} expression inside a run: block",
        )

    def test_action_yml_quotes_the_script_path(self) -> None:
        text = (REPO / "action.yml").read_text(encoding="utf-8")
        self.assertIn('python3 "$GITHUB_ACTION_PATH/send_email.py"', text)


class SendTestCase(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.record = self.scratch / "request.json"

    def assert_failed_cleanly(self, result: subprocess.CompletedProcess[str]) -> None:
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, "send_email.py exited 0")
        self.assertIn("::error::", result.stdout, output)
        self.assertNotIn("Traceback", output)

    def assert_rejected_before_request(
        self, result: subprocess.CompletedProcess[str]
    ) -> None:
        self.assert_failed_cleanly(result)
        self.assertFalse(self.record.exists(), "a request was made")


class PayloadTest(SendTestCase):
    def test_resend_payload(self) -> None:
        inputs = {**RESEND, "INPUT_BODY_HTML": "<p>html</p>"}

        result = run_send(self.record, inputs)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = load_record(str(self.record))
        expected = {
            "from": FROM,
            "to": TO,
            "subject": "subject",
            "html": "<p>html</p>",
            "text": "text body",
        }
        self.assertEqual(problems(record, RESEND_URL, expected), [])
        self.assertEqual(record["headers"]["authorization"], f"Bearer {RESEND_KEY}")
        self.assertEqual(record["headers"]["content-type"], "application/json")

    def test_postmark_payload(self) -> None:
        inputs = {**POSTMARK, "INPUT_BODY_HTML": "<p>html</p>"}

        result = run_send(self.record, inputs)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = load_record(str(self.record))
        expected = {
            "From": FROM,
            "To": TO,
            "Subject": "subject",
            "HtmlBody": "<p>html</p>",
            "TextBody": "text body",
        }
        self.assertEqual(problems(record, POSTMARK_URL, expected), [])
        self.assertEqual(record["headers"]["x-postmark-server-token"], POSTMARK_TOKEN)
        self.assertEqual(record["headers"]["accept"], "application/json")

    def test_empty_body_field_is_omitted(self) -> None:
        result = run_send(self.record, RESEND)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body = load_record(str(self.record))["body"]
        self.assertNotIn("html", body)
        self.assertEqual(body["text"], "text body")

    def test_hostile_inputs_arrive_verbatim(self) -> None:
        canary = self.scratch / "pwned"
        subject = (
            f'it\'s "quoted" $HOME `touch {canary}` $(touch {canary}) '
            f"'; touch {canary}; ' %0A ::warning::subject ünï 🙂"
        )
        body = "line one\nline two & x=y @/etc/passwd <x> \\ \r\n::warning::body"
        for provider, inputs, url, keys in (
            ("resend", RESEND, RESEND_URL, ("from", "to", "subject", "html", "text")),
            (
                "postmark",
                POSTMARK,
                POSTMARK_URL,
                ("From", "To", "Subject", "HtmlBody", "TextBody"),
            ),
        ):
            with self.subTest(provider=provider):
                hostile = {
                    **inputs,
                    "INPUT_SUBJECT": subject,
                    "INPUT_BODY_HTML": body,
                    "INPUT_BODY_TEXT": body,
                }

                result = run_send(self.record, hostile)

                self.assertFalse(canary.exists(), "an input was executed as shell")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                expected = dict(zip(keys, (FROM, TO, subject, body, body)))
                record = load_record(str(self.record))
                self.assertEqual(problems(record, url, expected), [])


class RejectsBeforeRequestTest(SendTestCase):
    def test_missing_or_empty_input(self) -> None:
        cases = [(RESEND, var) for var in RESEND] + [(POSTMARK, "POSTMARK_API_TOKEN")]
        for inputs, var in cases:
            if var == "INPUT_BODY_TEXT":
                continue  # optional on its own; see test_both_bodies_empty
            for mode in ("empty", "unset"):
                with self.subTest(
                    provider=inputs["INPUT_PROVIDER"], var=var, mode=mode
                ):
                    changed = dict(inputs)
                    if mode == "empty":
                        changed[var] = ""
                    else:
                        del changed[var]

                    result = run_send(self.record, changed)

                    self.assert_rejected_before_request(result)

    def test_both_bodies_empty(self) -> None:
        inputs = {**RESEND, "INPUT_BODY_TEXT": "", "INPUT_BODY_HTML": ""}

        self.assert_rejected_before_request(run_send(self.record, inputs))

    def test_invalid_provider(self) -> None:
        for provider in ("smtp", "Resend", "resend "):
            with self.subTest(provider=provider):
                inputs = {**RESEND, "INPUT_PROVIDER": provider}

                self.assert_rejected_before_request(run_send(self.record, inputs))

    def test_malformed_credential_is_rejected_without_echoing_it(self) -> None:
        for bad in (
            "re_secret\r\nX-Evil: 1",
            "re_secret\n",
            "re_sëcret",
            "re secret",
        ):
            for inputs, var in (
                (RESEND, "RESEND_API_KEY"),
                (POSTMARK, "POSTMARK_API_TOKEN"),
            ):
                with self.subTest(var=var, credential=bad):
                    result = run_send(self.record, {**inputs, var: bad})

                    self.assert_rejected_before_request(result)
                    self.assertNotIn("secret", result.stdout + result.stderr)


class ProviderResponseTest(SendTestCase):
    def test_http_error_fails_with_body_and_hides_secrets(self) -> None:
        for status in (400, 422, 500):
            for inputs, secret in ((RESEND, RESEND_KEY), (POSTMARK, POSTMARK_TOKEN)):
                provider = inputs["INPUT_PROVIDER"]
                message = f"fake error {status}: '{FROM}' to {TO} with {secret}"
                error_body = json.dumps({"message": message}).encode()
                body = {**inputs, "INPUT_BODY_HTML": "<p>private html</p>"}
                body["INPUT_BODY_TEXT"] = "private text"
                # Display-name form, so the provider's echo is only part of the input.
                body["EMAIL_FROM"] = f"Sender Name <{FROM}>"
                with (
                    self.subTest(provider=provider, status=status),
                    fake_provider(status, error_body) as url,
                ):
                    result = run_send(self.record, body, forward_url=url)

                    output = result.stdout + result.stderr
                    self.assert_failed_cleanly(result)
                    self.assertIn(f"fake error {status}", output)
                    self.assertIn(f"HTTP {status}", output)
                    for hidden in (secret, FROM, TO, "private html", "private text"):
                        self.assertNotIn(hidden, output)

    def test_redaction_survives_json_escaping(self) -> None:
        # JSON escapes the quote and backslash, so the echo differs from the input.
        quoted_to = '"quoted"@example.com'
        key = 're_"secret\\key'
        inputs = {**RESEND, "EMAIL_TO": quoted_to, "RESEND_API_KEY": key}
        message = f"rejected {quoted_to} with {key}"
        error_body = json.dumps({"message": message}).encode()
        with fake_provider(422, error_body) as url:
            result = run_send(self.record, inputs, forward_url=url)

        output = result.stdout + result.stderr
        self.assert_failed_cleanly(result)
        for hidden in ("quoted", "secret"):
            self.assertNotIn(hidden, output)

    def test_hostile_error_body_cannot_issue_workflow_commands(self) -> None:
        error_body = b"line one\n::warning::injected\n%0A::add-mask::x\r\n"
        with fake_provider(400, error_body) as url:
            result = run_send(self.record, RESEND, forward_url=url)

        self.assert_failed_cleanly(result)
        commands = commands_outside_stop_blocks(result.stdout)
        self.assertEqual(
            [c for c in commands if not c.startswith(("::group::", "::endgroup::"))],
            [c for c in commands if c.startswith("::error::")],
            "a workflow command other than ::error:: reached the runner",
        )
        errors = [c for c in commands if c.startswith("::error::")]
        self.assertEqual(len(errors), 1, result.stdout)
        self.assertIn("line one%0A::warning::injected", errors[0])

    def test_deeply_nested_error_body_fails_cleanly(self) -> None:
        nested = b"[" * 100_000 + b"]" * 100_000
        with fake_provider(400, nested) as url:
            result = run_send(self.record, RESEND, forward_url=url)

        self.assert_failed_cleanly(result)
        self.assertIn("HTTP 400", result.stdout)

    def test_success_with_unparseable_body_still_succeeds(self) -> None:
        nested = b"[" * 100_000 + b"]" * 100_000
        for body in (
            b"not json",
            b"\xff\xfe not utf-8",
            b"ok\n::warning::injected\n",
            nested,
        ):
            with self.subTest(body=body[:40]), fake_provider(200, body) as url:
                result = run_send(self.record, RESEND, forward_url=url)

                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertNotIn("Traceback", output)
                self.assertEqual(commands_outside_stop_blocks(result.stdout), [])


class NetworkFailureTest(SendTestCase):
    def assert_timed_out_quickly(self, mode: str) -> None:
        with fake_provider(mode=mode) as url:
            start = time.monotonic()
            result = run_send(
                self.record, RESEND, forward_url=url, deadline=SHORT_TIMEOUT
            )
            elapsed = time.monotonic() - start

        self.assert_failed_cleanly(result)
        self.assertIn("timed out", result.stdout)
        # Startup and teardown take well under 3 seconds; a 10x deadline would take 10.
        self.assertLess(elapsed, SHORT_TIMEOUT + 3, "the deadline did not hold")

    def test_unanswered_request_times_out(self) -> None:
        self.assert_timed_out_quickly("hang")

    def test_slow_drip_response_hits_the_total_deadline(self) -> None:
        # Each byte arrives within the per-read timeout, so only a total deadline stops it.
        self.assert_timed_out_quickly("drip")

    def test_requested_timeout_is_30_seconds(self) -> None:
        for inputs in (RESEND, POSTMARK):
            with self.subTest(provider=inputs["INPUT_PROVIDER"]):
                result = run_send(self.record, inputs)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(load_record(str(self.record))["timeout"], 30)

    def test_connection_refused(self) -> None:
        result = run_send(self.record, RESEND, forward_url=closed_port_url())

        self.assert_failed_cleanly(result)
        self.assertIn("request failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
