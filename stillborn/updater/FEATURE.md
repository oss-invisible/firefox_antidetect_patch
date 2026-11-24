# stillborn/updater

Category: stillborn
Prefs: app.update.interval, app.update.promptWaitTime, app.update.url.manual, app.update.url.details, app.update.checkInstallTime.days, app.update.badgeWaitTime (values only)
Test: juggler/tests/updater_refuses_what_follows_the_check.test.mjs (the heads of the two guarded functions and the check run from
Mozilla's real text on stubs, each with a negative control; the entry guards; the cadence; our functions);
scripts/validate_release.py --selftest (assert_updater_is_retails)

## What it does

The application update system is the retail's, minus what would change the
installed browser or the host (owner's decision, 2026-10-30: "as official,
without installing").

- `build/moz.configure/update-programs.configure` is Mozilla's file: the
  updater, the maintenance service and the update agent are compiled and
  packaged as in a release. `.mozconfig` passes the retail's MAR channel
  (`firefox-mozilla-release`), which Mozilla passes from its CI environment.
- The update check to aus5.mozilla.org goes out as official Firefox sends it:
  same timer, same URL, same headers.
- `toolkit/mozapps/update/StealthUpdate.sys.mjs` refuses what follows the
  answer:
  - `noneOffered(updates)` is called in the line after the `try/catch` of `CheckerService.#updateCheck`, on what Mozilla's
    `updates = this.#parseUpdates(request);` produced, and returns a new empty array whatever the answer offered (every
    consumer then takes Mozilla's own no-update path: no prompt, no badge, no download). Mozilla's parse line is as in the
    tag, and a parse error still goes to the `catch` as always; the request has already gone out unchanged.
  - `refusesDownload()` is the guard in `#downloadUpdate`, the one door of every download (a fresh offer, a download resumed
    from an earlier session, the fallback to a complete update; backstop for a download another build left half done at the
    same install path; an update it already staged is applied by the C++ driver at startup, not covered). It stands after
    Mozilla's own `if (!update) throw NS_ERROR_NULL_POINTER`, as before: no update still throws, and any real download gets
    `DOWNLOAD_FAILURE_GENERIC`.
  - `refusesHostTask()` is the guard at the head of `BackgroundUpdate._registerBackgroundUpdateTask`, the only place a browser
    run registers the Windows "Background Update" scheduled task. Mozilla's own statements after it are the ones that register
    it; they do not run.
- We build with the unofficial branding, whose update timings are Nightly-like
  (a check every 24 h, and one at every start once the build is 2 days old).
  Its lines carry the official branding's release values instead, on Mozilla's own lines: the interval is 21600 (6 hours,
  the release value; Mozilla's comment "24 hours" on that line is gone because it would be false), the user is given 691200
  seconds before the big prompt and 345600 before the badge, a binary may be 63 days old without a check, and the manual
  and details URLs are the release pages (`https://www.mozilla.org/%LOCALE%/firefox/new?reason=manual-update` and
  `.../firefox/notes`).

From 2026-08-31 to 2026-10-30 the update options were deleted from the
configure file instead: no updater was built and the check official Firefox
makes at startup never went out.

Gate: `scripts/validate_release.py` `assert_updater_is_retails` refuses a
package without the updater binary, without the retail's MAR channel in
`update-settings.ini`, or whose `UpdateService.sys.mjs` lacks our refusals
(it looks for the bytes `StealthUpdate.noneOffered(` and `StealthUpdate.refusesDownload(`, which the hooks still contain).

## Hooks in Mozilla files

- `toolkit/mozapps/update/UpdateService.sys.mjs`: the import, in a block of ours after Mozilla's imports (registration);
  `if (StealthUpdate.refusesDownload()) return Ci.nsIApplicationUpdateService.DOWNLOAD_FAILURE_GENERIC;` in `#downloadUpdate`,
  right after Mozilla's `if (!update) throw` (one line);
  `updates = StealthUpdate.noneOffered(updates);` as the line after the `try/catch` of `#updateCheck` (anchor; Mozilla's
  `updates = this.#parseUpdates(request);` is as in the tag).
- `toolkit/mozapps/update/BackgroundUpdate.sys.mjs`: the import, in a block of ours after Mozilla's imports (registration);
  `if (StealthUpdate.refusesHostTask()) return null;` as the first statement of `_registerBackgroundUpdateTask` (guard).
- `toolkit/mozapps/update/moz.build`: our module, after Mozilla's list.
- `browser/branding/unofficial/pref/firefox-branding.js`: six update prefs, each on Mozilla's line with the release value and
  the marker (declared value); nothing else on those lines.

## Our own files

- `toolkit/mozapps/update/StealthUpdate.sys.mjs` (`noneOffered`, `refusesDownload`, `refusesHostTask`).
- Test: `juggler/tests/updater_refuses_what_follows_the_check.test.mjs`.
