# Release Process — sbeam FEA Application

Authoritative guide for versioning, validating, and releasing sbeam.

---

## 1. Version Numbering

sbeam uses **semantic versioning**: `MAJOR.MINOR.PATCH`

| Component | When to increment |
|---|---|
| `MAJOR` | Breaking change to the BDF input format, case control syntax, or f06 output format |
| `MINOR` | New BDF card support, new solver (SOL), new viewer capability |
| `PATCH` | Bug fix that does not change the public interface |

The current version is recorded in `pyproject.toml` (or `setup.py`) under `version =`.

**Pre-release tags:** use `1.2.0-beta.1` for development candidates shared externally. Never publish an unversioned build.

---

## 2. What Constitutes a Release

**Cadence rule (2026-08-04, R13): release small and often.** Cut a release whenever the
gate in §3 passes and any of the following is true:

- ~1 month has passed since the last tag, **or** ~5 steps have closed since the last tag
  — whichever comes first. Accumulated small improvements are a valid release; do not
  wait for a phase milestone.
- A critical bug fix is resolved and verified.
- A new SOL (solver type) is production-ready and passes all acceptance tests.
- A breaking change to the BDF format or f06 output has been made.

Version numbers are **decoupled from phase completion** — bump `MINOR` per release under
the §1 rules. Do not cut a release for documentation-only changes. Never let
`[Unreleased]` grow past roughly a month of work: unreleased work has no regression
baseline (the pre-2026-08 state — one tagless release in three months and ~2,500
unreleased changelog lines — is the cautionary precedent).

---

## 3. Pre-Release Gate (slim, 2026-08-04)

The gate is **deliberately small and bounded** — documentation consistency is enforced
per-change by the tiered closure requirement in CLAUDE.md, not re-audited at release
time. Each item is a hard gate:

- [ ] **CI green:** `ruff` + `pyright` + full `pytest tests/ -v` — zero failures, zero
  errors, no `skip`/`xfail` without a documented reason in the backlog. The closed-form
  verification cases (≤ 0.1% tolerance), the VAL2 shipped-deck gates, and the coordinate
  regression tests are all part of the suite and pass with it (authoritative case tables:
  `00_program_overview.md`).
- [ ] **No open `[CRITICAL]`/`[MAJOR]` review findings** (see `07_code_review_process.md`).
- [ ] **Backlog is open-items-only** for the release scope (anything closed has moved to
  `docs/40_history/` — spot-check, not an audit).
- [ ] **`CHANGELOG.md` entry cut** for this version: features, fixes, breaking changes.
- [ ] **Viewer smoke test** — only if viewer code changed since the last tag: app starts,
  a representative model loads/solves/displays.

---

## 4. Cutting the Release

### Step 1 — Bump the version

Update the version string in `pyproject.toml`:

```toml
[project]
version = "X.Y.Z"
```

Commit with message: `Bump version to X.Y.Z`

### Step 2 — Update the changelog

Add a dated entry to `CHNGLOG` (or `CHANGELOG.md`):

```
## vX.Y.Z — YYYY-MM-DD

### Added
- ...

### Fixed
- ...

### Breaking changes
- ...
```

### Step 3 — Tag the release

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

If using GitHub:

```bash
git push origin vX.Y.Z
```

Then create a GitHub Release from the tag with the changelog entry as the release body.

### Step 4 — Archive verification results

Create `docs/verification/vX.Y.Z.md` recording the numerical output of the closed-form
verification cases run against the release tag (pasting the CI verification-test output is
sufficient). This provides a permanent regression baseline for future releases.

---

## 5. Post-Release Steps

- [ ] Update `docs/30_future/00_backlog.md` — remove any items resolved by this release; add any new bugs discovered during final testing.
- [ ] Update `docs/40_history/00_completed_development.md` — confirm the release tag and date are noted under the relevant steps.
- [ ] Open the next development cycle by identifying the next milestone in `docs/30_future/00_backlog.md`.
- [ ] If the release introduced any new BDF cards or solver types, update the supported card table in `CLAUDE.md`.

---

## 6. Hotfix Process

A hotfix is a `PATCH` release that corrects a critical defect in a released version.

1. Branch from the release tag: `git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z`
2. Apply the minimal fix — **no new features**, no refactoring.
3. Run the full pre-release checklist (§3), focusing on the affected subsystem.
4. Bump to `X.Y.Z+1`, update changelog, tag, and release.
5. Merge the fix back to `main`: `git cherry-pick <fix-commit>` or `git merge hotfix/...`.
6. Record the resolved bug under "Resolved defects" in the matching `docs/40_history/` area file (see the index `00_completed_development.md`).

---

## 7. Release Artefacts

| Artefact | Location | Notes |
|---|---|---|
| Source tag | `git tag vX.Y.Z` | Permanent point-in-time reference |
| Changelog entry | `CHNGLOG` | Human-readable summary |
| Verification record | `docs/verification/vX.Y.Z.md` | Numerical regression baseline |
| GitHub Release | GitHub UI | Links tag + release notes |

sbeam is not published to PyPI; distribution is via git clone or zip archive from the GitHub release page.
