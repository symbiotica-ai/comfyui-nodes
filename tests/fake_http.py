# ABOUTME: A requests-shaped double for the Modal and RNP transports — answers
# ABOUTME: from a scripted queue and records every call for assertions.
import json


class Response:
    def __init__(self, status_code, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (
            json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeHttp:
    """Answers in order; each call is recorded as (method, url, kwargs)."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if not self.queue:
            raise AssertionError(f"unexpected {method} {url}")
        return self.queue.pop(0)

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)
