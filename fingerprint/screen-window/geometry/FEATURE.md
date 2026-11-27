# fingerprint/screen-window/geometry

Category: spoof
Prefs: zoom.stealth.screen.width, zoom.stealth.screen.height (the fullscreen rectangle, through gfx::StealthDeclaredScreenRect); the window frame through StealthDeclarationGate
Test: dom/events/test/gtest/TestStealthWindowGeometry.cpp (StealthWindowGeometry.FullscreenContentStartsAtTheScreenOrigin, StealthWindowGeometry.OutsideFullscreenNothingChanges); widget/tests/gtest/TestStealthFullscreen.cpp (StealthFullscreen.TheDeclaredScreenAtTheDeclaredScale, StealthFullscreen.PlacedOnTheScreenTheWindowIsOn, StealthFullscreen.NothingWithoutADeclaredScreenOrAScale); juggler/tests/fullscreen_releases_the_viewport.test.mjs; the fullscreen state of the host gate in the wrapper (scripts/ci_host_gate.py: geometry after a real click on requestFullscreen() and after exitFullscreen(), with its invariants) on every CI host, Linux under Xvfb without a window manager included; the g.fullscreen key of headless_probe.py. widget/tests/gtest/TestStealthFullscreen.cpp also holds StealthFullscreen.AFullscreenMoveAndResizeLandsOnTheDeclaredRect and StealthFullscreen.TheLargestSizeGrowsToTheDeclaredScreenInFullscreen (the Windows rules); the host gate invariant fullscreen_is_the_screen on win-x86_64 is their end-to-end proof. Added: widget/tests/gtest/TestStealthFullscreen.cpp StealthFullscreen.TheRectOrTakesTheDeclaredScreenAndElseMozillas (the rectangle the widget moves to: declared, else Mozilla's); gtest:StealthMouseEventIPC.TheIdSurvivesTheMessage (the registration of the header of automation/input); wrapper e2e (to be written) tests/test_popup_geometry_is_the_declared_frame_e2e.py::test_a_popup_is_its_inner_size_plus_the_declared_frame and tests/test_a_click_in_an_iframe_lands_at_the_frames_own_screen_origin_e2e.py::test_a_real_click_in_an_iframe_has_the_screen_origin_of_the_iframe, and tests/test_context_locale_e2e.py::test_intl_in_the_page_realm_follows_the_language_and_zone_of_its_context (the language and zone hook that stays in this file).

## What it does

The window geometry a page reads comes from the declaration, in every state
the page can drive. Normal: the main window is the declared maximized window
(outer size, screenX/Y, the content origin under mozInnerScreenX/Y and every
mouse event), a popup its real inner size plus the declared frame. Fullscreen
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

### A main window resized by setViewportSize (2026-11-27)
Page.setViewportSize resizes the main window the way Juggler does on retail Windows Firefox: resizeBy on the outer size, which restores a maximized window. Measured on retail 159.0 (core workflow retail-window-geometry.yml, four rounds, scales 1/1.25/1.5/2 live), and declared by the core (prefs zoom.stealth.screen.ui_normal, ui_compact, compact_below_css, restored_position, min_inner_width_css, min_inner_height_css, with the existing frame_border and maximized_ui):
- The restored window sits at (restored_position, restored_position) = (4, 4) device px.
- Its chrome is at least min_inner_width_css x min_inner_height_css (500 x 120 CSS). A 390-wide content therefore sits in a window 500 CSS wide.
- The resize border is the maximized window's (frame_border). The bar above the content is ui_normal or ui_compact: Firefox 159 turns compact when the chrome is below compact_below_css (720 CSS) high, and re-decides this after every resize.
- The first resize from the maximized window turns the top border into space under the content (one border more than later resizes). A restored window is never maximized again by a resize.
- outerWidth/outerHeight, screenX/Y, mozInnerScreenX/Y and every event's screenX - clientX come from one state: StealthWindowState on the top BrowsingContext (carried across a BrowsingContext replacement by the line in CanonicalBrowsingContext::ReplacedBy). It moves only on Juggler's notification: juggler/TargetRegistry.js sends "stealth-viewport-resize" (the page's BrowsingContext and the requested CSS size) right before its resizeBy, and a parent-process observer (gfx/thebes/StealthViewportResizeObserver.cpp, registered from StealthEngineActive) computes the state with the declared scale through the pure gfx::StealthWindowStateAfterViewportResize (Juggler's arithmetic: truncated CSS deltas on fractional chrome sizes, outer rounded to CSS, back to device with RoundedToInt). A change of the top-level inner size (the first layout, fullscreen) is not a resize and leaves the state alone; a popup is declared from its own frame.

A repeated setViewportSize to the same size is a Juggler call like any other: the engine answers Juggler's arithmetic (the outer height shrinks by one border, 945 -> 937 CSS at 100% for 390x844). On retail, the repeat of the SECOND call is measured (round 5 of retail-window-geometry, core run 45952171443, step juggler2_repeat): nothing changes at any scale, as the engine answers; the repeat of the FIRST call is still being measured, and 937 stays Juggler's arithmetic until its run id replaces the comment in the test.

Test: dom/events/test/gtest/TestStealthWindowGeometry.cpp (TheFirstResizeAtEveryDomainScale, TheSecondResizeAtEveryDomainScale, TheWayBackAtEveryDomainScale: 15 measured points; TheViewportResizeNotificationMovesTheTopContextField, TheFirstLayoutLeavesTheFieldAlone, FullscreenLeavesTheFieldAlone, TheViewportResizeDataIsTwoDecimalIntegers, ARepeatedResizeToTheSameSizeAnswersJugglersArithmetic, TheRepeatOfTheSecondResizeChangesNothingAtEveryDomainScale, and the per-path, density-flip and minimum-width tests); wrapper:tests/test_a_restored_window_reads_the_retail_frame_after_set_viewport_size_e2e.py::test_a_restored_window_reads_the_retail_frame_after_set_viewport_size[1920x1080-dpr1.0] and ::test_the_restored_state_survives_a_browsing_context_replacement.

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

## The content origin

dom/events/StealthScreenCoords.h holds StealthContentOriginShift, the ONE
function that gives the declared content origin: mozInnerScreenX/Y
(StealthWindowGeometry.h) and every mouse event (Event::GetScreenCoords, through
StealthWithContentOrigin) both ask it, so event.screenX - event.clientX ==
mozInnerScreenX holds in the main window, in popups and in out-of-process
iframes (a subframe adds the shift to its OWN rectangle). It is arithmetic and
widget queries only: Event::GetScreenCoords is the hot path of every trusted
mouse and wheel event. The sum stays in integer app units, in Mozilla's order,
and is converted to CSS pixels once, by Mozilla's FromAppUnits.

## Hooks in Mozilla files

Registration (an include in a block of ours after Mozilla's includes, or a moz.build line after the closing `]`):
- `dom/base/nsGlobalWindowOuter.cpp`: `StealthWindowGeometry.h` (this folder) and `mozilla/dom/StealthSessionDeclaration.h` (marker of fingerprint/locale-time/session-declaration, which owns the function; the file is ours).
- `dom/events/Event.cpp`: `StealthScreenCoords.h`. `widget/nsIWidget.cpp`: `StealthFullscreen.h`. `widget/windows/nsWindow.cpp`: `StealthFullscreenWin.h`.
- `widget/moz.build` (SOURCES, and `EXPORTS.ipc += ["StealthMouseEventIPC.h"]`, marker of automation/input, which owns the file), `widget/gtk/moz.build` (SOURCES, X11 headers), `widget/windows/moz.build` (SOURCES, windows.h), `widget/tests/gtest/moz.build`, `dom/events/test/gtest/moz.build`: build our files and tests.

Wrap of an expression (Mozilla's expression stays, inside our call):
- `widget/nsIWidget.cpp`, nsIWidget::InfallibleMakeFullScreen: `doReposition(StealthFullscreenRectOr(*this, DesktopRect(screen->GetRectDisplayPix())))`. With the engine off, or without a declared screen, it is Mozilla's rectangle; otherwise doReposition receives the declared rectangle and Mozilla's next statement (save the new position) does what the old early return did by hand.
- `dom/events/Event.cpp`, Event::GetScreenCoords: `... + StealthWithContentOrigin(aPresContext, <Mozilla's last summand>)` inside Mozilla's FromAppUnits: one added opening line and one Mozilla line rewritten (the last, which closes the call), the marker on it. Integer addition: A + (B + shift) is (A + B) + shift.

Addition (a call between two Mozilla blocks):
- `widget/windows/nsWindow.cpp`, nsWindow::OnWindowPosChanging: `mozilla::widget::StealthHoldDeclaredFullscreen(*this, info);` between the forced-fullscreen block and the DWM block; nsWindow.h is the tag's.

Member:
- `widget/gtk/nsWindow.h`: declares nsWindow::StealthMakeFullScreenWithoutWM (defined in widget/gtk/StealthFullscreenGtk.cpp). The call, `if (StealthMakeFullScreenWithoutWM(aFullScreen)) return NS_OK;` inside Mozilla's `if (GdkIsX11Display() && !IsFullscreenSupported(mShell)) {` block of `widget/gtk/nsWindow.cpp` (nsWindow::MakeFullScreen), is in this folder, byte for byte the form fingerprint/screen-window/occlusion carries too (G48).

Anchors (a call right after a Mozilla statement, listed with their reason in HOOKS.json):
- `dom/base/nsGlobalWindowOuter.cpp`: GetOuterSize and GetScreenXY after Mozilla's resistFingerprinting check (GetScreenXY after the tree-owner check too, passing its local), GetMozInnerScreenXOuter/YOuter after `nsRect r = GetInnerScreenRect();`. A guard at the head of these functions would answer before Mozilla's resistFingerprinting check, which the core only defaults to false (an extra_prefs overlay can turn it on), so they stay where they are.
- `widget/windows/nsWindow.cpp`, case WM_GETMINMAXINFO: after the four ptMinTrackSize/ptMaxTrackSize assignments, the last statement of the block (the one exception of rule 5, G30).

Rewritten line, a declared exception of kind expression (approved by the pm):
- `dom/base/nsGlobalWindowOuter.cpp`, CreateNativeGlobalForInner: the two arguments `Top()->GetLanguageOverride()` / `GetTimezoneOverride()` of `xpc::InitGlobalObjectOptions` are replaced by `GetDeclaredRealmLanguage(aDocument), GetDeclaredRealmTimezone(aDocument)` with a marker comment line of fingerprint/locale-time/session-declaration, which owns the functions. They are the document's context language and zone, or the session's when the context carries none, including a document with no BrowsingContext. Mozilla's two expressions dereference the BrowsingContext and are evaluated before any code of ours, so a wrap of the call or of the arguments would crash for a document with no context; no add-only form can substitute a value for them or stop their evaluation, and a hook before the statement cannot skip it.

`dom/base/nsGlobalWindowOuter.h` is the tag's again: StealthContentOriginShift is a free inline function in StealthScreenCoords.h.
