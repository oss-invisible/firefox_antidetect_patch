/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Chrome popups that content anchors on the screen (firefox-71 root,
// DESIGN-window-origin.md section 3).
//
// A content process computes its screen coordinates from the declared window
// origin and the declared chrome offset, so a rect or a point that a child
// actor sends to its parent actor is declared. The parent opens the popup on
// the real screen: it passes the value through one of these functions first.
// Each one is the [ChromeOnly] method of CanonicalBrowsingContext
// (dom/chrome-webidl/BrowsingContext.webidl, body in dom/ipc/
// StealthScreenToReal.cpp) behind a free function, so that a hook is one line
// of a form the series accepts. Only parent-side code imports this file. A
// null BrowsingContext (a browser that has no frame loader any more) returns
// the value unchanged.
//
//   Rect: CSS px of the chrome page, the unit of getElementBoundingScreenRect.
//   X, Y: device px of the top-level widget, the unit of screenXDevPx.

export function StealthScreenRectToReal(aBrowsingContext, aRect) {
  return aBrowsingContext
    ? aBrowsingContext.stealthScreenRectToReal(aRect)
    : aRect;
}

export function StealthScreenXDevPxToReal(aBrowsingContext, aXDevPx) {
  return aBrowsingContext
    ? aBrowsingContext.stealthScreenXDevPxToReal(aXDevPx)
    : aXDevPx;
}

export function StealthScreenYDevPxToReal(aBrowsingContext, aYDevPx) {
  return aBrowsingContext
    ? aBrowsingContext.stealthScreenYDevPxToReal(aYDevPx)
    : aYDevPx;
}

// A context menu message carries the screen position of the click in device px
// (screenXDevPx, screenYDevPx); the menu and the translations panel both read
// it from the context. Maps it once, in place, and returns the context.
export function StealthContextScreenToReal(aBrowsingContext, aContext) {
  aContext.screenXDevPx = StealthScreenXDevPxToReal(
    aBrowsingContext,
    aContext.screenXDevPx
  );
  aContext.screenYDevPx = StealthScreenYDevPxToReal(
    aBrowsingContext,
    aContext.screenYDevPx
  );
  return aContext;
}
