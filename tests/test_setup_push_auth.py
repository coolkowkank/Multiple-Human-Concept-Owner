"""Offline tests for tools/setup_push_auth.py: local fake GitHub API, no network."""
import json, os, stat, subprocess, sys, tempfile, threading, unittest, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "tools", "setup_push_auth.py")
TOKEN = "ghp_TESTTOKEN-do-not-leak-0123456789abcdef"

class FakeGitHub(BaseHTTPRequestHandler):
    def _send(self, code, obj, scopes="public_repo"):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-OAuth-Scopes", scopes)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        srv = self.server
        if self.path == "/user":
            if "Bearer " + TOKEN in (self.headers.get("Authorization") or ""):
                self._send(200, {"login": srv.login}, srv.scopes)
            else:
                self._send(401, {"message": "Bad credentials"}, "")
        elif self.path.startswith("/repos/"):
            if srv.repo_status == 200:
                self._send(200, {"full_name": "o/r", "permissions": {"push": srv.can_push}}, srv.scopes)
            else:
                self._send(404, {"message": "Not Found"}, srv.scopes)
        else:
            self._send(404, {}, "")
    def log_message(self, *a): pass

class SetupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.srv = HTTPServer(("127.0.0.1", 0), FakeGitHub)
        self.srv.login, self.srv.scopes, self.srv.repo_status, self.srv.can_push = "my-bot", "public_repo", 200, True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.tf = os.path.join(self.tmp, "token")
        with open(self.tf, "w") as f: f.write(TOKEN + "\n")
        os.chmod(self.tf, 0o600)
        self.clone = os.path.join(self.tmp, "clone")
        subprocess.run(["git", "init", "-q", self.clone], check=True)
        self.env = dict(os.environ, GITHUB_API_URL=f"http://127.0.0.1:{self.srv.server_port}")
    def run_setup(self, *extra):
        return subprocess.run([sys.executable, SCRIPT, "--repo", self.clone, "--owner", "o", "--name", "r",
                               "--token-file", self.tf] + list(extra),
                              capture_output=True, text=True, env=self.env)
    def helper_config(self):
        return subprocess.run(["git", "-C", self.clone, "config", "credential.helper"],
                              capture_output=True, text=True).stdout.strip()

    def test_success_verifies_identity_push_and_sets_helper(self):
        r = self.run_setup()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("'my-bot'", r.stdout)
        self.assertIn("push access to o/r verified", r.stdout)
        self.assertIn(self.tf, self.helper_config())
        self.assertNotIn("password=", self.helper_config().replace("password=$(cat", ""))

    def test_token_never_in_output(self):
        for mutate in (lambda s: None,
                       lambda s: setattr(s, "scopes", "repo workflow"),
                       lambda s: setattr(s, "can_push", False),
                       lambda s: setattr(s, "repo_status", 404)):
            mutate(self.srv)
            r = self.run_setup()
            self.assertNotIn(TOKEN, r.stdout + r.stderr)
            self.srv.login, self.srv.scopes, self.srv.repo_status, self.srv.can_push = "my-bot", "public_repo", 200, True

    def test_invalid_token_clear_error(self):
        with open(self.tf, "w") as f: f.write("ghp_WRONG")
        r = self.run_setup()
        self.assertEqual(r.returncode, 1)
        self.assertIn("401", r.stderr); self.assertIn("public_repo", r.stderr)

    def test_no_repo_access_clear_error(self):
        self.srv.repo_status = 404
        r = self.run_setup()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no access", r.stderr); self.assertIn("my-bot", r.stderr)

    def test_no_push_permission_clear_error(self):
        self.srv.can_push = False
        r = self.run_setup()
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO push permission", r.stderr)

    def test_world_readable_token_file_refused(self):
        os.chmod(self.tf, 0o644)
        r = self.run_setup()
        self.assertEqual(r.returncode, 1)
        self.assertIn("chmod 600", r.stderr)

    def test_broad_scope_warns_but_proceeds(self):
        self.srv.scopes = "repo, workflow"
        r = self.run_setup()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WARNING", r.stderr); self.assertIn("workflow", r.stderr)

if __name__ == "__main__":
    unittest.main()
