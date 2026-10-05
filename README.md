# INF 345 — Week 4 Practice

**Your project gets a pipeline**

**M2 deadline: Sunday 11 October, 23:59** Almaty time. The marker reads your
repository and its run history on GitHub after the deadline.

By the end of today, every push and every pull request to your M1 project runs
your tests on a clean machine — and the green tick means what it says.

---

## Before the session (at home, 10 minutes)

- [ ] `./scripts/test.sh` works on your laptop and prints `TESTS: n/n`. A
      pipeline cannot run a script that does not work.
- [ ] You know your default branch name: open your repository on GitHub — the
      branch button top-left says `main` (or `master`).
- [ ] Optional: `pip install zizmor pyyaml` (the linter from the lecture, and
      what the M2 marker needs to run on your laptop).

---

## Part 1 — Your first workflow (20 minutes)

Work on a branch, like every change from now on.

```bash
cd <your project>
git switch -c ci
mkdir -p .github/workflows
```

Create `.github/workflows/ci.yml` from this scaffold. **Fill the five blanks
yourself** — they are the parts that are about *your* project.

```yaml
name: CI

on:
  push:
    branches: [ ____ ]            # 1. your default branch
  pull_request:

permissions:
  contents: ____                  # 2. tests only need to READ the code

defaults:
  run:
    shell: bash                   # pipefail - the green lie from the lecture

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: ____                    # 3. the name you want to see in the Actions tab
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false

      # 4. set up YOUR language - see the table below.
      #    Delete this step if you need nothing beyond what the runner has.
      - uses: ____
        with:
          ____

      - run: ____                 # 5. the ONE command that runs your tests
```

**Blank 4 — setting up your language:**

| Language | `uses:` | `with:` | Cache — only if you have this file |
|---|---|---|---|
| Python | `actions/setup-python@v7` | `python-version: "3.12"` | `cache: pip` needs `requirements.txt` (or `pyproject.toml` with dependencies) |
| Node | `actions/setup-node@v7` | `node-version: "24"` | `cache: npm` needs `package-lock.json` |
| Go | `actions/setup-go@v7` | `go-version-file: go.mod` | automatic when `go.sum` exists |
| Java | `actions/setup-java@v5` | `distribution: temurin` and `java-version: "21"` | `cache: maven` needs `pom.xml`; `cache: gradle` needs `build.gradle` |

**Blank 5** is the whole point: it is `./scripts/test.sh`. Not your test
commands copied into the YAML — your script. If the commands live in two
places they drift apart, and one of them stops being tested.

Push the branch and open a pull request:

```bash
git add .github/workflows/ci.yml
git commit -m "Add CI: run the tests on every push and pull request"
git push -u origin ci
```

On GitHub: **Compare & pull request → Create pull request**. Scroll down —
the check appears on the pull request. Click **Details**.

> **Checkpoint:** a green check on your pull request, and `TESTS: n/n` in the
> log of the test step. Merge the pull request.

---

## Part 2 — Break it on purpose (15 minutes)

M2 requires at least one **failed** run in your history. Not as a punishment —
because a pipeline you have only seen green is one you have not learned to read.

```bash
git switch main && git pull
git switch -c break-it
```

Break **one** thing — pick one:

- make one test expect the wrong value (the honest way — your tests should catch it)
- or delete the `checkout` step (you will see exit code 127)

Commit, push, open a pull request. When it goes red, answer the three questions
**in the pull request description**, in your own words:

1. Which step failed?
2. What is the exact line that tells you why? (copy it)
3. What changed since it was last green?

Then fix it, push again to the same branch, watch it go green, and merge.

> **Checkpoint:** your Actions tab shows at least one red run and one green run,
> and the latest run on your default branch is green.

---

## Part 3 — Harden it (10 minutes)

Check each line of your workflow against this list. The marker checks all of it.

- [ ] `on:` has **both** `push` and `pull_request`
- [ ] `permissions:` is set — `contents: read` is enough for tests
- [ ] `defaults: run: shell: bash` — so a pipe cannot hide a failure
- [ ] the job has a `name:`
- [ ] `runs-on: ubuntu-24.04`
- [ ] actions are pinned to a release (`@v7`), never `@main`; anything **not**
      from `actions/` is pinned to a full 40-character commit SHA
- [ ] if you have a dependency file (table above), caching is on
- [ ] a run takes under 5 minutes

Then mark yourself — exactly what I will run after the deadline:

```bash
pip install pyyaml
python3 mark_m2.py --repo https://github.com/<you>/<your-project>
```

---

## How M2 is marked

**Gates — any failure scores 0:** a workflow file under `.github/workflows/`
that is valid YAML · at least one run on GitHub · no credential written in a
workflow file.

| Block | 25 points for |
|---|---|
| **triggers and trust** | `push` and `pull_request` · actions pinned (releases for `actions/*`, commit SHAs for anyone else) · a `permissions:` block |
| **runs your tests** | a step runs `scripts/test.sh` · the latest completed run on your default branch is green |
| **has seen red** | at least one failed run **and** one successful run in your history |
| **hygiene** | a named job · an Ubuntu runner · pipefail on the test step (`shell: bash`) · caching if you have dependencies · every recent run under 5 minutes |

`mark_m2.py` is in this repository. It is the rubric; nothing is hidden.

**And one thing the script cannot check:** in Tuesday sessions from now on I
will open a few repositories on screen and ask the owner about one line.
"Why is this here? What happens if I delete it?" Two minutes, no trick
questions — the questions an interviewer asks.

---

## Common failures

| What you see | Why | Fix |
|---|---|---|
| The workflow never runs | the folder is `.github/workflow` (no **s**), or the file is not `.yml`/`.yaml`, or `branches: [main]` but your branch is `master` | exactly `.github/workflows/ci.yml`; match your default branch |
| **Invalid workflow file** on the Actions tab | indentation — a tab, or three spaces instead of two | two spaces per level, no tabs. Your editor may insert tabs: turn that off |
| `mapping values are not allowed in this context` | a colon followed by a space inside an unquoted value, e.g. `run: echo "Result: ok"` | put the command on its own line: `run: \|` then the command indented below |
| `./scripts/test.sh: No such file or directory` · exit 127 | no `actions/checkout` step — the machine is empty | add the checkout step first |
| `Permission denied` · exit 126 | the executable bit never reached GitHub (Windows) | `git update-index --chmod=+x scripts/test.sh`, commit, push |
| `/usr/bin/env: 'bash\r': No such file or directory` | Windows line endings in the script | add `.gitattributes` with `*.sh text eol=lf`, then `git add --renormalize .` and commit |
| setup-python: `No file ... matched to [**/requirements.txt ...]` | `cache: pip` but no `requirements.txt` | remove `cache: pip` — with no dependencies there is nothing to cache |
| setup-node: `Dependencies lock file is not found` | `cache: npm` without `package-lock.json` | run `npm install` locally and commit `package-lock.json`, or remove `cache:` |
| Go: `cannot find main module` | no `go.mod` | `go mod init <name>` locally, commit `go.mod` |
| Two runs for every push | a push to a branch with an open PR matches both `push` and `pull_request` | restrict `push` to `branches: [main]` as in the scaffold |
| Yellow warning about Node 20 | an old action version (`@v4`) | use the versions in the table — they run on Node 24 |
| Green tick, but you can see a test failure in the log | the green lie: a pipe without pipefail | `defaults: run: shell: bash` |

## Stuck?

1. Read the red step's log from the **bottom up** to the first line that says
   what went wrong. That line is the answer 9 times out of 10.
2. Compare your file with the scaffold, character by character — indentation first.
3. In the session: say it in the chat immediately. After: email with `INF 345`
   and your group in the subject, from your `@sdu.edu.kz` address, with **the
   link to the failing run** and the error line copied as text. A link gets an
   answer the same day; "it doesn't work" gets a question back.

---

## Stretch (optional, not marked)

- **A matrix:** test on three versions of your language at once (`strategy: matrix:`).
- **zizmor:** `zizmor .github/workflows/` — fix whatever it finds.
- **GitLab:** write the same pipeline as `.gitlab-ci.yml` (lecture slide 24).
  Most companies in Kazakhstan run GitLab; this is the translation you will do
  in your first job.
- **Make green mandatory:** Settings → Rules → Rulesets → a branch ruleset on
  `main` requiring a pull request and your check.
- **Dependabot:** add `.github/dependabot.yml` so pinned actions stay current.
