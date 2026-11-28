/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTHDECLARATIONGATE_H
#define GFX_STEALTHDECLARATIONGATE_H

#include "Units.h"
#include "mozilla/Maybe.h"
#include "mozilla/Span.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "mozilla/gfx/StealthCanvasProjection.h"
#include "nsPoint.h"

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
 */
inline bool StealthEngineActive() {
  return StaticPrefs::zoom_stealth_fpp_hw_seed() > 0;
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
  // A popup: from the window top (border included) to the top of its client
  // area. An out-of-process frame that has not received its first matrix reads
  // the client origin: the popup's position plus (mBorder, mPopupClientTop).
  int32_t mPopupClientTop;
};
Maybe<StealthWindowFrame> StealthDeclaredWindowFrame();

/**
 * The maximized main window: (-border, -border), the work area plus a border on
 * each side. Device pixels; the caller divides by its window's scale.
 */
Maybe<LayoutDeviceIntRect> StealthDeclaredMaximizedWindow();

/**
 * The top-left of the maximized main window: (-border, -border). Pure: the one
 * place the maximized window's position is written, read by
 * StealthDeclaredMaximizedWindow and StealthDeclaredClientOrigin.
 */
LayoutDeviceIntPoint StealthMaximizedWindowTopLeft(
    const StealthWindowFrame& aFrame);

/**
 * The declared content origin D on screen, in device pixels: (0, 0) in
 * fullscreen; a popup's position plus (border, popup UI); the maximized
 * window's content (0, maximized UI) otherwise. Pure. The one place D is
 * written: the chrome offset of a declared window is D minus the client origin.
 */
LayoutDeviceIntPoint StealthDeclaredContentOrigin(
    const StealthWindowFrame& aFrame,
    const Maybe<LayoutDeviceIntPoint>& aPopupWindowOrigin, bool aFullscreen);

/**
 * The declared CLIENT origin on screen, in device pixels: the top-left of the
 * top-level window's client area, which is where an out-of-process iframe that
 * has laid out but has not received its first matrix reads mozInnerScreenX/Y
 * (round 7 of the retail captures, WINDOW_GEOMETRY_FRAME_EARLY.csv: Mozilla's
 * matrix is then Translation(0), so the frame reads the window's client
 * origin). Fullscreen: (0, 0), the content is the screen. A popup (its declared
 * position in aPopupWindowOrigin): that position plus (border, popup client
 * top). The maximized main window: the declared maximized window's top-left
 * plus (border, border), which is (0, 0). Pure.
 */
LayoutDeviceIntPoint StealthDeclaredClientOrigin(
    const StealthWindowFrame& aFrame,
    const Maybe<LayoutDeviceIntPoint>& aPopupWindowOrigin, bool aFullscreen);

/**
 * The declared work area in device pixels: {0, 0, avail_device_width,
 * avail_device_height}. The maximized window is this plus a border on each side
 * (StealthDeclaredMaximizedWindow). Nothing() when the engine is off.
 */
Maybe<LayoutDeviceIntRect> StealthDeclaredAvailDeviceRect();

/**
 * Where a popup is declared to sit at birth, in DEVICE pixels, computed from
 * declared inputs only (the work area, the frame, the scale, the positions the
 * other browser windows are declared at). Retail's rule, read in the 159
 * source and measured in round 5 (RetailCaptures popup-frame): the markup's
 * position, the stagger, the constrain; then SizeOpenedWindow's clamp. Every
 * constant below is Firefox's own, with its line; none is a pref.
 */

// browser.xhtml:17, screenX="4" screenY="4" on the root, applied by
// AppWindow::LoadPositionFromXUL (AppWindow.cpp:1126-1199) to a popup too.
constexpr int32_t kStealthPopupXulPosition = 4;
// AppWindow::StaggerPosition (AppWindow.cpp:1352-1353): the step and the slop,
// in CSS pixels, turned into device pixels with the screen's scale.
constexpr int32_t kStealthPopupStaggerOffsetCss = 22;
constexpr int32_t kStealthPopupStaggerSlopCss = 4;
// AppWindow::CreateNewContentWindow (AppWindow.cpp:2245): the window a popup
// is created with, 615 x 480, before its chrome has loaded.
constexpr int32_t kStealthPopupInitialWidth = 615;
constexpr int32_t kStealthPopupInitialHeight = 480;
// SizeOpenedWindow (nsWindowWatcher.cpp:2395, :2402): a size the page gave is
// at least 100 CSS pixels.
constexpr int32_t kStealthPopupMinContentCss = 100;

/**
 * The chrome around a popup's content in CSS pixels, as SizeOpenedWindow
 * computes it (nsWindowWatcher.cpp:2298-2316): the window's size rounded to
 * CSS pixels minus the content's, each rounded on its own. The window is the
 * initial one (aInitialDevice); the content is that minus the declared chrome
 * (aChromeDevice: the popup UI plus the border for the height, two borders
 * for the width). Rounding each term is why this is not chromeDevice / scale:
 * at 2x the 153 device pixels of height are 76 CSS pixels, not 76.5.
 */
int32_t StealthPopupChromeCssPixels(int32_t aInitialDevice,
                                    int32_t aChromeDevice, float aScale);

/**
 * SizeOpenedWindow's clamp of one axis (nsWindowWatcher.cpp:2434-2452): when
 * the window ends past aAvailEnd it is moved back so it ends there, then it
 * does not start before aAvailStart. Device pixels.
 */
int32_t StealthClampPopupAxis(int32_t aPosition, int32_t aWindowSize,
                              int32_t aAvailStart, int32_t aAvailEnd);

/**
 * AppWindow::StaggerPosition (AppWindow.cpp:1347-1470) on the declared
 * positions of the other browser windows (aOthers: the maximized main window
 * at (-border, -border), other popups at their declared position, never their
 * real one). The window is aWindowSize device pixels, the screen is aAvail.
 * Returns aStart when nothing collides.
 */
LayoutDeviceIntPoint StealthStaggerPopupPosition(
    const LayoutDeviceIntPoint& aStart, float aScale,
    Span<const LayoutDeviceIntPoint> aOthers,
    const LayoutDeviceIntSize& aWindowSize, const LayoutDeviceIntRect& aAvail);

/**
 * nsWindow::ConstrainPosition on Windows (nsWindow.cpp:2318-2381) with
 * nsIWidget::ConstrainPositionToBounds (nsIWidget.cpp:1724-1755): the work
 * area inflated by the resize border (aBorder: left, right and bottom), the
 * window kept inside it; a window at (0, 0) is left alone.
 */
LayoutDeviceIntPoint StealthConstrainPopupPosition(
    const LayoutDeviceIntPoint& aPoint, const LayoutDeviceIntSize& aWindowSize,
    const LayoutDeviceIntRect& aAvail, int32_t aBorder);

/**
 * What the page asked for in window.open's features, as SizeOpenedWindow sees
 * it. Left and top are device pixels (CalcSizeSpec's desktop pixels, which are
 * device pixels on Windows); width and height are CSS pixels.
 */
struct StealthPopupRequest {
  Maybe<int32_t> mLeft;
  Maybe<int32_t> mTop;
  // The width and height the page gave, outer or inner; Nothing() when it gave
  // none, and the popup is then the initial window.
  Maybe<int32_t> mWidth;
  Maybe<int32_t> mHeight;
  // True when the size is the content's (innerWidth / width), so the chrome is
  // added to it; false for an outer size.
  bool mWidthIsInner = false;
  bool mHeightIsInner = false;
};

/**
 * The declared device position of a popup at birth. aFrame is the declared
 * window frame (only the border and the popup UI are read), aAvail the
 * declared work area, aScale layout.css.devPixelsPerPx, aOthers the declared
 * positions of the other navigator:browser windows.
 *
 * The base is the markup's position, staggered and constrained; an axis the
 * page gave replaces it; then the clamp of SizeOpenedWindow keeps the window
 * inside the work area, on both axes, with the window's size as Firefox
 * computes it: round((max(100, height) + chrome) * scale), the 100 only when
 * the page gave a size.
 */
LayoutDeviceIntPoint StealthDeclaredPopupPosition(
    const StealthPopupRequest& aRequest, const StealthWindowFrame& aFrame,
    const LayoutDeviceIntRect& aAvail, float aScale,
    Span<const LayoutDeviceIntPoint> aOthers);

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
 * The state of the top-level window that the declared window is built from.
 * Everything in it is the top's DECLARED state, except the top's real inner
 * size, which only sizes a popup (layout depends on it, so it stays real) and
 * the real outer size, which only says whether a window has a size yet.
 */
struct StealthDeclaredWindowState {
  // Was the top-level window opened as a popup (window.open with features)?
  bool mPopup = false;
  // The popup's declared position, device px; Nothing() until it is declared,
  // when the declared default (StealthWindowFrame::mPopupPosition) stands in.
  Maybe<LayoutDeviceIntPoint> mPopupPosition;
  // Is the top-level window in fullscreen (the top-level widget's size mode)?
  bool mFullscreen = false;
  // The top's real inner size, device px. Read for a popup only.
  LayoutDeviceIntSize mTopInner;
  // The real outer size of the window being declared, device px. 0x0 is a
  // window that has not been sized yet (StealthOuterSizeIsDeclared).
  LayoutDeviceIntSize mRealOuter;
  // Is the window an out-of-process frame in the top-level one? Its chrome
  // offset is 0 (BrowserChild asserts it): the frame's place in the top
  // document is in the matrix it receives, and the top's chrome offset is
  // carried by the top tab alone.
  bool mBridged = false;
};

/**
 * What the parent sends a content process in a DimensionInfo about the window,
 * declared: the outer rect (position and size), the client offset (the window
 * origin W is rect.TopLeft() + clientOffset) and the chrome offset.
 */
struct StealthDeclaredDimensions {
  LayoutDeviceIntRect mRect;
  LayoutDeviceIntPoint mClientOffset;
  LayoutDeviceIntPoint mChromeOffset;
};

/**
 * The declared window of a top-level window, device pixels. Pure: the declared
 * frame, the declared maximized window and the declared screen are arguments.
 * It never reads the real position of anything, so it gives the same answer
 * whatever real rect it is asked about.
 *
 *   maximized: rect = aMaximized; client offset = client origin - rect origin
 *     = (border, border); chrome offset (0, maximized UI).
 *   popup: rect = (declared position, top inner + (2 border, popup UI +
 *     border)); client offset (border, client top); chrome offset
 *     (0, popup UI - client top).
 *   fullscreen: rect = (0, 0, aScreen); both offsets 0.
 *
 * A window with no real size yet (mRealOuter 0x0) stays empty: f(0x0) = 0x0,
 * and its offsets are 0, as on retail before the first layout.
 */
StealthDeclaredDimensions StealthDeclaredWindowDimensions(
    const StealthWindowFrame& aFrame, const LayoutDeviceIntRect& aMaximized,
    const LayoutDeviceIntSize& aScreen, const StealthDeclaredWindowState& aState);

/**
 * StealthDeclaredWindowDimensions with the declared frame, maximized window
 * and screen of the prefs, for a window of scale aScale. Nothing() when the
 * engine is off.
 */
Maybe<StealthDeclaredDimensions> StealthDeclaredWindowDimensionsNow(
    const CSSToLayoutDeviceScale& aScale, const StealthDeclaredWindowState& aState);

/**
 * A window.moveTo/moveBy/resizeTo/resizeBy request, in declared space, as the
 * content process sends it: each coordinate is absolute, device px, and only
 * the ones the page changed are present.
 */
struct StealthOuterRequest {
  Maybe<int32_t> mX;
  Maybe<int32_t> mY;
  Maybe<int32_t> mWidth;
  Maybe<int32_t> mHeight;
};

/**
 * The same request for the real window. The page sees the declared outer rect
 * aDeclared and the window really has aReal, so a coordinate the page moves by
 * d moves the real window by d: real = aReal + (request - aDeclared), on each
 * axis. For the size that is the request, minus the declared frame, plus the
 * real frame, when the inner size is the same on both sides. Pure.
 */
StealthOuterRequest StealthRealOuterRequest(
    const StealthOuterRequest& aRequest, const LayoutDeviceIntRect& aDeclared,
    const LayoutDeviceIntRect& aReal);

/**
 * The popup's new declared position after a request: the requested
 * coordinates over the current declared position. Nothing() when the request
 * moves nothing.
 */
Maybe<LayoutDeviceIntPoint> StealthRequestedPosition(
    const StealthOuterRequest& aRequest,
    const LayoutDeviceIntPoint& aDeclaredPosition);

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
