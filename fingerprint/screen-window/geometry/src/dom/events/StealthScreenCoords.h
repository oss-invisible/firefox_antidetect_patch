/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthScreenCoords_h
#define mozilla_dom_StealthScreenCoords_h

// Defined here, not in a source file of its own: dom/events/moz.build
// registers none for it, so the hook in Event.cpp adds no line to a shared
// build file. Included by Event.cpp and, through StealthWindowGeometry.h, by
// nsGlobalWindowOuter.cpp: everything below is inline, so each translation
// unit sees one definition.

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "mozilla/DimensionRequest.h"
#include "mozilla/Maybe.h"
#include "mozilla/RefPtr.h"
#include "mozilla/dom/BrowserChild.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/Document.h"
#include "nsCOMPtr.h"
#include "nsIWidget.h"
#include "nsPoint.h"
#include "nsPresContext.h"

namespace mozilla::dom {

// The place of an out-of-process iframe inside the top document's content,
// as the matrix the parent process computed for the frame's own
// BrowsingContext (StealthNoteChildToParentMatrix in dom/ipc/
// StealthFrameOrigin.h): the frame's child-to-top-level-widget matrix less the
// tab's translation, so nothing of the host's chrome is in it. Nothing() with
// the engine off, for a root that is not an out-of-process frame (the top
// document and its in-process frames), before the frame's first matrix, and
// when the tab's matrix is not a translation. Read the frame's OWN
// BrowsingContext, never Top().
inline Maybe<LayoutDeviceToLayoutDeviceMatrix4x4> StealthFrameToTopContentOf(
    nsPresContext* aPresContext) {
  if (!aPresContext || !gfx::StealthEngineActive()) {
    return Nothing();
  }
  nsIWidget* rootWidget = aPresContext->GetRootWidget();
  if (!rootWidget) {
    return Nothing();
  }
  BrowserChild* rootChild = rootWidget->GetOwningBrowserChild();
  if (!rootChild || rootChild->IsTopLevel()) {
    return Nothing();
  }
  // The BrowsingContext of the frame's root, not of the document asking: a
  // same-process subframe inside the frame shares the frame's widget and so
  // its place.
  BrowsingContext* bc = rootChild->GetBrowsingContext();
  if (!bc) {
    return Nothing();
  }
  return bc->GetStealthFrameToTopContent();
}

// The matrix Event::GetScreenCoords applies to a widget point: Mozilla's
// (aMozilla, WidgetToTopLevelWidgetTransform()) for every document but an
// out-of-process iframe with a place in the top; for that frame the place
// without the host's chrome offset, keeping the frame's own transform and
// Firefox's integer offset (gfx::StealthFrameEventTransform). The page then
// reads the declared top origin plus the frame's own place, whatever the real
// chrome offset is, fractional or not.
inline LayoutDeviceToLayoutDeviceMatrix4x4 StealthTopLevelTransform(
    nsPresContext* aPresContext,
    const LayoutDeviceToLayoutDeviceMatrix4x4& aMozilla) {
  const Maybe<LayoutDeviceToLayoutDeviceMatrix4x4> rel =
      StealthFrameToTopContentOf(aPresContext);
  if (!rel) {
    return aMozilla;
  }
  return gfx::StealthFrameEventTransform(*rel, aMozilla);
}

// The shift between the real top-level content origin (the on-screen offset
// of the root widget, less the frame's own place in the top for an
// out-of-process iframe; what mozInnerScreenX reported before it became a
// declaration) and the declared one, in app units; Nothing() with the engine
// off. ONE function for mozInnerScreenX/Y and for the events (Event.cpp): this
// is how screenX - clientX == mozInnerScreenX stays true in popups and iframes
// too. A subframe adds the shift to its OWN rect, it does not replace it.
//
// Main thread only. Every call it makes is on a public API: nsPresContext,
// nsIWidget, BrowsingContext, BrowserChild::GetDimensions.
inline Maybe<nsPoint> StealthContentOriginShift(nsPresContext* aPresContext) {
  if (!aPresContext || !gfx::StealthEngineActive()) {
    return Nothing();
  }
  // The real origin is the on-screen offset of the root widget: in the content
  // process it is the PuppetWidget, whose offset is the origin of the
  // top-level content area - for the top document it coincides with
  // GetInnerScreenRect(), for a subframe it does not, and that very
  // difference is what must be preserved. Widget calls only, no layout:
  // Event.cpp calls this function for every mouse event.
  nsCOMPtr<nsIWidget> rootWidget = aPresContext->GetRootWidget();
  if (!rootWidget) {
    return Nothing();
  }
  const int32_t auPerDevPx = aPresContext->AppUnitsPerDevPixel();
  // A popup is declared from its REAL position: the outer rect of the
  // top-level window, which BrowserChild receives from the parent - also in an
  // out-of-process iframe, where it arrives from the embedder. It is the same
  // source as GetScreenXY (nsIBaseWindow::GetPosition of the tree owner).
  Maybe<LayoutDeviceIntPoint> popupOrigin;
  Document* doc = aPresContext->Document();
  BrowsingContext* bc = doc ? doc->GetBrowsingContext() : nullptr;
  if (bc && bc->Top()->GetIsPopupRequested()) {
    BrowserChild* child = rootWidget->GetOwningBrowserChild();
    if (!child) {
      // The parent process serves no pages: nothing to declare.
      return Nothing();
    }
    LayoutDeviceIntPoint outer;
    if (NS_FAILED(child->GetDimensions(DimensionKind::Outer, &outer.x.value,
                                       &outer.y.value, nullptr, nullptr))) {
      return Nothing();
    }
    popupOrigin = Some(outer);
  }
  // In fullscreen the content is the screen. Same source as Fullscreen() in a
  // content process: the puppet widget's size mode.
  const bool fullscreen = rootWidget->SizeMode() == nsSizeMode_Fullscreen;
  // The anchor is the root widget's screen offset less the frame's own place
  // in the top, so the page reads the declared top origin plus that place
  // (Firefox's rounded device offset of the frame, host chrome cancelled).
  // The place is the parent's matrix for an out-of-process iframe. The host's
  // real chrome offset is never used: it would leak it.
  const Maybe<LayoutDeviceToLayoutDeviceMatrix4x4> rel =
      StealthFrameToTopContentOf(aPresContext);
  LayoutDeviceIntPoint offsetInTop;
  if (rel) {
    offsetInTop = gfx::StealthFrameOffsetInTop(*rel);
  } else {
    BrowserChild* rootChild = rootWidget->GetOwningBrowserChild();
    if (rootChild && !rootChild->IsTopLevel()) {
      // An out-of-process iframe with no matrix: it has laid out but has not
      // received its first one (or the tab's matrix is not a translation).
      // Retail reads the CLIENT origin of its top-level window there: Mozilla's
      // matrix is Translation(0), so the frame's reading is the window's
      // client origin (round 7 of the retail captures,
      // WINDOW_GEOMETRY_FRAME_EARLY.csv: (0, 0) for the maximized window at
      // the 4 scales, the popup's position plus (border, client top) for a
      // popup, its client top measured in round 5,
      // WINDOW_GEOMETRY_POPUP_FRAME.csv; (0, 0) in fullscreen). The page reads D + offsetInTop, so the
      // place to take out of the anchor is the declared client origin less D:
      // the reading is then the declared client origin, whatever Mozilla's
      // matrix and the host's chrome are, and nothing of the host reaches it.
      const Maybe<gfx::StealthWindowFrame> frame =
          gfx::StealthDeclaredWindowFrame();
      if (!frame) {
        return Nothing();
      }
      offsetInTop =
          gfx::StealthDeclaredClientOrigin(*frame, popupOrigin, fullscreen) -
          gfx::StealthDeclaredContentOrigin(*frame, popupOrigin, fullscreen);
    }
  }
  const nsPoint real = LayoutDevicePixel::ToAppUnits(
      rootWidget->WidgetToScreenOffset() - offsetInTop, auPerDevPx);
  return gfx::StealthDeclaredOriginShift(real, popupOrigin, fullscreen,
                                         auPerDevPx);
}

// aScreenPoint (the last term of the sum Event::GetScreenCoords forms: the
// widget's offset on the screen, in app units) plus the declared content origin shift, so that
//
//     event.screenX - event.clientX === window.mozInnerScreenX
//
// stays true. aScreenPoint itself when the engine is off, or when there is
// nothing to declare: the value is then exactly stock Firefox's.
//
// It asks StealthContentOriginShift, the one function mozInnerScreenX and
// mozInnerScreenY ask too. Main thread only, like its caller. Arithmetic and
// widget queries only, no layout: this runs for every trusted mouse and wheel
// event.
//
// The text below was written in Event::GetScreenCoords, where this sum is
// formed: "this function", "here" and "up here" mean that function, which
// calls this one around the last term of that sum.
//
// Stealth: the origin comes from the SAME function mozInnerScreenX answers
// with, and that is the whole point of it being a function.
//
// This is the funnel: MouseEvent, UIEvent, Touch and EventStateManager all
// reach screen coordinates through here, so it is the one place where the
// relation a page checks is either true or false.
//
//     event.screenX - event.clientX === window.mozInnerScreenX
//
// It holds on every real Firefox because both sides come from this widget.
// When the window geometry became a declaration on 2026-08-09 the three DOM
// getters were moved and this line was not, so the two sides came from
// different places and the relation failed on 45 mouse events out of 45 on
// Windows and 20 of 20 on Linux, against 0 of 6 on stock. Humanised movement
// made it louder rather than quieter: dozens of events per action, each one a
// fresh sample of the same contradiction.
//
// Adding the declared origin HERE rather than teaching the widget to lie is
// deliberate. The widget works in device pixels and cannot see the CSS scale
// - layout.css.devPixelsPerPx is applied above it, in the device context - so
// a declaration down there would need a conversion factor the widget does not
// have. Up here the units are known and the arithmetic is the same one the
// getter does.
// Written as the relation itself - screen = client + content origin - and not
// as "the widget-relative point plus something", because the widget-relative
// point sits inside the REAL window and carries the real chrome height with
// it. That was the first attempt and it moved the declared amount while
// leaving the same gap: with chrome_h at 85 the offset was 800, and with
// chrome_h at 300 it was still 800, because both sides had moved together.
// The client point is the one the page already receives, so adding the origin
// to it makes the relation true by construction rather than by arithmetic
// that happens to line up.
//
// Arithmetic only, and that is not an optimisation, it is a correctness
// requirement. THIS FUNCTION IS THE HOT PATH: EventStateManager::PreHandleEvent
// calls it for every trusted real mouse event and every wheel event, to store
// sLastScreenPoint, and then calls GetClientCoords right after. A first
// version of this branch derived the client point here with
// nsLayoutUtils::GetEventCoordinatesRelativeTo, which put a SECOND layout
// query on every mouse event - and humanised movement emits dozens per action.
// Measured: the full Windows e2e went from 2 mouse failures to 7, plus 4
// detector tests that had never failed, all of them timeouts, and all of them
// passing again when the same tests ran alone. A correctness fix that makes
// the browser too slow to click is not a fix.
//
// The identity used instead needs no layout at all:
//
//     screen_real     = topLevelRelative + topLevelWidgetOrigin
//     client          = screen_real - realContentOrigin
//     screen_declared = client + declaredContentOrigin
//                     = screen_real - realContentOrigin + declaredOrigin
//
// realContentOrigin is the root widget's screen offset - the very quantity
// mozInnerScreenX reported before it became a declaration - so the relation
// the gate checks holds by construction, and both terms are widget calls the
// original expression already made.
// The shift is computed by ONE function, the same one mozInnerScreenX and
// mozInnerScreenY call. When the arithmetic lived only here, the plain
// substitution in nsGlobalWindowOuter recreated inside the iframes the
// contradiction that this block removes at the top level - measured on
// 2026-08-10.
//
// The sum stays in integer app units (A + (B + shift): integer addition, the
// same value as (A + B) + shift), and the caller converts to CSS pixels once, exactly as before: no float
// addition is introduced.
inline nsPoint StealthWithContentOrigin(nsPresContext* aPresContext,
                                        const nsPoint& aScreenPoint) {
  // Nothing() (engine off, no PresContext, no root widget, a parent process
  // popup) is the zero shift: the sum then equals stock Firefox's.
  return aScreenPoint +
         StealthContentOriginShift(aPresContext).valueOr(nsPoint());
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthScreenCoords_h
