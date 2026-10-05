"""Fixture tests for mark_m2.py. Run: python3 -m unittest discover -s tests"""
import json, os, shutil, subprocess, sys, tempfile, textwrap, unittest

MARKER = os.path.join(os.path.dirname(__file__), "..", "mark_m2.py")
GOOD = textwrap.dedent("""\
    name: CI
    on:
      push:
        branches: [main]
      pull_request:
    permissions:
      contents: read
    defaults:
      run:
        shell: bash
    concurrency:
      group: ${{ github.workflow }}-${{ github.ref }}
      cancel-in-progress: true
    jobs:
      test:
        name: Tests
        runs-on: ubuntu-24.04
        steps:
          - uses: actions/checkout@v7
            with:
              persist-credentials: false
          - run: ./scripts/test.sh
    """)
RUNS = [
    {"head_branch": "main", "status": "completed", "conclusion": "success", "run_duration_ms": 21000},
    {"head_branch": "main", "status": "completed", "conclusion": "failure", "run_duration_ms": 9000},
]


def mark(workflow, files=None, runs=RUNS):
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, ".github", "workflows"))
        open(os.path.join(d, ".github", "workflows", "ci.yml"), "w").write(workflow)
        for name, body in (files or {}).items():
            open(os.path.join(d, name), "w").write(body)
        rj = os.path.join(d, "runs.json"); json.dump(runs, open(rj, "w"))
        out = subprocess.run([sys.executable, MARKER, "--path", d, "--runs-json", rj, "--json"],
                             capture_output=True, text=True).stdout
        return json.loads(out)
    finally:
        shutil.rmtree(d)


def block(report, name):
    return next(b for b in report["blocks"] if b["name"] == name)


class M2(unittest.TestCase):
    def test_good_scores_100(self):
        self.assertEqual(mark(GOOD)["score"], 100)

    def test_green_lie_without_pipefail_loses_hygiene(self):
        r = mark(GOOD.replace("defaults:\n  run:\n    shell: bash\n", ""))
        self.assertEqual(block(r, "hygiene")["points"], 0)
        self.assertIn("pipefail", block(r, "hygiene")["detail"])

    def test_shell_bash_on_the_step_is_enough(self):
        wf = GOOD.replace("defaults:\n  run:\n    shell: bash\n", "").replace(
            "      - run: ./scripts/test.sh", "      - run: ./scripts/test.sh\n        shell: bash")
        self.assertEqual(mark(wf)["score"], 100)

    def test_no_permissions_loses_trust(self):
        r = mark(GOOD.replace("permissions:\n  contents: read\n", ""))
        self.assertEqual(block(r, "triggers and trust")["points"], 0)

    def test_third_party_tag_pin_loses_trust(self):
        wf = GOOD.replace("      - run: ./scripts/test.sh",
                          "      - uses: tj-actions/changed-files@v46\n      - run: ./scripts/test.sh")
        r = mark(wf)
        self.assertEqual(block(r, "triggers and trust")["points"], 0)
        self.assertIn("commit SHA", block(r, "triggers and trust")["detail"])

    def test_third_party_sha_pin_is_fine(self):
        wf = GOOD.replace("      - run: ./scripts/test.sh",
                          "      - uses: tj-actions/changed-files@" + "a" * 40 + "\n      - run: ./scripts/test.sh")
        self.assertEqual(mark(wf)["score"], 100)

    def test_dependencies_without_cache_lose_hygiene(self):
        r = mark(GOOD, files={"requirements.txt": "requests==2.32.3\n"})
        self.assertEqual(block(r, "hygiene")["points"], 0)
        self.assertIn("requirements.txt", block(r, "hygiene")["detail"])

    def test_dependencies_with_cache_pass(self):
        wf = GOOD.replace("      - run: ./scripts/test.sh",
                          "      - uses: actions/setup-python@v7\n        with:\n          python-version: '3.12'\n          cache: pip\n      - run: ./scripts/test.sh")
        self.assertEqual(mark(wf, files={"requirements.txt": "requests==2.32.3\n"})["score"], 100)

    def test_never_red_loses_block(self):
        r = mark(GOOD, runs=[RUNS[0]])
        self.assertEqual(block(r, "has seen red")["points"], 0)

    def test_latest_main_red_loses_runs_block(self):
        r = mark(GOOD, runs=[RUNS[1], RUNS[0]])
        self.assertEqual(block(r, "runs your tests")["points"], 0)

    def test_floating_main_pin(self):
        r = mark(GOOD.replace("actions/checkout@v7", "actions/checkout@main"))
        self.assertEqual(block(r, "triggers and trust")["points"], 0)

    def test_only_push_trigger(self):
        r = mark(GOOD.replace("  pull_request:\n", ""))
        self.assertIn("pull_request", block(r, "triggers and trust")["detail"])

    def test_literal_token_is_a_gate(self):
        r = mark(GOOD + "# ghp_" + "A" * 36 + "\n")
        self.assertTrue(r["capped"])
        self.assertEqual(r["score"], 0)



def git(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


class AtDeadline(unittest.TestCase):
    """--at-deadline: a push or a run after the deadline changes nothing."""

    def repo_with_late_commit(self, on_time, late):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, ".github", "workflows"))
        wf = os.path.join(d, ".github", "workflows", "ci.yml")
        open(wf, "w").write(on_time)
        git(d, "init", "-q", "-b", "main")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "on time", date="2026-10-11T20:00:00+05:00")
        open(wf, "w").write(late)
        git(d, "commit", "-q", "-am", "late", date="2026-10-12T09:00:00+05:00")
        return d

    def run_marker(self, path, runs, deadline=True):
        fd, rj = tempfile.mkstemp(suffix="-runs.json")
        with os.fdopen(fd, "w") as fh:
            json.dump(runs, fh)
        self.addCleanup(lambda: os.path.exists(rj) and os.remove(rj))
        args = [sys.executable, MARKER, "--path", path, "--runs-json", rj, "--json"]
        if deadline:
            args.append("--at-deadline")
        out = subprocess.run(args, capture_output=True, text=True).stdout
        return json.loads(out)

    def test_late_push_does_not_change_the_files_marked(self):
        late = GOOD.replace("actions/checkout@v7", "actions/checkout@main")
        repo = self.repo_with_late_commit(GOOD, late)
        runs = [dict(r, created_at="2026-10-11T14:00:00Z") for r in RUNS]
        r = self.run_marker(repo, runs)
        self.assertEqual(r["score"], 100, r)
        self.assertTrue(any("last commit on or before" in n for n in r["notes"]), r["notes"])
        # the student's working tree is untouched
        self.assertIn("@main", open(os.path.join(repo, ".github", "workflows", "ci.yml")).read())
        # without --at-deadline the newest files are marked
        self.assertEqual(block(self.run_marker(repo, runs, deadline=False),
                               "triggers and trust")["points"], 0)

    def test_runs_after_the_deadline_do_not_count(self):
        repo = self.repo_with_late_commit(GOOD, GOOD + "# late\n")
        runs = [
            {"head_branch": "main", "status": "completed", "conclusion": "failure",
             "run_duration_ms": 9000, "created_at": "2026-10-12T04:00:00Z"},   # after
            {"head_branch": "main", "status": "completed", "conclusion": "success",
             "run_duration_ms": 21000, "created_at": "2026-10-11T14:00:00Z"},  # before
        ]
        r = self.run_marker(repo, runs)
        self.assertEqual(block(r, "has seen red")["points"], 0)     # the red came too late
        self.assertEqual(block(r, "runs your tests")["points"], 25)  # latest before = green

if __name__ == "__main__":
    unittest.main()
