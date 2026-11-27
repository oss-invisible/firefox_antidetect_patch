/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthWindowGeometry_h
#define mozilla_dom_StealthWindowGeometry_h

// The window geometry a page sees when the stealth engine is on, for the outer
// window it asks. Each Stealth* function below answers false (or Nothing) when
// the engine is off: the caller then keeps Firefox's own path. Otherwise it
// fills its out parameter and answers true. Main thread only.
//
// This file holds the definitions too, and is included by
// nsGlobalWindowOuter.cpp ONLY: dom/base/moz.build registers no source file
// for it, so the hooks in nsGlobalWindowOuter.cpp add no line to a shared
// build file. Do not include it from another translation unit. The content
// origin shift both mozInnerScreenX/Y and the mouse events use is in
// dom/events/StealthScreenCoords.h (StealthContentOriginShift).
//
// No compiled value anywhere: a missing declaration refuses in
// StealthDeclarationGate instead of being papered over here.

#include "StealthDeclarationGate.h"
#include "StealthScreenCoords.h"
#include "Units.h"
#include "mozilla/DimensionRequest.h"
#include "mozilla/ErrorResult.h"
#include "mozilla/Maybe.h"
#include "mozilla/PresShell.h"
#include "mozilla/RefPtr.h"
#include "mozilla/dom/BrowserChild.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/Document.h"
#include "nsCOMPtr.h"
#include "nsGlobalWindowOuter.h"
#include "nsIBaseWindow.h"
#include "nsIDocShell.h"
#include "nsIWidget.h"
#include "nsPIDOMWindowInlines.h"
#include "nsPresContext.h"
#include "nsRect.h"

namespace mozilla::dom {

namespace {

// Is the top-level window of this document a popup (opened with features)?
// The declaration of the window depends on it.
inline bool StealthIsInPopup(const nsGlobalWindowOuter& aWindow) {
  BrowsingContext* bc = aWindow.GetBrowsingContext();
  return bc && bc->Top()->GetIsPopupRequested();
}

// Is the top-level window in fullscreen (requestFullscreen or F11)? The same
// source as window.fullScreen and the display-mode media query: in a content
// process, the size mode the parent gave the puppet widget.
inline bool StealthIsFullscreen(const nsGlobalWindowOuter& aWindow) {
  return aWindow.Fullscreen();
}

// The content origin shift for the window's document, or Nothing().
inline Maybe<nsPoint> StealthShiftOf(nsGlobalWindowOuter& aWindow) {
  nsIDocShell* docShell = aWindow.GetDocShell();
  RefPtr<nsPresContext> pc = docShell ? docShell->GetPresContext() : nullptr;
  return StealthContentOriginShift(pc);
}

// Has the window's document a root frame yet? Mozilla's GetInnerScreenRect
// answers an empty rect when its pres shell has none (nsGlobalWindowOuter.cpp,
// GetInnerScreenRect): before the first layout, as seen by an inline script at
// the top of <head>.
inline bool StealthHasRootFrame(nsGlobalWindowOuter& aWindow) {
  nsIDocShell* docShell = aWindow.GetDocShell();
  PresShell* presShell = docShell ? docShell->GetPresShell() : nullptr;
  return presShell && presShell->GetRootFrame();
}

}  // namespace

// window.outerWidth / outerHeight, in CSS pixels. Throws NS_ERROR_FAILURE
// through aError (and answers 0x0) when the window has no tree owner.
//
// Stealth: the outer size from the declared window, in device pixels,
// converted below with the window's own scale exactly like the real size.
//
// The MAIN window is maximized: the work area plus Windows' invisible resize
// border on each side (retail 151, 100%: outerWidth - availWidth = 16). Until
// firefox-38 this answered the work area itself, a window that does not
// exist maximized on Windows (B261). A POPUP is its real inner size plus its
// frame - a border on the left, right and bottom, the popup UI above - where
// it used to answer the maximized window's size, 1920x1032 for a
// width=500,height=400 popup (B258). The inner size is the top-level one,
// synced to every process in the BrowsingContext (see
// nsPresContext::UpdateInnerSizeSpoofedForRFP), so an out-of-process iframe
// in the popup answers the same.
//
// No compiled value anywhere: a missing declaration refuses in
// StealthDeclarationGate instead of being papered over here.
inline bool StealthOuterSize(nsGlobalWindowOuter& aWindow, CSSIntSize& aSize,
                             ErrorResult& aError) {
  if (!gfx::StealthEngineActive()) {
    return false;
  }
  gfx::StealthAssertDeclarationsComplete();
  nsCOMPtr<nsIBaseWindow> treeOwnerAsWin = aWindow.GetTreeOwnerWindow();
  if (!treeOwnerAsWin) {
    aError.Throw(NS_ERROR_FAILURE);
    aSize = CSSIntSize();
    return true;
  }
  // A window whose real outer size is still 0x0 (an out-of-process iframe
  // that started before the parent sent its dimensions) keeps it, like retail:
  // the declared window replaces a real window, not the absence of one, and
  // inner is 0x0 in the same state.
  if (!gfx::StealthOuterSizeIsDeclared(treeOwnerAsWin->GetSize())) {
    return false;
  }
  // In fullscreen the window is the declared screen, popups included: retail
  // answers outer == inner == screen. It used to answer the maximized window
  // (1936x1048 under a 1920x1080 inner), a window no screen holds.
  if (StealthIsFullscreen(aWindow)) {
    if (const auto screen = gfx::StealthDeclaredScreenRect()) {
      aSize = screen->Size();
      return true;
    }
  }
  const CSSToLayoutDeviceScale scale =
      aWindow.CSSToDevScaleForBaseWindow(treeOwnerAsWin);
  if (StealthIsInPopup(aWindow)) {
    const auto frame = gfx::StealthDeclaredWindowFrame();
    BrowsingContext* bc = aWindow.GetBrowsingContext();
    if (frame && bc) {
      const LayoutDeviceIntSize inner = gfx::RoundedToInt(
          CSSSize(bc->TopInnerSizeSpoofedForRFP().width,
                  bc->TopInnerSizeSpoofedForRFP().height) *
          scale);
      const LayoutDeviceIntSize outer =
          inner + LayoutDeviceIntSize(2 * frame->mBorder,
                                      frame->mPopupUi + frame->mBorder);
      aSize = gfx::RoundedToInt(outer / scale);
      return true;
    }
  } else if (const auto maximized = gfx::StealthDeclaredMaximizedWindow()) {
    aSize = gfx::RoundedToInt(maximized->Size() / scale);
    return true;
  }
  // Unreachable: the gate refuses at launch without the declaration.
  aSize = CSSIntSize();
  return true;
}

// window.screenX / screenY of the MAIN window, from the declared maximized
// window. False for a popup, which keeps its real position, and when the
// declaration has no maximized window.
//
// Stealth: the MAIN window's position is the declared maximized window's,
// a resize border off the screen (-8 at 100%, -7 at 125%, -6 at 200% on
// retail 151), which outerWidth above depends on: until 2026-08-09 the
// position stayed whatever the OS handed the headless widget, and screenX +
// outerWidth came to 1924 on a 1920 screen. A POPUP keeps its REAL
// position: the page chose it, or nsWindowWatcher put it at the declared
// default when the page did not, so it is the same on both builds.
inline bool StealthScreenXY(nsGlobalWindowOuter& aWindow,
                            nsIBaseWindow* aTreeOwner, CSSIntPoint& aPoint) {
  if (!gfx::StealthEngineActive()) {
    return false;
  }
  // In fullscreen, main or popup, the window is the screen: (0, 0).
  if (StealthIsFullscreen(aWindow)) {
    aPoint = CSSIntPoint(0, 0);
    return true;
  }
  if (StealthIsInPopup(aWindow)) {
    return false;
  }
  if (const auto maximized = gfx::StealthDeclaredMaximizedWindow()) {
    aPoint = gfx::RoundedToInt(
        maximized->TopLeft() / aWindow.CSSToDevScaleForBaseWindow(aTreeOwner));
    return true;
  }
  return false;
}

// mozInnerScreenX / mozInnerScreenY: aRect (the real inner screen rect of the
// window) moved by the content origin shift. Nothing when there is no shift.
//
// Stealth: the content origin, from the ONE function that answers it.
//
// This used to read the two prefs here and do the arithmetic inline, and so
// did mozInnerScreenY, and so did screenX with its own pair - three copies of
// the same idea, and the EVENT path never got its copy because nothing in the
// source connected them. A page found that with one subtraction: on every
// mouse event, screenX - clientX must equal this value, and it did not, on 45
// events out of 45. See StealthDeclarationGate.h for the measurement.
//
// GetInnerScreenRect keeps serving its other callers - popup placement,
// coordinate conversion - the real rect. Those are not content-visible.
// The SHIFT, not the substitution. Substituting answers the TOP-LEVEL origin
// to every window: measured on 2026-08-10, an iframe at (220, 150) in the
// page answered (0, 85) like the top, and inside that iframe
// screenX - clientX gave 220 against a mozInnerScreenX of 0 - the same
// contradiction this patch exists to remove, moved one level down. By adding
// the shift to the REAL rect of the window, the offset between frames stays
// true and the relation holds at any depth.
//
// Before the document has a root frame every frame reads 0, Mozilla's own
// answer (round 7 of the retail captures, WINDOW_GEOMETRY_FRAME_EARLY.csv: an
// inline script at the top of <head> reads mozInnerScreenX/Y = (0, 0) in the
// top document and in every frame). Adding the shift to that empty rect would
// answer the shift alone, a value derived from the host's real origin, so
// Nothing() is answered and Mozilla's 0 stands.
inline Maybe<float> StealthMozInnerScreenX(nsGlobalWindowOuter& aWindow,
                                           const nsRect& aRect) {
  if (!StealthHasRootFrame(aWindow)) {
    return Nothing();
  }
  if (const auto shift = StealthShiftOf(aWindow)) {
    return Some(nsPresContext::AppUnitsToFloatCSSPixels(aRect.x + shift->x));
  }
  return Nothing();
}

// Stealth: see StealthMozInnerScreenX. A maximized window's content starts
// the UI height below the screen top - 85 device pixels at 100%, 107 at 125%,
// which reads 85.6 like retail 151 - and a popup's the popup UI below its
// own top.
inline Maybe<float> StealthMozInnerScreenY(nsGlobalWindowOuter& aWindow,
                                           const nsRect& aRect) {
  if (!StealthHasRootFrame(aWindow)) {
    return Nothing();
  }
  if (const auto shift = StealthShiftOf(aWindow)) {
    return Some(nsPresContext::AppUnitsToFloatCSSPixels(aRect.y + shift->y));
  }
  return Nothing();
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthWindowGeometry_h
