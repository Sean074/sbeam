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

A release is cut when one or more of the following is true:

- A Phase milestone is complete (e.g., all Phase 2 steps done).
- A critical bug fix (B-series) is resolved and verified.
- A new SOL (solver type) is production-ready and passes all acceptance tests.
- A breaking change to the BDF format or f06 output has been made.

Do **not** cut a release for documentation-only changes or in-progress steps.

---

## 3. Pre-Release Checklist

Complete all items before tagging. Each item is a hard gate — do not proceed past a failure.

### 3.1 Backlog and Documentation

- [ ] `development_plan_bugs_todo.md` — all bugs listed for this release are marked resolved.
- [ ] `docs/completed_development.md` — all steps included in this release are recorded with their full step format.
- [ ] All `docs/` files are consistent with the code being released (no documentation drift).
- [ ] `CHANGELOG.md` (or `CHNGLOG`) entry written for this version: summary of new features, bug fixes, and breaking changes.

### 3.2 Code Quality

- [ ] No `[CRITICAL]` or `[MAJOR]` open findings from the most recent code review (see `docs/code_review.md`).
- [ ] No TODO comments that are release-blocking (deferred-to-next-version TODOs are acceptable if logged in `development_plan_bugs_todo.md`).
- [ ] All public functions in `assembly/`, `solver/`, `parser/`, and `model/` have type hints and docstrings.

### 3.3 Test Suite

Run the full test suite and confirm all pass:

```
pytest tests/ -v
```

- [ ] Zero test failures.
- [ ] Zero test errors (as distinct from assertion failures).
- [ ] No tests marked `skip` or `xfail` without a documented reason in `development_plan_bugs_todo.md`.

### 3.4 Analytical Verification Cases

All four closed-form verification cases must pass. Tolerance: ≤ 0.1% relative error.

| Case | Formula | Module |
|---|---|---|
| Cantilever tip load deflection | `δ = PL³/3EI` | SOL 101 |
| Simply supported mid-span deflection | `δ = PL³/48EI` | SOL 101 |
| Cantilever fundamental frequency | `f₁ = (1.875²/2π)√(EI/ρAL⁴)` | SOL 103 |
| Free-free beam rigid body modes | First 6 modes ≤ 0.001 Hz | SOL 103 |

- [ ] All four cases pass.
- [ ] Verification output (numerical result vs. analytical result) is recorded in the release notes.

### 3.5 Coordinate System Regression

- [ ] At least one test model with a non-zero `CORD2R` (CP ≠ 0 on GRID, or non-zero CID on FORCE/MOMENT/CONM2) produces correct results.
- [ ] Round-trip coordinate transform test passes to machine precision.

### 3.6 Viewer Smoke Test

- [ ] Streamlit viewer starts without error: `streamlit run sbeam/viewer/app.py`.
- [ ] A representative model (e.g., cantilever) can be loaded, viewed, solved (SOL 101 and SOL 103), and results displayed without error.
- [ ] f06 file is written to the expected location.

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

Create `docs/verification/vX.Y.Z.md` recording the numerical output of all four verification cases run against the release tag. This provides a permanent regression baseline for future releases.

---

## 5. Post-Release Steps

- [ ] Update `development_plan_bugs_todo.md` — remove any items resolved by this release; add any new bugs discovered during final testing.
- [ ] Update `docs/completed_development.md` — confirm the release tag and date are noted under the relevant steps.
- [ ] Open the next development cycle by identifying the next milestone in `development_plan_bugs_todo.md`.
- [ ] If the release introduced any new BDF cards or solver types, update the supported card table in `CLAUDE.md`.

---

## 6. Hotfix Process

A hotfix is a `PATCH` release that corrects a critical defect in a released version.

1. Branch from the release tag: `git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z`
2. Apply the minimal fix — **no new features**, no refactoring.
3. Run the full pre-release checklist (§3), focusing on the affected subsystem.
4. Bump to `X.Y.Z+1`, update changelog, tag, and release.
5. Merge the fix back to `main`: `git cherry-pick <fix-commit>` or `git merge hotfix/...`.
6. Record the resolved bug in `docs/completed_development.md` under "Resolved Defects".

---

## 7. Release Artefacts

| Artefact | Location | Notes |
|---|---|---|
| Source tag | `git tag vX.Y.Z` | Permanent point-in-time reference |
| Changelog entry | `CHNGLOG` | Human-readable summary |
| Verification record | `docs/verification/vX.Y.Z.md` | Numerical regression baseline |
| GitHub Release | GitHub UI | Links tag + release notes |

sbeam is not published to PyPI; distribution is via git clone or zip archive from the GitHub release page.
