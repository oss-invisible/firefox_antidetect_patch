# repo-01: noreply identity

**Rule.** Every commit, annotated tag and tagger made public carries a GitHub noreply address. Commits are made as `feder-cr <85809106+feder-cr@users.noreply.github.com>` (this noreply identity is the one in use here), never with a personal email, in the author, the committer, or a tag's tagger.

The check is in two places and has one judge, read from `main` of the core, never from the judged branch:
- the job `noreply-identity` of `.github/workflows/series.yml` on pull requests and on pushes to `main`; it is a requirement of the job `gate`;
- `.github/workflows/noreply-identity.yml` on pushes to branches other than `main` and on tags, which calls the core's reusable workflow.

**Why.** A commit on a public repository publishes its email, and what others have cloned cannot be taken back. The identity is checked where it can still be changed: on the branch, before the merge. The job in `series.yml` is inline because a workflow started by a pull request may not call a workflow of another repository.

**Files.** `.github/workflows/series.yml`, `.github/workflows/noreply-identity.yml` (both exist only at the root: `export` does not copy them), `tools/tests/test_noreply_identity_gate.py` (the gate waits for the identity job and always runs; the inline job reads the judge from `main` of the core; branches and tags `series.yml` does not see go to the core's workflow).

**Don't.**
- Commit or tag with a personal email, or leave the global git identity of a machine to decide.
- Take the judge from the branch being judged.
- Remove the identity job from the `gate` of `series.yml`.
