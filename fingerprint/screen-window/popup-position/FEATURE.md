# fingerprint/screen-window/popup-position

Category: spoof
Prefs: none read directly (the declared window frame comes from the core through `StealthDeclaredWindowFrame()`)
Test: wrapper `tests/test_the_maximized_window_frames_and_popups_read_retail_e2e.py::test_the_maximized_window_frames_and_popups_read_retail[1920x1080-dpr1.25]` (the popup position and frame at every scale), `tests/test_popup_geometry_is_the_declared_frame_e2e.py::test_a_popup_is_its_inner_size_plus_the_declared_frame` (neither left nor top); the only-left case has no test yet (to be added to that file by the characterization stream, green on firefox-68); `tests/test_popup_pages.py`; node `juggler/tests/explicit_size_flag_is_free.test.mjs` (bit of the explicit-size flag, shared with automation/window-size)

## What it does

A window a page opens without `left`/`top` is born at the declared default position, not wherever the host puts it: retail Firefox on Windows 11 opens it at 4,4 device pixels (3,3 CSS at 125%, 2,2 at 200%), while the host would put it anywhere (Windows staggers from the opener, a bare X server has no window manager at all) and a popup's `screenX`/`screenY` is its REAL position (`nsGlobalWindowOuter::GetScreenXY`). The default is applied at the birth of the window, so both builds have the same real position and nothing corrects it afterwards. A position the page does give needs nothing: `CalcSizeSpec` has already turned its CSS pixels into desktop pixels with the opener's own CSS-to-desktop scale (measured on the Linux build at 1.25, 1.5 and 2: a second conversion put `left=100` at `screenX` 125, 150 and 200). Chrome callers and the engine-off case keep the stock behaviour.

The logic is `StealthPlacePopupAtDefault` in `toolkit/components/windowwatcher/StealthWindowPlacement.{h,cpp}`. The file `nsWindowWatcher.cpp` also carries the hook of `automation/window-size` (the flag of an explicit popup size, `JugglerPopupChromeFlags` in `JugglerWindowSize.{h,cpp}`); this folder owns the file.

## Hooks in Mozilla files

All in `toolkit/components/windowwatcher/nsWindowWatcher.cpp`:

- Registration: two includes in a block of ours after `#include "ReferrerInfo.h"`: `JugglerWindowSize.h` (marker of automation/window-size) and `StealthWindowPlacement.h`.
- `nsWindowWatcher::CalculateChromeFlagsForContent`, the popup branch of the ternary: wrap-expression `mozilla::JugglerPopupChromeFlags(aFeatures, nsIWebBrowserChrome::CHROME_MINIMAL_POPUP)` around Mozilla's operand (marker of automation/window-size, comment line above as at its branch): the function ORs our bit into Mozilla's flags and follows them if Mozilla changes them. It uses the two-argument overload of `JugglerWindowSize.{h,cpp}` that automation/window-size adds; this branch is rebased on hooks/automation__window-size.
- `SizeOpenedWindow`, one anchor right after Mozilla's `bool positionSpecified = aSizeSpec.PositionSpecified();`: `mozilla::StealthPlacePopupAtDefault(aIsCallerChrome, treeOwnerAsWin, aSizeSpec, left, top, positionSpecified);`. It writes left/top only when absent and, when it placed the popup, sets `positionSpecified` through its `bool&` parameter, so the caller treats the declared position as specified; Mozilla's line is untouched. It needs `left`, `top`, `treeOwnerAsWin` and `positionSpecified`, locals of Mozilla's function, so a guard at the head of the function finds them unborn. The code between the left/top set-up and the anchor (the width/height set-up) reads and writes only width, height and the chrome sizes.

- `docshell/base/CanonicalBrowsingContext.h`, three members: `mStealthPopupPosition` (the popup's declared position in device pixels, born with the window, set by `StealthSetPopupPosition`) and its accessor `StealthPopupPosition()`. The window origin of fingerprint/screen-window/geometry reads it; the real window's position is never read.

Port note: the anchor needs Mozilla's left/top set-up to stay before the `positionSpecified` declaration, `positionSpecified` to be declared from `aSizeSpec.PositionSpecified()`, and the statements between them to leave left, top and `positionSpecified` alone.
