/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTHDECLARATIONGATE_H
#define GFX_STEALTHDECLARATIONGATE_H

#include "Units.h"
#include "mozilla/Atomics.h"
#include "mozilla/Maybe.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "mozilla/gfx/StealthCanvasProjection.h"
#include "nsPoint.h"
#include "nsStringFwd.h"
#include "nsXULAppAPI.h"

namespace mozilla {
namespace gfx {

/**
 * Is the stealth engine on?
 *
 * THIS EXISTS BECAUSE THE ANSWER WAS BEING RE-DERIVED IN NINE PLACES, IN FOUR
 * DIFFERENT SPELLINGS. Counted 2026-08-23: `hw_seed() > 0`, `hw_seed() <= 0`,
 * `hw_seed() > 0 &&`, and a bare assignment - spread across Element.cpp,
 * Navigator.cpp, CanvasRenderingContext2D.cpp, gfxDWriteFonts.cpp,
 * gfxFT2FontBase.cpp, nsMediaFeatures.cpp, and this file twice.
 *
 * That is engine rule 16 in its purest shape - the same FACT computed in more
 * than one place - and the failure mode is silent. The day "on" becomes two
 * conditions instead of one, whoever adds the second has to find nine sites,
 * and the tenth they miss raises no error: it keeps behaving like stock Firefox
 * on one surface while every other surface is spoofed, which is exactly the
 * kind of internal disagreement a detector looks for.
 *
 * The home is this header rather than a new one because the predicate is this
 * gate's own precondition: the comment on StealthAssertDeclarationsComplete
 * already says "only checked when the stealth engine is actually on", and two
 * of the nine sites were in this very file.
 *
 * A bare binary launched with no seed is stock Firefox and must behave like
 * stock Firefox. That is not an incomplete declaration, it is the absence of
 * one.
 *
 * It is also where the parent process registers the observer of Juggler's
 * viewport resizes (StealthRegisterViewportResizeObserver), the first time it
 * answers true. No other point is certain to run in the parent before Juggler's
 * first Page.setViewportSize: the parent asks this during gfx and branding
 * startup, before any page exists. A content process pays nothing for it (one
 * process-type comparison, only when the engine is on), the parent one relaxed
 * atomic load once registered.
 */
void StealthRegisterViewportResizeObserver();

// Set, on the main thread of the parent, when the observer is registered.
inline Atomic<bool, Relaxed> gStealthViewportObserverRegistered(false);

inline bool StealthEngineActive() {
  const bool active = StaticPrefs::zoom_stealth_fpp_hw_seed() > 0;
  if (active && XRE_IsParentProcess() &&
      !gStealthViewportObserverRegistered) {
    StealthRegisterViewportResizeObserver();
  }
  return active;
}

/**
 * The canvas noise as the core declared it: the seed, or 0 when the
 * canvas is to be left exactly as drawn (the engine is off, or the canvas noise
 * is declared off, zoom.stealth.canvas.substitute_pixels), and the tolerance
 * that tells a blend of two colours from a neighbourhood with a third
 * (zoom.stealth.canvas.edge_tolerance, 0-255, refused at launch when missing). Every place that applies gfx::StealthProjectPixels
 * asks here, so the rule is written once.
 */
inline gfx::StealthCanvasNoise StealthCanvasNoiseDeclared() {
  if (!StealthEngineActive() ||
      !StaticPrefs::zoom_stealth_canvas_substitute_pixels()) {
    return gfx::StealthCanvasNoise::Off();
  }
  return {StaticPrefs::zoom_stealth_fpp_hw_seed(),
          StaticPrefs::zoom_stealth_canvas_edge_tolerance()};
}

/**
 * Refuse to run with an incomplete declaration.
 *
 * Engine rule 7, in the form the owner dictated on 2026-08-09: a value whose
 * domain is finite - or infinite but with the set of values the whole web
 * actually uses finite - lives ONLY in the core. One source. No compiled
 * copy in the engine, not even as a floor. And if the declaration is missing,
 * the engine REFUSES: it does not invent a default and it does not ask the
 * machine.
 *
 * That last sentence is what this exists to enforce, because the two obvious
 * alternatives are both worse and both have already happened here. Falling back
 * to the host is a measurable leak: a CFF webfont diverged on 108 of 150
 * measureText fields between Windows and Linux because one path dropped through
 * to FreeType. Falling back to a compiled constant is not a leak but it is two
 * numbers for one fact, which is how the taskbar height ended up written in
 * four places in two languages, three of which were 48 and one of which was 40.
 *
 * Refusing is loud, immediate, and impossible to mistake for working. The
 * failure it replaces was silent by construction: a page served with a value
 * from the machine looks exactly like a page served correctly.
 *
 * Only checked when the stealth engine is actually on. A bare binary launched
 * with no seed is stock Firefox and must behave like stock Firefox - that is
 * not an incomplete declaration, it is the absence of one.
 */
void StealthAssertDeclarationsComplete();

/**
 * Whether the CSS scale the page reads through (layout.css.devPixelsPerPx) is
 * the scale the window geometry was declared at: the declared CSS screen width
 * times the scale is the declared device work-area width, within one device
 * pixel. False for a non-positive scale (the host's own, -1) or width.
 * StealthAssertDeclarationsComplete refuses when this is false.
 */
bool StealthScaleMatchesDeclaration(float aDevPixelsPerPx,
                                    int32_t aScreenWidth,
                                    int32_t aAvailDeviceWidth);

/**
 * The window frame and the maximized window, in DEVICE pixels.
 *
 * One function per fact, read by everyone who can be asked it, instead of each
 * caller reading the prefs for itself. That is not tidiness. On 2026-08-09 three
 * DOM getters were moved onto the declaration - screenX/screenY,
 * mozInnerScreenX and mozInnerScreenY - and the event path was not, because
 * nothing connected the two in the source. The result was a contradiction a
 * page reads with one subtraction:
 *
 *     event.screenX - event.clientX === window.mozInnerScreenX
 *
 * holds on every real Firefox, because both sides come from the same widget.
 * With the geometry declared in one place and the events still asking the
 * widget, it held on NONE of 45 events on Windows and none of 20 on Linux,
 * against 0 failures out of 6 on stock.
 *
 * DEVICE pixels since firefox-38 (known bugs B258, B261). The previous
 * declaration was four CSS integers - a window at (0, 0), no side border, the
 * content 85 below - read the same for every window. Retail Firefox 151 on
 * Windows 11, measured at the four persona scales, says otherwise: a maximized
 * window sits a resize border OFF the screen on three sides (-8 at 100%) and is
 * two borders wider than the work area; its content starts 85 device pixels
 * below the screen top at 100% and 107 at 125%, i.e. 85.6 CSS, a value no CSS
 * integer can carry; and a popup has its own frame and its own position. In
 * device pixels that is one rule, and each reader converts with its window's
 * own scale and Gecko's rounding, as it does for the real values.
 *
 * Nothing() when the engine is off, which is stock Firefox and not an
 * incomplete declaration. When the engine is on they never fall back: a missing
 * declaration goes to StealthAssertDeclarationsComplete(), and the gate has
 * already refused at launch in the parent.
 */
struct StealthWindowFrame {
  // Invisible resize border, on the left, right and bottom of every window and
  // on the top of a popup.
  int32_t mBorder;
  // A maximized window: from the screen top to the content top.
  int32_t mMaximizedUi;
  // A popup: from the window top (border included) to the content top.
  int32_t mPopupUi;
  // A popup opened without left/top: where it is put, on both axes.
  int32_t mPopupPosition;
  // The browser UI height (window client top to content top) of a RESTORED
  // main window: it depends on the UI density only, normal, or compact when the
  // window's chrome height is under mCompactBelowCss CSS pixels. The maximized
  // window's own bar is mMaximizedUi, declared with the same rule.
  int32_t mUiNormal;
  int32_t mUiCompact;
  int32_t mCompactBelowCss;
  // A restored main window sits at (mRestoredPosition, mRestoredPosition) on
  // the screen, device pixels.
  int32_t mRestoredPosition;
  // The smallest chrome (client area) a window can have, in CSS pixels.
  int32_t mMinInnerWidthCss;
  int32_t mMinInnerHeightCss;
};
Maybe<StealthWindowFrame> StealthDeclaredWindowFrame();

/**
 * The maximized main window: (-border, -border), the work area plus a border on
 * each side. Device pixels; the caller divides by its window's scale.
 */
Maybe<LayoutDeviceIntRect> StealthDeclaredMaximizedWindow();

/**
 * What the main window is, as ONE value kept on the top BrowsingContext
 * (StealthWindowState, synced to every process) and updated in one place, when
 * Juggler resizes the window: the "stealth-viewport-resize" observer
 * (StealthRegisterViewportResizeObserver), which runs StealthNextWindowState.
 * A change of the inner size does not move it: on retail only Juggler's
 * resizeBy restores the window, and the inner size also changes with the first
 * layout (the host's real size) and with fullscreen.
 *
 * Maximized (mRestored false, mOuter and mCompact unused) is the declared
 * maximized window. Restored is what the main window becomes when
 * Page.setViewportSize resizes it (retail leaves the maximized size mode on
 * that resize): its outer size in device pixels, and the UI density it has, so
 * the content origin does not depend on anything but this value. Every reader
 * (outerWidth/outerHeight, screenX/screenY, mozInnerScreenX/Y, event screenX -
 * clientX) derives from it through StealthRestoredWindowRect and
 * StealthRestoredContentOrigin.
 */
struct StealthWindowState {
  bool mRestored = false;
  bool mCompact = false;
  LayoutDeviceIntSize mOuter;

  bool operator==(const StealthWindowState& aOther) const {
    return mRestored == aOther.mRestored && mCompact == aOther.mCompact &&
           mOuter == aOther.mOuter;
  }
};

/**
 * The largest size, in CSS pixels, the observer accepts from a
 * Page.setViewportSize: a window no host has is ignored, not clamped.
 */
constexpr int32_t kStealthMaxRequestedCss = (1 << 14) - 1;

/**
 * The state as the 64-bit value the BrowsingContext field carries: bit 0
 * restored, bit 1 compact, bits 2-25 the outer width, bits 26-49 the outer
 * height. The maximized state is 0, the field's default.
 */
uint64_t StealthPackWindowState(const StealthWindowState& aState);
StealthWindowState StealthUnpackWindowState(uint64_t aPacked);

/**
 * The scale the persona declared: device pixels per CSS pixel, the value of
 * layout.css.devPixelsPerPx the gate validated against the declared screen
 * (StealthScaleMatchesDeclaration). Never the widget's own scale: that is the
 * host's. Nothing() when the engine is off, and when the declaration is
 * missing or inconsistent (the gate refuses at launch in the parent, so a
 * process serving pages has it).
 */
Maybe<float> StealthDeclaredScale();

/**
 * The content of the maximized window in CSS pixels, rounded as Gecko rounds:
 * the size a page reads unresized. aMaximized is
 * StealthDeclaredMaximizedWindow(), aScale the declared scale.
 */
CSSIntSize StealthMaximizedContent(const LayoutDeviceIntRect& aMaximized,
                                   const StealthWindowFrame& aFrame,
                                   float aScale);

/**
 * The state after ONE Juggler resize (Page.setViewportSize: resizeBy on the
 * window) to aNewInner (CSS pixels). aMaximized is
 * StealthDeclaredMaximizedWindow(), aFrame StealthDeclaredWindowFrame(), aScale
 * the declared scale (StealthDeclaredScale).
 *
 * Only Juggler's calls reach this: every call is a resize from the window the
 * state describes, a repeat of the last size included (retail runs resizeBy
 * again, from the window it has). aOld is unchanged for a size with a
 * non-positive side, and for a window that was never restored and is asked for
 * the maximized content size (resizeBy with a zero delta does nothing). Any
 * other size is a resize, which Juggler makes with resizeBy on the window's
 * outer size in CSS pixels: the deltas are the new inner size minus the
 * chrome's inner size (width) and plus the bar over it (height), both
 * fractional CSS pixels, truncated toward zero; the outer size is rounded to
 * CSS pixels, moved by them, converted back to device pixels and not under the
 * minimum chrome. A restored window is never maximized again, whatever size it
 * is resized to, the maximized content size included: it goes through the same
 * resize. The UI density is decided again from the new chrome height. The
 * chrome of a maximized window is the work area; of a restored one the outer
 * size less a border on each side and the bottom.
 */
StealthWindowState StealthNextWindowState(const StealthWindowState& aOld,
                                          const CSSIntSize& aNewInner,
                                          const LayoutDeviceIntRect& aMaximized,
                                          const StealthWindowFrame& aFrame,
                                          float aScale);

/**
 * The pure core of the "stealth-viewport-resize" notification: the state after
 * Juggler asked the window for aRequested (CSS pixels), with the declared
 * scale.
 */
StealthWindowState StealthWindowStateAfterViewportResize(
    const StealthWindowState& aOld, const CSSIntSize& aRequested,
    const LayoutDeviceIntRect& aMaximized, const StealthWindowFrame& aFrame,
    float aDeclaredScale);

/**
 * The data of the "stealth-viewport-resize" notification, "<width>,<height>"
 * in CSS pixels, as two decimal integers from 1 to kStealthMaxRequestedCss.
 * False, aOut untouched, for anything else.
 */
bool StealthParseViewportResize(const nsAString& aData, CSSIntSize& aOut);

/**
 * Observes "stealth-viewport-resize", which Juggler sends right before the
 * resizeBy of Page.setViewportSize with the page's BrowsingContext as subject
 * and the requested CSS size as data, and moves the main window's state
 * (StealthWindowState on the top BrowsingContext) with it. Registered once, in
 * the parent process, from StealthEngineActive (the first time it answers
 * true, which the parent asks during gfx and branding startup) and again from
 * StealthAssertDeclarationsComplete, harmlessly. Idempotent, a no-op outside
 * the parent and on a thread that is not the main one (the next call from the
 * main thread registers).
 */
void StealthRegisterViewportResizeObserver();

/**
 * The restored main window in device pixels: at the restored position, the
 * state's outer size. Nothing() for the maximized state.
 */
Maybe<LayoutDeviceIntRect> StealthRestoredWindowRect(
    const StealthWindowState& aState, const StealthWindowFrame& aFrame);

/**
 * Where the content of the restored main window starts on the screen, in device
 * pixels: the restored position plus the border, and plus the bar of the
 * state's density. The one formula for it. Nothing() for the maximized state.
 */
Maybe<LayoutDeviceIntPoint> StealthRestoredContentOrigin(
    const StealthWindowState& aState, const StealthWindowFrame& aFrame);

/**
 * Does a window answer the DECLARED outer size, or its own real one?
 *
 * The declaration stands in for a real window that exists. In a content
 * process the outer size of an out-of-process iframe is whatever the parent
 * last sent (BrowserChild::RecvUpdateDimensions); until the first message the
 * rect is empty, and retail answers outerWidth/outerHeight 0x0 together with
 * innerWidth/innerHeight 0x0. aRealOuter is that real size (the tree owner's
 * GetSize(), device pixels). 0x0 is "the window has no size yet": a real 0
 * stays 0, as on retail, and the declared window is not put over it - a page
 * would read an outer window of 1936x1048 around an inner one of 0x0, which
 * no retail window is. Any other real size is replaced by the declaration,
 * unchanged.
 */
bool StealthOuterSizeIsDeclared(const LayoutDeviceIntSize& aRealOuter);

/**
 * The SHIFT between the real content origin and the declared one, in app
 * units. Nothing() when the engine is off.
 *
 * It exists because a plain substitution is not enough, and the first version
 * of this patch proved it in the field. `mozInnerScreenX` returned the declared
 * origin to EVERY window, iframes included: measured on 2026-08-10, an iframe
 * placed at (220, 150) in the page answered (0, 85) exactly like the top-level
 * document, and inside that iframe the invariant above gave 220 against 0. The
 * value is not SUBSTITUTED, the ANCHOR is moved: the caller passes its own real
 * origin and adds the shift, so the offset between frames stays the true one at
 * any depth.
 *
 * `aPopupWindowOrigin` decides WHICH window is declared. Nothing() is the
 * maximized main window, whose content starts at (0, UI) on the declared
 * screen. Some(p) is a popup, whose position is the REAL one (chosen by the
 * page, or by nsWindowWatcher from the declaration when the page does not ask
 * for one) and whose content starts at p + (border, popup UI). In device
 * pixels; `aAppUnitsPerDevPixel` is the one of the caller's pres context.
 *
 * `aRestoredContentOrigin` is StealthRestoredContentOrigin() for the
 * maximized-window case: when it is Some, the main window is restored and its
 * content starts there instead of at (0, UI). Ignored for a popup and in
 * fullscreen.
 *
 * One function only, because the shift is a fact and facts live in one place:
 * when it was computed in three places, the fourth consumer was forgotten.
 */
//
// `aFullscreen` comes first: a window in fullscreen, main or popup, is the
// whole declared screen, its content at (0, 0) like retail's (no UI, no
// border). Until 2026-11-01 the main window kept declaring the maximized one
// in fullscreen, content 85 below the top while the page filled the screen.
Maybe<nsPoint> StealthDeclaredOriginShift(
    const nsPoint& aRealContentOrigin,
    const Maybe<LayoutDeviceIntPoint>& aPopupWindowOrigin,
    const Maybe<LayoutDeviceIntPoint>& aRestoredContentOrigin, bool aFullscreen,
    int32_t aAppUnitsPerDevPixel);

/**
 * The colour depth the persona declares (zoom.stealth.screen.color_depth), or 0
 * when none is declared, in which case the caller carries on as stock Firefox.
 *
 * Read before anything asks the real panel. It used to fall through to
 * nsDeviceContext::GetDepth() and report whatever display the user actually
 * has, which is a host value inside a persona that claims to be a particular
 * Windows machine.
 *
 * It survived every cross-OS comparison we ran, and the reason is worth
 * keeping: both development machines are 24-bit, so the field AGREED across
 * platforms and looked declared. Agreement is not declaration - an absence of
 * difference is not evidence of a shared source, and this is the field that
 * proved it. Found by the field-by-field declaration audit,
 * which asks for the source in the code rather than for equality in the
 * measurement.
 */
int32_t StealthDeclaredPixelDepth();

/**
 * The screen the persona declares, in CSS pixels: {0, 0, width, height} from
 * zoom.stealth.screen.width/height (set by the core at launch), or
 * Nothing() when either is not above zero and the caller carries on as stock
 * Firefox.
 *
 * Deliberately NOT gated through StealthAssertDeclarationsComplete: that is what
 * StealthDeclaredAvailRect does on the first use of a declared value, and the
 * old inline code in GetRect never did. Keeping it that way keeps the output of
 * the engine byte for byte what it was.
 */
Maybe<CSSIntRect> StealthDeclaredScreenRect();

/**
 * The available part of the declared screen, in CSS pixels: {0, 0, width,
 * height - taskbar} from zoom.stealth.screen.width/height/taskbar_px, or
 * Nothing() when width or height is not above zero and the caller carries on
 * as stock Firefox.
 *
 * The strip by which availHeight is short of height is the Windows taskbar, and
 * its height is DECLARED - by the core, once, and by nothing else. It used
 * to be the literal 48 in the engine and a second literal 48 in the generator's
 * Python, in two languages with nothing tying them together: a persona needing
 * a different one (auto-hide, a second monitor, a scaled display) had to be
 * changed in both, and nothing would have said so if only one moved.
 *
 * There is NO compiled floor under it any more (engine rule 7, 2026-08-09). The
 * "-1 keeps the 48 that was compiled in" that used to sit here was the second
 * source of truth the rule forbids: it made a browser launched with a
 * half-written profile look like it was working. A missing declaration now
 * refuses, in StealthAssertDeclarationsComplete, on the FIRST USE of a declared
 * value - not at startup, where the first attempt put it and where it hung
 * every legitimate launch, because on the production path the prefs arrive over
 * the connection after the process is already up.
 */
Maybe<CSSIntRect> StealthDeclaredAvailRect();

}  // namespace gfx
}  // namespace mozilla

#endif  // GFX_STEALTHDECLARATIONGATE_H
