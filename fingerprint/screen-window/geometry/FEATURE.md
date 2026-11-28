# fingerprint/screen-window/geometry

Category: spoof
Prefs: zoom.stealth.screen.width, zoom.stealth.screen.height (the fullscreen rectangle, through gfx::StealthDeclaredScreenRect); the window frame through StealthDeclarationGate
Test: dom/events/test/gtest/TestStealthWindowGeometry.cpp (the declared window at every scale, the popup, fullscreen, the bridged frame, the request that moves the real window by the declared amounts: StealthWindowGeometry.*); dom/ipc/gtest/TestStealthScreenToReal.cpp (StealthScreenToReal.*); dom/ipc/gtest/TestStealthChromeOffset.cpp (StealthChromeOffset.*); juggler/tests/every_parent_site_of_a_screen_coordinate_passes_the_map.test.mjs, juggler/tests/the_screen_map_of_the_parent_is_chrome_only.test.mjs; widget/tests/gtest/TestStealthFullscreen.cpp (StealthFullscreen.TheDeclaredScreenAtTheDeclaredScale, StealthFullscreen.PlacedOnTheScreenTheWindowIsOn, StealthFullscreen.NothingWithoutADeclaredScreenOrAScale, StealthFullscreen.AFullscreenMoveAndResizeLandsOnTheDeclaredRect, StealthFullscreen.TheLargestSizeGrowsToTheDeclaredScreenInFullscreen, StealthFullscreen.TheRectOrTakesTheDeclaredScreenAndElseMozillas); juggler/tests/fullscreen_releases_the_viewport.test.mjs; the fullscreen state of the host gate in the wrapper (scripts/ci_host_gate.py: geometry after a real click on requestFullscreen() and after exitFullscreen(), with its invariants) on every CI host, Linux under Xvfb without a window manager included; the g.fullscreen key of headless_probe.py; gtest:StealthMouseEventIPC.TheIdSurvivesTheMessage (the registration of the header of automation/input); wrapper:tests/test_the_maximized_window_frames_and_popups_read_retail_e2e.py::test_the_maximized_window_frames_and_popups_read_retail[1920x1080-dpr1.25] (the window, the frames and the popups read retail at every scale); wrapper:tests/test_a_select_dropdown_opens_at_its_element_e2e.py::test_a_select_dropdown_opens_at_its_element[1920x1080-dpr1.25]; wrapper:tests/test_input_reaches_the_top_and_a_frame_of_another_site_at_every_scale_e2e.py::test_input_reaches_the_top_and_a_frame_of_another_site (the guard of the snap of the remote layer offset); wrapper:tests/test_a_drag_from_the_top_into_a_frame_of_another_site_e2e.py::test_a_drag_from_the_top_into_a_frame_of_another_site[1920x1080-dpr1.25]; wrapper:tests/test_context_locale_e2e.py::test_intl_in_the_page_realm_follows_the_language_and_zone_of_its_context.

## What it does

The window geometry a page reads comes from the declaration, in every state
the page can drive, and it is declared where Firefox builds it for the content
process: in the parent, in the DimensionInfo that BrowserParent sends. Normal:
the main window is the declared maximized window (outer rect, client offset and
chrome offset), a popup its real inner size plus the declared frame at the
declared position. No content process holds the host's window position, so
Firefox's own code in the child (screenX/Y, outerWidth/Height, mozInnerScreenX/Y,
the screen coordinates of every event) reads the declared values with no
correction of ours. Fullscreen
(requestFullscreen, F11, a popup too): the window is the declared screen, as
on retail (outer == inner == screen, position and content origin 0). The
fullscreen state itself is decided on every host, not by the host's window
manager or monitor: nsIWidget::InfallibleMakeFullScreen fills the declared
screen instead of the host's monitor (Windows, headless), and on X with no
window manager, where GTK refused fullscreen and the widget never left its
size mode (display-mode false, innerHeight the work area), the GTK widget
decides it as Windows and HeadlessWidget do (nsWindow::StealthMakeFullScreenWithoutWM:
the real X window resized to the declared screen, the widget rectangle updated
at once so AppWindow's fullscreen change finishes, then the size mode and the
listener; leaving restores both). It is a member of nsWindow, defined in our
file, because the size mode and the client area are private state that only
OnWindowStateEvent sets; the hook is one call at the head of MakeFullScreen.
Juggler's viewport pin lets go in fullscreen and comes back on leaving.

## Windows fullscreen (2026-11-02)

On Windows a fullscreen window was put back on the HOST's monitor after
InfallibleMakeFullScreen had asked for the declared rectangle: run 41325657085
read innerWidth x innerHeight 1024x768 (the GPU-less CI desktop) under a declared
1280x720 or 1920x1080 screen. Two Mozilla rules decide from the host there:
nsWindow::OnWindowPosChanging forces every move-and-resize of a fullscreen window
onto the monitor's rect (bug 1482920), and DefWindowProc clamps the size to
MINMAXINFO.ptMaxTrackSize, about the monitor's size. Both are answered from the
declaration in fullscreen (widget/windows/StealthFullscreenWin.cpp, thin
adapters over the pure rules StealthHeldFullscreenPosition and
StealthFullscreenMaxTrackSize in widget/StealthFullscreen.cpp). Both read the
size mode from the widget themselves (nsWindow::SizeMode(), which is
mFrameState->GetSizeMode()).

nsWindow::OnWindowPosChanging (Mozilla's, signature as at the tag) holds the
declared rectangle with one line, a pure addition between the forced-fullscreen
block and the DWM block: StealthHoldDeclaredFullscreen(*this, info). The WM_GETMINMAXINFO
hook has to follow Mozilla's four ptMinTrackSize/ptMaxTrackSize assignments (it
takes the maximum of their result and the declared rectangle), so it stays
the last statement of that case block.

## The window origin

dom/ipc/StealthWindowOrigin.h declares the window origin W and the chrome offset T in
the one place Firefox builds them for the content process: BrowserParent::GetDimensionInfo
(Mozilla's body is renamed GetDimensionInfo_Mozilla; the definition on top of it is in
dom/ipc/StealthGetDimensionInfo.h, included by BrowserParent.cpp alone). The arithmetic is
pure and lives in gfx/thebes/StealthDeclarationGate (StealthDeclaredWindowDimensions,
StealthDeclaredClientOrigin, StealthMaximizedWindowTopLeft, StealthRealOuterRequest), where the
gtests call it. The one lookup of the top of a tab (StealthTopBrowserParent) follows the
BrowserBridgeParent chain, so a tab, a popup, an in-process frame and an out-of-process frame
at any depth read the same declaration. A frame bridged to its embedder has no chrome offset of
its own.

A request from the content process (moveTo, resizeTo and the like) is computed from the declared
window, so the parent turns it into the request for the real window (StealthRealDimensionRequest in the
BrowserParent function that passes it on): the real window moves and resizes by the declared amounts, and
a requested position is also the popup's new declared position (the declaration is sent again to
the tab and its frames).

The parent maps back every screen coordinate it gets from content (dom/ipc/StealthScreenToReal.h,
toolkit/modules/StealthScreenMap.sys.mjs): the content computed it from the declared W and T, the
native panel opens on the real screen, so p_real = p_declared - d with d = (declared W + declared T) -
(real W + real T) of the top tab. Nine parent-side sites pass the coordinate through the map (the
context menu, the form validation bubble, the autocomplete popup, the date and colour pickers, the
select dropdown, the Picture-in-Picture toggle, the GenAI chat button and the browser element); the
three methods of CanonicalBrowsingContext that do it are [ChromeOnly], a page has no BrowsingContext
object to ask. The drag image rect goes through the same map (StealthRealDragRect).

The matrix that BrowserParent sends to an out-of-process child and the two drag points that
nsBaseDragService sends carry the chrome offset in declared space (dom/ipc/StealthChromeOffset.h:
StealthSendChildToParentMatrix, StealthDragPoint); the stored matrix is never changed, every input
conversion in the parent stays real. The chrome offset is whole at its birth: the offset of the
remote layer of nsSubDocumentFrame is rounded to device pixels, the same rounding as
BrowserParent::GetChildProcessOffset (layout/generic/StealthRemoteLayerOffset.h,
StealthSnapOffset.h), so a client coordinate is R(x * scale) on every host. Juggler's input origin
is the same whole number (automation/juggler PageHandler._browserOrigin).

The snap equals BrowserParent::GetChildProcessOffset because of two facts of our chrome, not because of an invariant of Mozilla's code: the `<browser>` element has no border or padding, so destRect.TopLeft() is (0, 0), and no transformed ancestor sits above it, so the reference frame is the widget root. The guard that fails as soon as either fact stops being true is wrapper:tests/test_input_reaches_the_top_and_a_frame_of_another_site_at_every_scale_e2e.py::test_input_reaches_the_top_and_a_frame_of_another_site: clientX/Y exactly equal to the requested point, at 4 scales, in the top document and in an out-of-process frame.

A popup's position at birth is declared by fingerprint/screen-window/popup-position and stored on
the top CanonicalBrowsingContext; StealthWindowOrigin reads it from there.

## Hooks in Mozilla files

Registration (an include in a block of ours after Mozilla's includes, an import, or a moz.build line after the closing `]`):
- `dom/ipc/BrowserParent.cpp`: `StealthGetDimensionInfo.h`, `StealthScreenToReal.h`, `StealthChromeOffset.h`. `layout/generic/nsSubDocumentFrame.cpp`: `StealthRemoteLayerOffset.h`. `widget/nsBaseDragService.cpp`: `StealthChromeOffset.h`. `widget/nsIWidget.cpp`: `StealthFullscreen.h`. `widget/windows/nsWindow.cpp`: `StealthFullscreenWin.h`.
- The import of `resource://gre/modules/StealthScreenMap.sys.mjs` in the nine parent-side sites (ContextMenuParent, FormValidationParent, browser.js, GenAI, AutoCompleteParent, InputPickerParentCommon, SelectParent, PictureInPicture, browser-custom-element).
- `docshell/base/CanonicalBrowsingContext.h`: the forward declaration `class DOMRectReadOnly;`. `dom/chrome-webidl/BrowsingContext.webidl`: the three [ChromeOnly] methods of the map.
- `dom/ipc/moz.build` (StealthScreenToReal.cpp), `toolkit/modules/moz.build` (StealthScreenMap.sys.mjs), `dom/ipc/gtest/moz.build` (TestStealthScreenToReal.cpp, TestStealthChromeOffset.cpp, and /dom/ipc and /layout/generic in LOCAL_INCLUDES), `dom/events/test/gtest/moz.build`, `widget/moz.build` (SOURCES, and `EXPORTS.ipc += ["StealthMouseEventIPC.h"]`, marker of automation/input, which owns the file), `widget/gtk/moz.build` (SOURCES, X11 headers), `widget/windows/moz.build` (SOURCES, windows.h), `widget/tests/gtest/moz.build`: build our files and tests.

Wrap of a function (the body keeps Mozilla's code under a new name):
- `dom/ipc/BrowserParent.cpp` and `BrowserParent.h`: BrowserParent::GetDimensionInfo becomes GetDimensionInfo_Mozilla; the function of the old name is ours (StealthGetDimensionInfo.h). BrowserParent.h also names StealthWindowOrigin as a friend (member).

Wrap of an expression or of a call (Mozilla's expression stays, inside our call):
- `dom/ipc/BrowserParent.cpp`: `webBrowserChrome->SetDimensions(StealthRealDimensionRequest(this, std::move(aRequest)))` in the request from the content process; `StealthSendChildToParentMatrix(this, ToUnknownMatrix(aMatrix), aRemoteDocumentRect)` in the matrix send; `StealthRealDragRect(this, aDragRect)` in the argument of the drag start.
- `widget/nsBaseDragService.cpp`: `StealthDragPoint(bp, mEndDragPoint)` and `StealthDragPoint(mDelayedDropBrowserParent, <the ref point of the event>)` in the two drag points that are sent to the child.
- `layout/generic/nsSubDocumentFrame.cpp`: `mOffset = StealthRemoteLayerOffset(mFrame, <Mozilla's expression>)`.
- `widget/nsIWidget.cpp`, nsIWidget::InfallibleMakeFullScreen: `doReposition(StealthFullscreenRectOr(*this, DesktopRect(screen->GetRectDisplayPix())))`. With the engine off, or without a declared screen, it is Mozilla's rectangle; otherwise doReposition receives the declared rectangle and Mozilla's next statement (save the new position) does what the old early return did by hand.
- In JavaScript (the form wrap-expression, or rewire for a statement that reassigns a local): the nine parent-side sites pass the value Mozilla read from the content message through StealthScreenRectToReal, StealthContextScreenToReal, StealthScreenXDevPxToReal or StealthScreenYDevPxToReal, with the BrowsingContext of the actor or of the browser.

Addition (a call between two Mozilla blocks):
- `widget/windows/nsWindow.cpp`, nsWindow::OnWindowPosChanging: `mozilla::widget::StealthHoldDeclaredFullscreen(*this, info);` between the forced-fullscreen block and the DWM block; nsWindow.h is the tag's.

Member:
- `docshell/base/CanonicalBrowsingContext.h`: the three methods of the map (StealthScreenRectToReal, StealthScreenXDevPxToReal, StealthScreenYDevPxToReal, defined in dom/ipc/StealthScreenToReal.cpp). The members of the popup's position are the hooks of fingerprint/screen-window/popup-position in the same file.
- `widget/gtk/nsWindow.h`: declares nsWindow::StealthMakeFullScreenWithoutWM (defined in widget/gtk/StealthFullscreenGtk.cpp). The call, `if (StealthMakeFullScreenWithoutWM(aFullScreen)) return NS_OK;` inside Mozilla's `if (GdkIsX11Display() && !IsFullscreenSupported(mShell)) {` block of `widget/gtk/nsWindow.cpp` (nsWindow::MakeFullScreen), is in this folder, byte for byte the form fingerprint/screen-window/occlusion carries too (G48).

Anchor (a call right after a Mozilla statement, listed with its reason in HOOKS.json):
- `widget/windows/nsWindow.cpp`, case WM_GETMINMAXINFO: after the four ptMinTrackSize/ptMaxTrackSize assignments, the last statement of the block (the one exception of rule 5, G30).

Fractional host chrome offset: it is a host dependence and it dies at birth. The chrome offset of the remote layer is rounded where it is born (nsSubDocumentFrame), and what the parent sends for the child is declared, so any transform and any host chrome offset give retail's value.

No hook is a declared exception.
