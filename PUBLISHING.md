# Publishing coop-sql-review

How to get this onto GitHub and PyPI so anyone can install it with
`pipx install coop-sql-review`. You do the GitHub + PyPI account steps **once**; after that,
**every release is just a git tag** and GitHub does the rest automatically — no passwords or API
tokens stored anywhere.

> Most steps run in a terminal. Lines starting with `$` are commands to type (without the `$`).

---

## Part A — Put the code on GitHub (one time)

1. **Make sure you have the GitHub CLI** (`gh`) and are logged in:
   ```
   $ gh auth status
   ```
   If it says you're not logged in: `gh auth login` and follow the prompts (choose GitHub.com →
   HTTPS → login with a browser).

2. **From the project folder**, create the repo and push it. This repo's CI/publish workflows
   assume the owner/name `kabukisensei/coop-sql-review` (in `pyproject.toml` and the README); use
   that, or update those references if you pick a different name.
   ```
   $ cd coop-sql-review        # the project folder
   $ git init -b main
   $ git add -A
   $ git commit -m "Initial commit: coop-sql-review"   # tag the release separately (see Part B)
   $ gh repo create coop-sql-review --private --source=. --remote=origin --push
   ```
   (Use `--public` instead of `--private` if it should be open.)

3. Confirm the **CI** workflow runs green on GitHub (Actions tab). It lints and tests on
   Windows + Linux across Python 3.10–3.13.

---

## Part B — Set up PyPI Trusted Publishing (one time, no tokens)

This lets GitHub publish to PyPI securely without storing any secret.

1. **Create a PyPI account** at https://pypi.org and **turn on 2FA** (Account settings → Add 2FA).
   This is required to publish.

2. **Add a "pending publisher"** so PyPI will accept the first upload from your GitHub Action.
   Go to https://pypi.org/manage/account/publishing/ and fill in:
   - **PyPI project name:** `coop-sql-review`
   - **Owner:** your GitHub user/org (e.g. `kabukisensei`)
   - **Repository name:** `coop-sql-review`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`

   Click **Add**.

3. **Create the matching GitHub environment.** On GitHub: the repo → **Settings → Environments →
   New environment** → name it exactly **`pypi`** → Save. (No secrets needed inside it.)

That's the whole setup. The repo's `.github/workflows/publish.yml` already requests the right
permissions (`id-token: write`, `environment: pypi`) and uses the official PyPI publish action.

---

## Part C — Cut a release (every time)

A release is triggered by pushing a **version tag** that starts with `v`.

1. **Bump the version in ONE place** — `src/coop_sql_review/__init__.py`:
   - `src/coop_sql_review/__init__.py` → `__version__ = "0.1.1"`

   > **Do not add a `version =` key to `pyproject.toml`.** The version is
   > single-sourced: `pyproject.toml` declares `dynamic = ["version"]` and
   > `[tool.hatch.version] path = "src/coop_sql_review/__init__.py"`, so
   > hatchling reads `__version__` automatically at build time. Adding a static
   > `version =` key conflicts with the `dynamic` declaration and breaks
   > `python -m build`.

   Use [semantic versioning](https://semver.org): bump the **last** number for fixes
   (`0.1.0 → 0.1.1`), the **middle** for new features (`0.1.0 → 0.2.0`), the **first** for
   breaking changes (`0.1.0 → 1.0.0`).

2. **Commit and tag:**
   ```
   $ git add -A
   $ git commit -m "Release v0.1.1"
   $ git push
   $ git tag v0.1.1
   $ git push origin v0.1.1
   ```

3. The **publish workflow** runs automatically: it builds the wheel, smoke-tests it in a clean
   environment (`coop-sql-review --version`), and publishes to PyPI. Watch it on the **Actions**
   tab. Within a couple of minutes the new version is live at
   https://pypi.org/project/coop-sql-review/.

> **PyPI version numbers are permanent.** You can't re-upload or reuse a number (even after
> deleting it). If a release is bad, bump to the next number and publish again.

---

## Part D — Tell people how to install

Once it's on PyPI, installing is one line (see the README for the full beginner walkthrough):
```
pipx install coop-sql-review
```
And updating later:
```
coop-sql-review update
```

---

## Quick reference

| Task | Command |
|---|---|
| First push to GitHub | `gh repo create coop-sql-review --source=. --remote=origin --push` |
| Build the wheel locally (to test) | `python -m build` |
| Cut release `vX.Y.Z` | bump version in `src/coop_sql_review/__init__.py` → commit → `git tag vX.Y.Z && git push origin vX.Y.Z` |
| Check what published | https://pypi.org/project/coop-sql-review/ |

Before any release, make sure `ruff check src tests`, `ruff format --check src tests`, and
`pytest` are all green locally — CI enforces the same.
