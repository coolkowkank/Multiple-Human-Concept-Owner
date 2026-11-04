"""Offline tests for tools/loop_runner.py: real git, scratch remotes, stub executor."""
import json, os, subprocess, sys, tempfile, unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO_ROOT, "tools", "loop_runner.py")

def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, check=True)

class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = self.tmp.name
        env = dict(os.environ)
        subprocess.run(["git", "init", "-q", "--bare", t + "/remote.git"], check=True)
        subprocess.run(["git", "init", "-q", t + "/seed"], check=True)
        git(t + "/seed", "config", "user.email", "op@example.test"); git(t + "/seed", "config", "user.name", "op")
        self.loop = {"state": "REVIEW_REQUESTED", "cycle": 1, "pinned_sha": "a" * 40,
                     "feedback_sha": None, "api_budget_total": 6, "api_used": 0}
        os.makedirs(t + "/seed/.team/review")
        json.dump(self.loop, open(t + "/seed/.team/review/LOOP.json", "w"))
        git(t + "/seed", "add", "-A"); git(t + "/seed", "commit", "-qm", "init")
        git(t + "/seed", "branch", "-M", "live/groq-dev-3")
        git(t + "/seed", "remote", "add", "origin", t + "/remote.git")
        git(t + "/seed", "push", "-qu", "origin", "live/groq-dev-3")
        git(t + "/seed", "checkout", "-qb", "review/groq-dev-3")
        git(t + "/seed", "push", "-qu", "origin", "review/groq-dev-3")
        subprocess.run(["git", "clone", "-q", t + "/remote.git", t + "/repo"], check=True)
        git(t + "/repo", "checkout", "-q", "live/groq-dev-3")
        git(t + "/repo", "config", "user.email", "op@example.test"); git(t + "/repo", "config", "user.name", "op")
        git(t + "/repo", "config", "commit.gpgsign", "false")
        subprocess.run(["git", "init", "-q", t + "/records"], check=True)
        git(t + "/records", "config", "user.email", "op@example.test"); git(t + "/records", "user", "x") if False else git(t + "/records", "config", "user.name", "op")
        self.t = t
        # stub executor: writes a 2-call transcript, makes a model-ish commit, pushes
        with open(t + "/stub_exec.py", "w") as f:
            f.write("""import json, os, subprocess, sys
repo, branch, att, task = sys.argv[1:5]
t = [{"ts": 1, "api_response": {}}, {"ts": 2, "api_response": {}}]
os.makedirs(repo + "/.team/attempts", exist_ok=True)
json.dump(t, open(f"{repo}/.team/attempts/{att}-transcript.json", "w"))
open(repo + "/change.txt", "w").write(task[:40] if False else "changed")
subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
subprocess.run(["git", "-C", repo, "commit", "-qm", "fix"], check=True)
subprocess.run(["git", "-C", repo, "push", "-q", "origin", "HEAD"], check=True)
""")
    def tearDown(self): self.tmp.cleanup()
    def run_once(self):
        env = dict(os.environ, RECORDS_DIR=self.t + "/records")
        return subprocess.run([sys.executable, RUNNER, "--repo", self.t + "/repo",
                               "--records", self.t + "/records", "--review-branch", "review/groq-dev-3",
                               "--budget", "6", "--once", "--executor", self.t + "/stub_exec.py"],
                              capture_output=True, text=True, env=env)
    def publish_feedback(self):
        t = self.t
        git(t + "/seed", "checkout", "-q", "review/groq-dev-3")
        open(t + "/seed/.team/review/FEEDBACK-c1.md", "w").write("VERDICT: FIX_NEEDED\nline two\n")
        git(t + "/seed", "add", "-A"); git(t + "/seed", "commit", "-qm", "feedback c1")
        git(t + "/seed", "push", "-q", "origin", "review/groq-dev-3")
        return git(t + "/seed", "rev-parse", "HEAD").stdout.strip()

    def test_no_feedback_no_change(self):
        r = self.run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no new feedback", r.stdout)
        loop = json.load(open(self.t + "/repo/.team/review/LOOP.json"))
        self.assertEqual(loop["state"], "REVIEW_REQUESTED")

    def test_new_feedback_runs_cycle_and_counts_calls(self):
        fb_sha = self.publish_feedback()
        r = self.run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("FIX_COMMITTED", r.stdout)
        git(self.t + "/repo", "fetch", "-q", "origin")
        loop = json.loads(git(self.t + "/repo", "show", "origin/live/groq-dev-3:.team/review/LOOP.json").stdout)
        self.assertEqual(loop["state"], "FIX_COMMITTED")
        self.assertEqual(loop["feedback_sha"], fb_sha)
        self.assertEqual(loop["api_used"], 2)
        # pinned_sha is the model's fix commit; the operator's LOOP.json commit sits on top
        fix_sha = git(self.t + "/repo", "log", "-1", "--format=%H", "--grep=^fix$", "origin/live/groq-dev-3").stdout.strip()
        self.assertEqual(loop["pinned_sha"], fix_sha)
        self.assertNotEqual(fix_sha, git(self.t + "/repo", "rev-parse", "origin/live/groq-dev-3").stdout.strip())
        task = open(self.t + "/repo/.team/review/task-c1.md").read()
        self.assertIn("VERBATIM", task); self.assertIn("VERDICT: FIX_NEEDED\nline two\n", task)

    def test_budget_exhausted_escalates(self):
        self.publish_feedback()
        loop = dict(self.loop, api_used=6)
        json.dump(loop, open(self.t + "/repo/.team/review/LOOP.json", "w"))
        git(self.t + "/repo", "add", "-A"); git(self.t + "/repo", "commit", "-qm", "used up"); git(self.t + "/repo", "push", "-q", "origin", "HEAD")
        r = self.run_once()
        self.assertIn("ESCALATE: budget exhausted", r.stdout)
        git(self.t + "/repo", "fetch", "-q", "origin")
        loop = json.loads(git(self.t + "/repo", "show", "origin/live/groq-dev-3:.team/review/LOOP.json").stdout)
        self.assertEqual(loop["state"], "ESCALATE")

    def test_terminal_state_noop(self):
        loop = dict(self.loop, state="VERIFIED")
        json.dump(loop, open(self.t + "/repo/.team/review/LOOP.json", "w"))
        r = self.run_once()
        self.assertIn("nothing to do", r.stdout)

if __name__ == "__main__":
    unittest.main()
