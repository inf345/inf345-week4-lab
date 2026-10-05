#!/usr/bin/env python3
"""
INF 345 Milestone 2 - marks a student's continuous integration setup.

Two sources of evidence:
  - the workflow YAML, read from a clone of the repository
  - the run history, read from the GitHub API

    python3 mark_m2.py --repo https://github.com/<user>/<project>
    python3 mark_m2.py --path . --runs-json runs.json    # offline
    python3 mark_m2.py --repo <url> --at-deadline        # what the course run does

--at-deadline marks the last commit on or before the deadline, and counts only
runs created on or before it - a push after the deadline changes nothing.

The API is read with 'gh api' when the GitHub CLI is available, because an
authenticated request gets 5000 requests an hour and an anonymous one gets 60 -
and 60 does not mark a class of 44. Falling back to an anonymous request works
for a handful of students and then starts failing; set GITHUB_TOKEN instead.

Exit code 0 only if the score is 100.
Nothing here is hidden from students. It is the rubric.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

try:
    import yaml
except ImportError:
    print("::error::pyyaml is required: pip install pyyaml")
    sys.exit(2)


DEADLINE = "2026-10-11T23:59:59+05:00"      # Sunday 11 October, 23:59 Almaty (UTC+5)


def _when(stamp):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def runs_before(runs, deadline=DEADLINE):
    """Only the runs GitHub created on or before the deadline (newest first, as given)."""
    limit = datetime.datetime.fromisoformat(deadline)
    kept = []
    for r in runs or []:
        when = _when(r.get("created_at"))
        if when is not None and when <= limit:
            kept.append(r)
    return kept


def deadline_commit(path, deadline=DEADLINE):
    rc, out, _ = run(["git", "rev-list", "-1", "--first-parent",
                      f"--before={deadline}", "HEAD"], cwd=path)
    return out.strip() if rc == 0 and out.strip() else None


def tree_at(path, rev):
    """Extract the files of commit `rev` into a new temporary folder (or None).
    The student's working tree is never touched."""
    tmp = tempfile.mkdtemp(prefix="m2-tree-")
    try:
        arc = subprocess.run(["git", "archive", "--format=tar", rev], cwd=path,
                             capture_output=True, timeout=180)
        if arc.returncode == 0:
            ext = subprocess.run(["tar", "-x", "-C", tmp], input=arc.stdout,
                                 capture_output=True, timeout=180)
            if ext.returncode == 0:
                return tmp
    except (OSError, subprocess.SubprocessError):
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    return None


def run(cmd, cwd=None, timeout=180):
    try:
        p = subprocess.run(cmd, cwd=cwd, timeout=timeout,
                           capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", str(exc)


# --------------------------------------------------------------- the API

def repo_slug(url):
    m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def fetch_runs(slug):
    """Returns (runs, note). runs is [] when it could not be read."""
    if shutil.which("gh"):
        rc, out, err = run(["gh", "api", "-X", "GET",
                            f"repos/{slug}/actions/runs",
                            "-f", "per_page=100"], timeout=60)
        if rc == 0:
            try:
                return json.loads(out).get("workflow_runs", []), "gh api"
            except json.JSONDecodeError:
                pass
        note = f"gh api failed: {(err or out).strip()[:120]}"
    else:
        note = "gh not installed"

    url = f"https://api.github.com/repos/{slug}/actions/runs?per_page=100"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "inf345"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("workflow_runs", []), "anonymous API"
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return [], (note + "; API refused (rate limit?) - set GITHUB_TOKEN "
                        "or install gh")
        return [], f"{note}; API returned {exc.code}"
    except Exception as exc:
        return [], f"{note}; {type(exc).__name__}"


# ------------------------------------------------------------- the YAML

def load_workflows(path):
    d = os.path.join(path, ".github", "workflows")
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if not name.endswith((".yml", ".yaml")):
            continue
        p = os.path.join(d, name)
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
            out.append((name, yaml.safe_load(raw), raw))
        except yaml.YAMLError as exc:
            out.append((name, None, str(exc)))
    return out


def all_steps(wf):
    for job in (wf.get("jobs") or {}).values():
        if isinstance(job, dict):
            for step in (job.get("steps") or []):
                if isinstance(step, dict):
                    yield job, step


def triggers_of(wf):
    # YAML parses a bare `on:` key as the boolean True. Famously.
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on.keys())
    return set()


# ------------------------------------------------------------ the gates

def gate_workflow_exists(path, wfs, runs, note):
    if not wfs:
        return False, "no workflow file under .github/workflows/"
    broken = [n for n, parsed, _ in wfs if parsed is None]
    if broken:
        return False, f"{broken[0]} is not valid YAML"
    return True, f"{len(wfs)} workflow file(s): " + ", ".join(n for n, _, _ in wfs)


def gate_has_runs(path, wfs, runs, note):
    if not runs:
        return False, f"no workflow runs found ({note})"
    return True, f"{len(runs)} runs read via {note}"


def gate_no_secrets(path, wfs, runs, note):
    for name, _, raw in wfs:
        for pat, label in [(r"AKIA[0-9A-Z]{16}", "AWS key"),
                           (r"gh[pousr]_[A-Za-z0-9]{36,}", "GitHub token")]:
            if re.search(pat, raw or ""):
                return False, f"{label} written literally in {name}"
    return True, "no literal credentials in the workflow files"


# ----------------------------------------------------------- the blocks

def block_triggers(path, wfs, runs, note):
    """25 - runs on push AND pull_request; borrowed code pinned; token scoped."""
    problems = []
    trig = set()
    for _, wf, _ in wfs:
        trig |= triggers_of(wf)
    if "push" not in trig:
        problems.append("no push trigger")
    if "pull_request" not in trig:
        problems.append("no pull_request trigger")

    for name, wf, _ in wfs:
        for _, step in all_steps(wf):
            u = step.get("uses")
            if not isinstance(u, str) or "@" not in u or u.startswith(("./", "docker://")):
                continue
            action, ref = u.split("@", 1)
            if ref in ("main", "master", "HEAD", "latest"):
                problems.append(f"{u} follows a moving branch - pin a release such as @v7")
            elif not action.startswith("actions/") and not re.fullmatch(r"[0-9a-f]{40}", ref):
                problems.append(f"{u} is a third-party action pinned by a tag - pin it "
                                f"to the full commit SHA (the Trivy story, week 4)")

    scoped = all(isinstance(wf, dict) and ("permissions" in wf or all(
        isinstance(j, dict) and "permissions" in j for j in (wf.get("jobs") or {}).values()))
        for _, wf, _ in wfs)
    if not scoped:
        problems.append("no 'permissions:' block - say what the token may do "
                        "(contents: read is enough for tests)")
    if problems:
        return 0, "; ".join(dict.fromkeys(problems))
    return 25, "push and pull_request; actions pinned; token scoped with permissions"


def block_runs_tests(path, wfs, runs, note):
    calls = False
    for _, wf, _ in wfs:
        for _, step in all_steps(wf):
            body = step.get("run")
            if isinstance(body, str) and re.search(r"scripts/test\.sh", body):
                calls = True
    if not calls:
        return 0, ("no step runs scripts/test.sh. The workflow should call your "
                   "own script, not repeat the commands inline - otherwise the "
                   "two drift apart and only one of them is tested.")
    main_runs = [r for r in runs
                 if r.get("head_branch") in ("main", "master")
                 and r.get("status") == "completed"]
    if not main_runs:
        return 0, "no completed run on the default branch"
    latest = main_runs[0]
    if latest.get("conclusion") != "success":
        return 0, (f"the latest run on the default branch concluded "
                   f"'{latest.get('conclusion')}', not success")
    return 25, "calls scripts/test.sh; latest run on the default branch is green"


def block_seen_red(path, wfs, runs, note):
    done = [r for r in runs if r.get("status") == "completed"]
    ok = sum(1 for r in done if r.get("conclusion") == "success")
    bad = sum(1 for r in done if r.get("conclusion") == "failure")
    if ok and bad:
        return 25, f"{ok} successful and {bad} failed run(s) in the history"
    if not bad:
        return 0, ("no failed run in the history. Break something on purpose, "
                   "push it, read the log, then fix it. A pipeline you have "
                   "only ever seen green is one you have not learned to read.")
    return 0, "no successful run in the history"


DEP_FILES = ("requirements.txt", "Pipfile.lock", "poetry.lock", "uv.lock",
             "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum",
             "pom.xml", "build.gradle", "build.gradle.kts", "Cargo.lock",
             "Gemfile.lock", "composer.lock")


def has_dependencies(path):
    """True if the project declares third-party dependencies worth caching."""
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                   ("node_modules", "vendor", "build", "dist", "target")]
        for f in files:
            if f in DEP_FILES or re.fullmatch(r"requirements[-\w]*\.txt", f):
                return f
            if f == "pyproject.toml":
                txt = open(os.path.join(root, f), errors="replace").read()
                if re.search(r"(?m)^\s*dependencies\s*=\s*\[\s*[\"']", txt):
                    return f
    return None


def uses_pipefail(wf, job, step):
    for scope in (step, job, wf):
        if not isinstance(scope, dict):
            continue
        shell = scope.get("shell") if scope is step else \
            ((scope.get("defaults") or {}).get("run") or {}).get("shell")
        if isinstance(shell, str):
            return shell.strip() == "bash" or "pipefail" in shell
    return False


def block_hygiene(path, wfs, runs, note):
    """25 - named job, ubuntu, pipefail, cache if there is something to cache, fast."""
    problems = []
    cached = named = False
    test_step_pipefail = None
    for _, wf, _ in wfs:
        for job_id, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            if job.get("name"):
                named = True
            ro = job.get("runs-on")
            if isinstance(ro, str) and not ro.startswith("ubuntu"):
                problems.append(f"runs-on is '{ro}', this course uses ubuntu-24.04")
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                u, w = step.get("uses", ""), step.get("with") or {}
                if isinstance(u, str) and "actions/cache" in u:
                    cached = True
                if isinstance(w, dict) and "cache" in w:
                    cached = True
                body = step.get("run")
                if isinstance(body, str) and "scripts/test.sh" in body:
                    ok = uses_pipefail(wf, job, step)
                    test_step_pipefail = ok if test_step_pipefail is None else (test_step_pipefail and ok)
    if test_step_pipefail is False:
        problems.append("the step that runs scripts/test.sh has no pipefail - add "
                        "'defaults: run: shell: bash' (the green lie, week 4)")
    manifest = has_dependencies(path)
    if manifest and not cached:
        problems.append(f"{manifest} lists dependencies but nothing is cached (a "
                        "'cache:' input on the setup action, or actions/cache)")
    if not named:
        problems.append("no job has a 'name:'")

    durations = [r.get("run_duration_ms") for r in runs[:10]
                 if isinstance(r.get("run_duration_ms"), int)]
    if durations:
        worst = max(durations) / 1000.0
        if worst > 300:
            problems.append(f"slowest recent run took {worst:.0f}s, over the "
                            f"5 minute budget")
    if problems:
        return 0, "; ".join(problems)
    what = "cached" if manifest else "no dependencies to cache"
    return 25, f"named, ubuntu, pipefail, {what}, inside the time budget"


GATES = [("workflow file", gate_workflow_exists),
         ("run history", gate_has_runs),
         ("no credentials", gate_no_secrets)]
BLOCKS = [("triggers and trust", block_triggers),
          ("runs your tests", block_runs_tests),
          ("has seen red", block_seen_red),
          ("hygiene", block_hygiene)]


def mark(path, runs, note, as_json=False, notes=None):
    wfs = load_workflows(path)
    report = {"gates": [], "blocks": [], "score": 0, "capped": False,
              "notes": list(notes or [])}
    for name, fn in GATES:
        ok, detail = fn(path, wfs, runs, note)
        report["gates"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["capped"] = True
    if not report["capped"]:
        for name, fn in BLOCKS:
            pts, detail = fn(path, wfs, runs, note)
            report["blocks"].append({"name": name, "points": pts, "detail": detail})
            report["score"] += pts

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for n in report["notes"]:
            print(f"  note: {n}")
        print()
        for g in report["gates"]:
            print(f"  [gate {'ok ' if g['ok'] else 'FAIL'}] {g['name']}: {g['detail']}")
        if report["capped"]:
            print("\n  A gate failed, so this milestone scores 0.\n\nSCORE: 0/100")
            return 1
        print()
        for b in report["blocks"]:
            print(f"  [ {b['points']:>2}/25 ] {b['name']}")
            print(f"            {b['detail']}")
        print(f"\nSCORE: {report['score']}/100")
    return 0 if report["score"] == 100 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mark INF 345 milestone 2.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo")
    src.add_argument("--path")
    ap.add_argument("--runs-json", help="read run history from a file instead "
                                        "of the API (for testing)")
    ap.add_argument("--at-deadline", action="store_true",
                    help=f"mark the last commit on or before {DEADLINE} and count "
                         "only the runs created by then")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.runs_json:
        runs, note = json.load(open(a.runs_json)), "a local file"
    else:
        slug = repo_slug(a.repo or "")
        if not slug and a.path:
            rc, out, _ = run(["git", "remote", "get-url", "origin"], cwd=a.path)
            slug = repo_slug(out.strip()) if rc == 0 else None
        if not slug:
            print("::error::could not work out owner/repo - pass --repo")
            return 1
        runs, note = fetch_runs(slug)

    notes = []
    if a.at_deadline:
        total = len(runs or [])
        runs = runs_before(runs)
        notes.append(f"counting the {len(runs)} of {total} runs created on or before {DEADLINE}")

    def go(root):
        tree = None
        if a.at_deadline:
            dc = deadline_commit(root)
            if not dc:
                notes.append(f"no commit on or before {DEADLINE} - marking the newest commit")
            else:
                rc, head, _ = run(["git", "rev-parse", "HEAD"], cwd=root)
                notes.append(f"marking {dc[:12]}, the last commit on or before {DEADLINE}")
                if not (rc == 0 and head.strip() == dc):
                    tree = tree_at(root, dc)
                    if tree is None:
                        notes.append("could not extract that commit - reading the newest files")
        try:
            return mark(tree or root, runs, note, a.json, notes)
        finally:
            if tree:
                shutil.rmtree(tree, ignore_errors=True)

    if a.path:
        return go(os.path.abspath(a.path))

    tmp = tempfile.mkdtemp(prefix="m2-")
    try:
        rc, _, err = run(["git", "clone", "--quiet", a.repo, tmp])
        if rc != 0:
            print(f"::error::could not clone {a.repo}: {err.strip()[:200]}")
            return 1
        return go(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
