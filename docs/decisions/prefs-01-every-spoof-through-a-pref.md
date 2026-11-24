# prefs-01: every spoof goes through a pref

**Rule.** Every spoof is switched and parameterised by a pref under `zoom.stealth.*` (or `stealthfox.*`). The core declares the values; the engine reads them. The names are the contract with the core and are never renamed. A pref of ours is declared once: where Mozilla already declares a pref and we change its value, we change it on Mozilla's own line (a `declared-value` hook, [hook-02](hook-02-shape-and-contract.md)); our files declare only prefs Mozilla does not have.

A few declarations reach the engine as `STEALTHFOX_*` environment variables set at launch instead of prefs (among them `STEALTHFOX_WEBRTC_NETWORK`, `STEALTHFOX_PINGSENDER_ROUTE`, `STEALTHFOX_SECURITY_STATE`, `STEALTHFOX_FONT_MANIFEST`); their names are part of the same contract and are never renamed either.

**Why.** A pref is the one channel the core already uses to hand the engine a declared value ([product-01](product-01-no-value-from-the-host.md)). The core checks the engine's source for every `zoom.stealth.*` name it emits, so a pref name is kept as one whole literal in our file, and a rename breaks the core's checks against the engine's source. A pref declared twice has a final value that depends on load order, which Mozilla changes without notice.

**Files.** `platform/prefs/src/modules/libpref/init/StealthPrefs.js` and `StealthPrefList.yaml` (our declarations), `platform/prefs/src/modules/libpref/StealthPrefSanitize.cpp` (the prefix is let through to content processes), the tests `test_stealth_prefs_declared_once.py` and `test_stealth_prefs_final_values.py` beside them, `platform/prefs/FEATURE.md`; the core's checks that read the engine tree run in the job `rebuilds` of `.github/workflows/series.yml`.

**Don't.**
- Rename a `zoom.stealth.*` or `stealthfox.*` pref, or a `STEALTHFOX_*` variable.
- Declare a pref in our files that Mozilla also declares.
- Build a pref name from pieces: the core looks for the whole literal.
