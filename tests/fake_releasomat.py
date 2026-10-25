"""A stand-in for Releasomat's integration API (ADR 0044): answers from saved fixtures (taken
from a real Releasomat) or from the test, and remembers every request. Tests never go online."""

import io
import json
import urllib.error

from tests.conftest import FIXTURES

ONLINE = FIXTURES / "online"
URL = "http://192.168.1.10:8430"
KEY = "tagwerk-test-key-0123456789"


def saved(name: str) -> dict:
    return json.loads((ONLINE / f"releasomat_{name}.json").read_text(encoding="utf-8"))


class _Response(io.BytesIO):
    status = 200


class FakeReleasomat:
    """Use as ``monkeypatch.setattr(releasomat.urllib.request, "urlopen", fake)``.

    ``answers``: call name ("info", "files", "adopt", …) → a dict (answered with 200), an int
    (that HTTP error, with the matching saved error body), an exception to raise, or a function
    of the request's body returning one of those (to play Releasomat's side). A POST call
    without an answer of its own answers ok for every file sent.
    """

    ERRORS = {401: "wrong_key", 403: "integration_off"}
    OLD = {404: {"detail": "Not Found"}}  # FastAPI's own answer: a Releasomat without the API

    def __init__(self, **answers):
        self.answers = {"info": saved("info"), "files": saved("files"), **answers}
        self.requests = []  # urllib.request.Request objects

    def __call__(self, request, timeout):
        self.requests.append(request)
        call = request.full_url.rsplit("/", 1)[-1]
        answer = self.answers.get(call)
        if callable(answer) and not isinstance(answer, Exception):
            answer = answer(self.body(request))
        if answer is None and request.get_method() == "POST":
            answer = {"integration_api": 1, "files": [
                {"asked": f["path"], "ok": True, "changed": True, "id": f.get("id"),
                 "path": f["path"], "status": call}
                for f in self.body(request)["files"]
            ]}  # fmt: skip
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            found = saved(self.ERRORS[answer]) if answer in self.ERRORS else self.OLD.get(answer)
            body = json.dumps(found or {})
            raise urllib.error.HTTPError(
                request.full_url, answer, "error", {}, io.BytesIO(body.encode())
            )
        return _Response(json.dumps(answer).encode())

    @staticmethod
    def body(request) -> dict:
        return json.loads(request.data or b"{}")

    def calls(self) -> list[str]:
        return [r.full_url.rsplit("/", 1)[-1] for r in self.requests]

    def sent(self, call: str) -> list[dict]:
        """The bodies of every request to ``call``."""
        return [self.body(r) for r in self.requests if r.full_url.endswith(f"/{call}")]
