import json, os, shutil, tempfile, unittest
from unittest import mock
from launcher.adapters import HttpAdapter


class Resp:
    def __init__(self, body): self.body = json.dumps(body).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def run(body):
    d = tempfile.mkdtemp()
    log = os.path.join(d, "u.jsonl")
    os.environ["RID_KEY"] = "k"
    a = HttpAdapter("http://x.invalid", "m", "RID_KEY", usage_log=log)
    with mock.patch("urllib.request.urlopen", return_value=Resp(body)):
        a.complete("s", "p")
    rows = [json.loads(l) for l in open(log)]
    shutil.rmtree(d, True)
    return rows


class T(unittest.TestCase):
    base = {"choices": [{"message": {"content": '{"summary": "ok", "handoff": null}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2}}

    def test_records_provider_id_verbatim(self):
        self.assertEqual(run(dict(self.base, id="chatcmpl-abc"))[0]["response_id"], "chatcmpl-abc")

    def test_absent_or_nonstring_id_not_recorded(self):
        for bad in (None, "", 5):
            body = dict(self.base)
            if bad is not None: body["id"] = bad
            self.assertNotIn("response_id", run(body)[0])
