# Release Process — sbeam FEA Application

Authoritative guide for versioning, validating, and releasing sbeam — and, since
2026-09-05, for the GitHub milestone/issue/branch workflow that drives development
(§2–§2a). Practices marked *(sloads)* were adopted from the sloads project's
multi-developer process after its 2026-08/09 review cycle — each one is a failure mode
sloads hit and fixed; the citations are its `DEVELOPMENT_PROCESS.md` §0 and
`RELEASE_PROCESS.md` §4.

---

## 1. Version Numbering

sbeam uses **semantic versioning**: `MAJOR.MINOR.PATCH`

| Component | When to increment |
|---|---|
| `MAJOR` | Breaking change to the BDF input format, case control syntax, or f06 output format |
| `MINOR` | A milestone completes (§2) — new BDF card support, new solver (SOL), new viewer capability |
| `PATCH` | Hotfix to a released version that does not change the public interface (§6) |
| `X.Y.0-beta.N` | Interim regression baseline cut on a release branch mid-milestone (§2) |

The current version is recorded in `pyproject.toml` under `version =`. Never publish an
unversioned build.

---

## 2. What Constitutes a Release (milestone model, 2026-09-05)

**Releases are milestone-driven.** Each planned release is a GitHub **milestone**
(`v0.3.0`, `v0.4.0`, …) whose issues define its scope; the authoritative milestone map
(definition of done per release, ladder to 1.0.0) is `docs/30_future/00_backlog.md`.
A MINOR release is cut when — and only when — its milestone's issues are all closed and
the §3 gate passes.

**Interim baselines (replaces the 2026-08-04 R13 minor-bump cadence):** the
release-small-and-often principle survives as **pre-release tags on the release branch**.
When ~1 month has passed since the last tag or ~5 issues have closed — whichever comes
first — and the §3 gate passes, tag `vX.Y.0-beta.N` on `release/X.Y.0` (annotated tag, no
GitHub Release needed, no verification archive). Unreleased work must never go
untagged past roughly a month: unreleased work has no regression baseline (the pre-2026-08
tagless precedent stands as the caution).

Do not cut any tag for documentation-only changes.

## 2a. Milestones, issues and branches (2026-09-05)

**Issues are the working backlog.** Every open work item is a GitHub issue carrying its
full body; labels encode the mission tag (`mission:E`/`mission:V`), kind
(`defect`, `physics` = design-note-before-code, `decision` = carries a convention-decision
checklist), and `opportunistic` (small, milestone-free). `docs/30_future/00_backlog.md`
holds the mission + milestone map only; `docs/30_future/02_parked.md` keeps unscheduled
ideas **out** of the tracker — activating a parked item means opening an issue and
deleting the parked entry.

**One branch per release** *(sloads §0 — per-item branches/PRs while solo are pure
overhead and created a double-close defect class)*: `release/X.Y.0` is cut from `main`
when the milestone opens, and every item of that milestone is worked directly on it.

**One commit per closed item** *(sloads)*: the closing commit carries the closure-tier
artefacts (CHANGELOG entry, doc updates, history entry — CLAUDE.md tiers) and names the
issue in its subject, e.g. `Pratt gust cases (#1)`. `git log` stays the step-per-commit
record.

**Closing an issue is explicit, in the same session** — run
`gh issue close N --comment "Closed by <sha> on release/X.Y.0"`. Never rely on
`Closes #N` in a commit or PR body: commit-message auto-close only fires on the default
branch, and *(sloads #38)* two closing paths both claiming the same item is a defect
class of its own. The tiered closure requirement in CLAUDE.md now includes this step.

**Milestone end:** §3 gate on the branch → merge to `main` locally with a merge commit
(`git merge --no-ff release/X.Y.0` — **never squash**: the per-item commits are the
record *(sloads)*) → §4 cut → close the milestone on GitHub → delete the release branch →
open the next milestone's branch.

**CI runs on release branches** (`.github/workflows/ci.yml` triggers on push to `main`
**and** `release/**`): the full ruff → pyright → pytest matrix, same as `main`. Without
this the beta gate would be unverifiable — a branch CI never sees is a branch no gate
covers *(the sloads CI-shape lesson, adapted: sbeam's full matrix is ~3 min, so no
fast/full split is needed)*.

**Git roles (standing practice, now written down):** the AI commits and tags locally and
verifies; the user performs every `git push` (branches and tags) and is the author of
record.

---

## 3. Pre-Release Gate (slim, 2026-08-04)

The gate is **deliberately small and bounded** — documentation consistency is enforced
per-change by the tiered closure requirement in CLAUDE.md, not re-audited at release
time. Each item is a hard gate (for a `-beta.N` tag, the first two items suffice):

- [ ] **CI green:** `ruff` + `pyright` + full `pytest tests/ -v` — zero failures, zero
  errors, no `skip`/`xfail` without a documented reason in an open issue. The closed-form
  verification cases (≤ 0.1% tolerance), the VAL2 shipped-deck gates, and the coordinate
  regression tests are all part of the suite and pass with it (authoritative case tables:
  `00_program_overview.md`).
- [ ] **No open `[CRITICAL]`/`[MAJOR]` review findings** (see `07_code_review_process.md`).
- [ ] **Milestone empty:** every issue on the milestone is closed (spot-check the
  milestone page, not an audit).
- [ ] **`CHANGELOG.md` entry cut** for this version: features, fixes, breaking changes.
- [ ] **Viewer smoke test** — only if viewer code changed since the last tag: app starts,
  a representative model loads/solves/displays. *(From v0.4.0 on, the scripted GUI
  journey test in CI is the first line and this hand walk is the second — see issue #11.)*

---

## 4. Cutting the Release

Steps 1–2 are commits on the release branch; step 3 happens after the merge to `main`.

### Step 1 — Bump the version

Update the version string in `pyproject.toml`:

```toml
[project]
version = "X.Y.Z"
```

Commit with message: `Bump version to X.Y.Z`

### Step 2 — Update the changelog

Cut `[Unreleased]` to a dated `## [X.Y.Z] — YYYY-MM-DD` entry in `CHANGELOG.md`
(Added / Fixed / Breaking changes), leaving a fresh empty `[Unreleased]` above it.

### Step 3 — Merge, tag, release

Merge the release branch into `main` (`--no-ff`, §2a), then:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

The user pushes `main` and the tag:

```bash
git push origin main vX.Y.Z
```

Then create a GitHub Release from the tag with the changelog entry (or a curated summary
linking it) as the release body, close the milestone, and delete the release branch.

### Step 4 — Archive verification results

Create `docs/verification/vX.Y.Z.md` recording the numerical output of the closed-form
verification cases run against the release tag (pasting the CI verification-test output is
sufficient). This provides a permanent regression baseline for future releases.

---

## 5. Post-Release Steps

- [ ] The GitHub milestone is closed and empty; any deliberately-deferred issue is moved
  to the next milestone (with a comment saying why), never left on a closed one.
- [ ] Update `docs/30_future/00_backlog.md` — milestone map row updated (tag + date);
  file any new defects found in final testing as issues.
- [ ] Update `docs/40_history/00_completed_development.md` — confirm the release tag and
  date are noted under the relevant entries.
- [ ] Open the next milestone's `release/X.Y.0` branch (§2a).
- [ ] If the release introduced any new BDF cards or solver types, update the supported
  card table in `CLAUDE.md`.

---

## 6. Hotfix Process

A hotfix is a `PATCH` release that corrects a critical defect in a **released** version.
A defect found mid-milestone in unreleased work is **not** a hotfix — it is the next
issue on the release branch *(sloads)*.

1. Branch from the release tag: `git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z`
2. Apply the minimal fix — **no new features**, no refactoring.
3. Run the full pre-release checklist (§3), focusing on the affected subsystem.
4. Bump to `X.Y.Z+1`, update changelog, tag, and release.
5. Merge the fix back to `main`: `git cherry-pick <fix-commit>` or `git merge hotfix/...`.
6. **Immediately merge `main` back into the open release branch**
   (`git checkout release/X.Y.0 && git merge main`) before the next item — this is the
   only path that puts a commit on `main` mid-milestone, and deferring the sync is where
   divergence bites *(sloads, corrected at their 0.7.2 cut)*.
7. Record the resolved bug under "Resolved defects" in the matching `docs/40_history/`
   area file (see the index `00_completed_development.md`).

---

## 7. Release Artefacts

| Artefact | Location | Notes |
|---|---|---|
| Source tag | `git tag vX.Y.Z` (or `vX.Y.0-beta.N`) | Permanent point-in-time reference |
| Changelog entry | `CHANGELOG.md` | Human-readable summary |
| Verification record | `docs/verification/vX.Y.Z.md` | Numerical regression baseline (full releases only) |
| GitHub Release | GitHub UI | Links tag + release notes (full releases only) |
| Closed milestone | GitHub UI | The release's issue-level record |

sbeam is not published to PyPI; distribution is via git clone or zip archive from the GitHub release page.

---

## Appendix — sloads practices reviewed and *not* adopted (2026-09-05)

Recorded so their absence is a decision, not an oversight; revisit at the first second
collaborator:

- **Changelog/history fragments** (`changes/<slug>.md` + a build script rolling them at
  cut): solves concurrent-PR merge conflicts on `CHANGELOG.md`/history files, which a
  solo repo does not have. Adopt when two people edit the changelog concurrently.
- **Branch protection + PR-only `main`, process-conformance guard tests** (branch-
  protection snapshot asserted by pytest, backlog↔issue drift checks): sbeam's `main` is
  unprotected and its backlog file no longer duplicates issue state, so there is nothing
  to guard yet.
- **Scripted solo loop** (`solo_start.sh`/`solo_close.sh`): sbeam's closure sequence is
  enforced by CLAUDE.md + this doc and executed in-session; scripts add value when a
  human runs the loop by hand.
- **Docs-only fast gate**: sbeam's full suite is ~3 min in CI; scaling the gate to the
  change set isn't worth the predicate.
- **Version single-sourcing in `_version.py`** (sloads' stale-`importlib.metadata`-stamp
  bug): sbeam stamps no version into its outputs today. If an f06/report provenance
  stamp is ever added, read the version from source, not install metadata.
