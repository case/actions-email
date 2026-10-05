"""Stands in for the network when EMAIL_STUB_RECORD is set.

Records the request send_email.py makes as JSON, then forwards it to
EMAIL_STUB_FORWARD_URL if set, or answers 200 itself.
"""

import email.message
import io
import json
import os
import urllib.request
import urllib.response


def _install(record_path: str) -> None:
    real_urlopen = urllib.request.urlopen

    def urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> urllib.response.addinfourl:
        headers = {k.lower(): v for k, v in request.header_items()}
        data = request.data
        record = {
            "url": request.full_url,
            "method": request.get_method(),
            "headers": headers,
            "body": json.loads(data) if isinstance(data, bytes) else None,
            "timeout": timeout,
        }
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)

        forward_url = os.environ.get("EMAIL_STUB_FORWARD_URL")
        if not forward_url:
            reply = email.message.Message()
            reply["Content-Type"] = "application/json"
            body = io.BytesIO(b'{"id": "stub"}')
            return urllib.response.addinfourl(body, reply, request.full_url, code=200)

        forwarded = urllib.request.Request(
            forward_url,
            data=request.data,
            headers=dict(request.header_items()),
            method=request.get_method(),
        )
        return real_urlopen(forwarded, timeout=timeout)

    urllib.request.urlopen = urlopen


_record_path = os.environ.get("EMAIL_STUB_RECORD")
if _record_path:
    _install(_record_path)
