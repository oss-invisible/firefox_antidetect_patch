# ci-01: builds from main or latitude branches

**Rule.** The engine is compiled only on the Latitude.sh build node, for the two legs (Linux and Windows x86_64), by `release.yml`; gates and tests run on GitHub. The secrets of the node are in the environment `latitude-builder`, limited to `main` and `latitude/*`, so a trial build is dispatched from one of those: `gh workflow run release.yml --ref latitude/<name> -f kind=candidate`.
- The compile cache belongs to a branch. A run reads its own branch's cache and `main`'s; a branch born from `main` starts with `main`'s, a branch that does not compiles cold.
- A release runs only from `main`, never from a tag: `release_plan.py` refuses a tag as the ref, and `kind=release` from any ref but `main`.
- `stop_after=objects` (compile the touched directories and stop, no link and no gate) is only for a candidate on a `latitude/*` branch; the plan refuses it elsewhere and for `kind=release`.
- A push to `main` and a weekly timer run a candidate by themselves, with the gtests, to keep `main`'s cache warm. A candidate publishes nothing.

**Why.** An Actions cache entry is saved for the ref that made it, and a later run reads only its own ref's and the default branch's. A run from a tag saves entries nothing can read, and a branch apart from `main` pays a cold build, which is hours. Limiting the environment keeps the node's secrets away from arbitrary branches.

**Files.** `platform/ci/src/scripts/release_plan.py` (`plan`, `RELEASE_BRANCH`, `STOP_AFTER_BRANCH_PREFIX`), `.github/workflows/release.yml` (inputs `kind`, `release_tag`, `compile_cache`, `wrapper_ref`, `core_ref`, `stop_after`, `gtests`, `gtest_filter`; the jobs with `environment: latitude-builder`), `platform/ci/src/scripts/ci/latitude_node.py`.

**Don't.**
- Dispatch a build from a tag, or from a branch that does not descend from `main`.
- Dispatch a release from any ref but `main`.
- Compile the engine anywhere but the build node.
