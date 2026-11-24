# platform/prefs

Category: other, prefs
Prefs: browser.translations.select.enable, font.size.monospace.ar, font.size.monospace.el, font.size.monospace.he, font.size.monospace.x-cyrillic, font.size.monospace.x-unicode, font.size.monospace.x-western, invisible_firefox.usage_ping.enabled, invisible_firefox.usage_ping.url, juggler.locale.override, juggler.timezone.override, network.proxy.socks_password, network.proxy.socks_username, termsofuse.acceptedDate, termsofuse.acceptedVersion, ui.font.-moz-button, ui.font.-moz-button.size, ui.font.-moz-field, ui.font.-moz-field.size, ui.font.-moz-list, ui.font.-moz-list.size, ui.font.-moz-pull-down-menu, ui.font.-moz-pull-down-menu.size, ui.font.caption, ui.font.caption.size, ui.font.icon, ui.font.icon.size, ui.font.menu, ui.font.menu.size, ui.font.message-box, ui.font.message-box.size, ui.font.small-caption, ui.font.small-caption.size, ui.font.status-bar, ui.font.status-bar.size, zoom.stealth., zoom.stealth.audio.fp_noise, zoom.stealth.audio.max_channel_count, zoom.stealth.audio.output_latency_ms, zoom.stealth.audio.sample_rate, zoom.stealth.branding.archive, zoom.stealth.canvas.edge_tolerance, zoom.stealth.canvas.substitute_pixels, zoom.stealth.focus.ignore_os_deactivation, zoom.stealth.font.fontlist, zoom.stealth.font.system_ui, zoom.stealth.fonts.generics, zoom.stealth.fonts.manifest, zoom.stealth.fpp.hw_seed, zoom.stealth.hw_concurrency, zoom.stealth.max_touch_points, zoom.stealth.media.decode_support, zoom.stealth.media.decoding_info, zoom.stealth.media.enumeration_ms, zoom.stealth.pointer.all, zoom.stealth.pointer.primary, zoom.stealth.screen.avail_device_height, zoom.stealth.screen.avail_device_width, zoom.stealth.screen.color_depth, zoom.stealth.screen.frame_border, zoom.stealth.screen.height, zoom.stealth.screen.maximized_ui, zoom.stealth.screen.popup_position, zoom.stealth.screen.popup_ui, zoom.stealth.screen.taskbar_px, zoom.stealth.screen.width, zoom.stealth.storage.quota_mb, zoom.stealth.text.coverage_ladder, zoom.stealth.text.freetype_antialias, zoom.stealth.text.freetype_hintstyle, zoom.stealth.text.system_quality, zoom.stealth.voices.list, zoom.stealth.webgl.extensions, zoom.stealth.webgl.float_params, zoom.stealth.webgl.int2_params, zoom.stealth.webgl.int_params, zoom.stealth.webgl.renderer, zoom.stealth.webgl.shader_output_language, zoom.stealth.webgl.shader_precisions, zoom.stealth.webgl.vendor, zoom.stealth.webgl2.extensions, zoom.stealth.widget.occlusion_tracking.enabled
Test: modules/libpref/test/test_stealth_prefs_declared_once.py (no pref of ours declared twice), modules/libpref/test/test_stealth_prefs_final_values.py (final values in load order, our defaults reach it through greprefs.js, the generator gets our list and group; each with the stock-Firefox reader as negative control), modules/libpref/test/gtest/TestStealthPrefSanitize.cpp (gtest StealthPrefSanitize.*: the prefix is allowed, names outside it are not), juggler/tests/geolocation_network_url_is_empty_by_default.test.mjs (geo.provider.network.url line)

## What it does

Pref values we change on the line where Mozilla declares them (translations off, monospace 13 on the Unix block, empty geo.provider.network.url on Linux), plus the lines that make the browser read our defaults: greprefs.js includes StealthPrefs.js after all.js (so our defaults win), moz.build adds StealthPrefList.yaml as a second generator input and the "juggler" group to pref_groups, and "zoom.stealth." is let through to content processes by Preferences.cpp.

## Hooks in Mozilla files

- `browser/app/profile/firefox.js`: `pref("browser.translations.enable", false);` and `pref("browser.translations.select.enable", false);` (declared-value, one line each). Mozilla declares both twice (all.js false, firefox.js true, firefox.js loaded last); with false on firefox.js's own line the final value is false, as with all.js alone. See the section below.
- `modules/libpref/greprefs.js`: `#include init/StealthPrefs.js` after `#include init/all.js` (registration). The marker is the line before: the preprocessor takes the rest of an `#include` line as the file name, so a trailing marker would break the include.
- `modules/libpref/moz.build`: `pref_groups += ["juggler"]` after the closing bracket of the list (Mozilla sorts the tuple below, so the position is irrelevant) and `gen_inputs += ["init/StealthPrefList.yaml"]` after Mozilla's one-line `gen_inputs` (registration).
- `modules/libpref/init/all.js`: six `font.size.monospace.*` values 12 -> 13 on Mozilla's lines of the Unix-only block (declared-value; Windows keeps the global 13), and `geo.provider.network.url` empty (declared-value; its marker names fingerprint/geolocation/no-host-provider, which owns that hook and its test).
- `modules/libpref/Preferences.cpp`: `#include "StealthPrefSanitize.h"` in a block of ours, and `if (StealthPrefAllowedInContent(aPref->Name())) return false;` in `ShouldSanitizePreference`, right after Mozilla's diagnostic assert (guard as anchor: the assert must keep running for every name). It replaces the `"zoom.stealth."` entry that sat first in `sDynamicPrefOverrideList` (allowlist of dynamically named string prefs for content processes). Same answer for every pref: a name with that prefix is not a `$$$` pref, no entry of `sRestrictFromWebContentProcesses` is a prefix of it (none starts with or is a prefix of `zoom.stealth.`), and the dynamic-string branch answered false through the override entry; every other branch answered false too. The function is in `modules/libpref/StealthPrefSanitize.cpp/.h`, with the explanation.
- `modules/libpref/moz.build`: also `UNIFIED_SOURCES += ["StealthPrefSanitize.cpp"]` after Mozilla's list. `modules/libpref/test/gtest/moz.build`: `UNIFIED_SOURCES += ["TestStealthPrefSanitize.cpp"]` after Mozilla's list.

## Values changed on Mozilla's own lines (2026-10-29)

No pref of ours is declared twice: a Mozilla pref whose value we change is
changed on the line where Mozilla declares it, marked
`// STEALTH-HOOK(platform/prefs)` at the end of the line, and our files declare
only prefs Mozilla does not have (modules/libpref/init/StealthPrefs.js, included
by greprefs.js; StealthPrefList.yaml for static prefs). Enforced by
modules/libpref/test/test_stealth_prefs_declared_once.py.

### First run (terms of use, data-reporting notice)

Moved to the core on 2026-11-02: invisible_core declares the first-run state on every host (browser.preonboarding.enabled false, termsofuse.acceptedVersion 4, termsofuse.acceptedDate, in user.js before the window exists; measured on official 159: with the two termsofuse prefs neither the terms-of-use modal nor the legacy data-reporting notice appears). The engine leaves Mozilla's lines: tools/tests/test_first_run_is_the_cores.py.

### browser/app/profile/firefox.js: browser.translations.enable and browser.translations.select.enable

firefox.js declared both true and is loaded after all.js, so it won. The two lines
now say `false` on Mozilla's own lines, marked; the final value is all.js's
`false` and nothing of ours declares the pref.

STEALTHFOX: translations stay at Gecko's default, which is OFF
(`modules/libpref/init/all.js` declares them false; it is firefox.js that
turns them on). A browser that drives a page translates nothing.

What they cost, measured on 2026-08-14 on Linux with about:memory dumped via
SIGRTMIN. TranslationsParent detects the language of EVERY page loaded, and to
do so it instantiates the worker of the CLD2 detector: `cld-worker.js` holds
**17.75 MB** of ArrayBuffer in the parent process, which is 17.3 of the 19.4 MB
of all the chrome workers put together. Three pairs of interleaved measurements
on the parent heap - 255.0/232.3, 276.0/276.0->229.0, 307.3/291.8 - give three
differences, all negative, mean **-28.4 MB**, and the smallest (-15.5) is the
size of the worker itself.

⛔ And here the form of the correction is a PREF and not a cut in the code,
unlike about:newtab, for a measured reason and not for convenience: the flag
works. With the pref at its default the worker is not born - 0.00 MB in three
runs out of three - whereas browser.newtabpage.enabled let about:home load the
add-on all the same. Where Firefox's flag really covers the feature, cutting
deeper would add divergence from upstream for zero extra MB.

Not observable from a page: translation is chrome interface, no web API
exposes it, and not detecting the language changes nothing of what the page
can read.

### modules/libpref/init/all.js: font.size.monospace.{ar,el,he,x-cyrillic,x-unicode,x-western} 13

In the `#if !defined(ANDROID) && !defined(XP_MACOSX) && defined(XP_UNIX)` block.

STEALTH: all.js sets these to 12 on desktop Unix while Windows keeps the
global 13. This build claims Windows, and the difference is directly
observable - a font-size-less monospace span measured 121.583px on
Windows vs 112.233 on Linux (ratio 13/12). Kept at the Windows value, under
the same condition as the Mozilla lines they replace.
