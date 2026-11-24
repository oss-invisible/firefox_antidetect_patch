# Next: Firefox 160.0.1, measured against the series

This page records what is known about moving the series from the Mozilla tag `FIREFOX_159_0_RELEASE` to `FIREFOX_160_0_1_RELEASE`. The measure was taken with the method of `tools/engine.py drift` (hunk-level three-way comparison) on the series at 4a24f64a7c9a. Each hunk of the series falls in one of four classes:

- **intact**: Mozilla did not touch the file region; the hunk applies unchanged.
- **moved clean**: the region moved, but the hunk's old side still matches at 160; it applies at the new position.
- **merged**: Mozilla changed lines within 3 lines of the hunk, and a three-way merge combines both changes.
- **conflict**: Mozilla changed the same lines or the same insertion point; the hunk needs a decision.

## Totals

| | Series at 4a24f64a7c9a |
|---|---|
| Hunks | 794 |
| Mozilla files touched | 339 |
| Additions / rewrites / deletions | 587 / 204 / 3 |
| Intact | 401 |
| Moved clean | 341 |
| Merged | 39 |
| Conflicts | 13 |
| Conflict rate, all hunks | 1.64% |
| Conflict rate, hunks in files Mozilla changed (393) | 3.3% |

By kind, conflicts over all hunks: additions 5 of 587 (0.85%), rewrites 8 of 204 (3.9%), deletions 0 of 3. Without the `fingerprint/webgpu` folder: 6 conflicts in 685 hunks (0.9%). Six folders hold a conflict.

Every conflict has a Mozilla change within 3 lines; every hunk with no Mozilla change that near applies cleanly.

## The 13 conflicts

"Where our line can go" gives an alternative position that would avoid the conflict; it is stated only where one has been worked out.

| # | Folder | Mozilla file | Hunk | Kind | What Mozilla did | Where our line can go |
|---|---|---|---|---|---|---|
| 1 | `network/proxy-udp` | `netwerk/socket/nsSOCKSIOLayer.cpp` | 2 | rewrite | Added `mProxyConnectAttempted = true;` right above the `connect()` call we rewrite (`IsInProgress()` also replaces the errno test below). | Not worked out. |
| 2 | `automation/navigation` | `docshell/base/nsDocShell.cpp` | 7 | add | Removed `nsDocShell::OnLinkClickWithLoadState`; the line our `StealthLinkClickBefore` hook sits in no longer exists. | None: the hook has no place at 160 and needs a new design. |
| 3 | `fingerprint/js-surface/branding` | `security/sandbox/linux/broker/SandboxBrokerPolicyFactory.cpp` | 1 | add | Added `#include <memory>` at the same spot as our include: after the last `#endif` of the include list, before `namespace mozilla`. | Directly after a Mozilla include that is not the last of the list (an anchored registration), so one untouched line separates it from the tail where Mozilla adds. Keep both lines. |
| 4 | `fingerprint/js-surface/debugger` | `devtools/shared/heapsnapshot/tests/gtest/moz.build` | 1 | add | Added a `SOURCE_HEADERS += [...]` block after `FINAL_LIBRARY`, at the end of the file where our `UNIFIED_SOURCES += [...]` line goes. | Directly after the closing `]` of Mozilla's `UNIFIED_SOURCES` list (the registration form), not at the end of the file. Keep both lines. |
| 5 | `fingerprint/js-surface/debugger` | `js/src/debugger/Debugger.cpp` | 2 | rewrite | `globalDebuggers.append(Realm::DebuggerVectorEntry(...))` became `emplaceBack(this, debuggeeLink)` on the line we rewrite. | Not worked out. |
| 6 | `fingerprint/screen-window/occlusion` | `widget/gtk/nsWindow.cpp` | 3 | add | The static `IsFullscreenSupported(GtkWidget*)` became a member `IsFullscreenSupported()` and the `MakeFullScreen` guard our hook sits in was rewritten. Merging also breaks compilation. | Not worked out. |
| 7 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/naga-types/.cargo-checksum.json` | 1 | rewrite | Vendored wgpu sync: Mozilla regenerated the one-line checksum JSON. | Not a position problem: regenerate our checksum, do not merge. |
| 8 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/naga/.cargo-checksum.json` | 1 | rewrite | Same as 7. | Same as 7. |
| 9 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/wgpu-core/.cargo-checksum.json` | 1 | rewrite | Same as 7. | Same as 7. |
| 10 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/wgpu-hal/.cargo-checksum.json` | 1 | rewrite | Same as 7. | Same as 7. |
| 11 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/wgpu-types/.cargo-checksum.json` | 1 | rewrite | Same as 7. | Same as 7. |
| 12 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/wgpu-hal/src/vulkan/adapter.rs` | 1 | add | Added `features.set(F::DEBUG_PRINTF, ...)` at the same place after the feature list as our `features.insert(EXTERNAL_TEXTURE)`. | Not worked out. |
| 13 | `fingerprint/webgpu/external-texture-vulkan` | `third_party/rust/wgpu-hal/src/vulkan/device.rs` | 8 | rewrite | Refactored the descriptor-write code (`buffer_infos`/`local_buffer_infos`, an `add_image_descriptor_writes` helper) inside the block our rewrite replaces. | Not worked out. |

## Other port work

- **Backport leaves the series.** The Mozilla-commit backport `platform/backports/fontconfig-face-index` is already in the 160 tag, so it is removed from the series.
- **Births ledger against 160.** The network births ledger is red against 160: 2 entries are new, 4 changed, 1 invalid. The files involved are `nsNetUtil`, `EarlyHintPreloader`, `SpeculationRules`, `nsAuthSSPI`, `network-content.js` and `services/sync`; each is to be examined one by one.
- **Headers and modules we include.** 65 Mozilla headers or modules that our own files include changed (none vanished). The most moved are `gfx/2d/DrawTargetRecording.h`, `RecordedEventImpl.h`, `dom/base/Document.h`, `WebGLContext.h`, `nsHttpHandler.h`, `xpcprivate.h` and `nsDocShell.h`. Compile errors from these show only when compiling.
- **Retail-measured values.** Values measured on retail Firefox must be confirmed again on 160. The window frame has already been measured on 160.0.1.

## Limits of the measure

- "Moved clean" only means the old side of the hunk still matches at 160. Two hunks (the media decoder factory include and the WebGL validation include) pass because their anchor changed, not because those spots are safe.
- The method does not see compile breaks, nor changes in our own files (conflict 6 is an example).
