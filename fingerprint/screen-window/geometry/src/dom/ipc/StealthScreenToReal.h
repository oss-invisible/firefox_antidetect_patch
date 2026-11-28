/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthScreenToReal_h
#define mozilla_dom_StealthScreenToReal_h

// Chrome popups that content anchors on the screen (firefox-71 root,
// DESIGN-window-origin.md section 3).
//
// Every screen coordinate that a content process computes is DECLARED: it is
// built on the declared window origin W and the declared chrome offset T. The
// parent opens a select, an autocomplete, a picker, a validation bubble, a
// context menu, a tooltip or the image of a drag at the coordinates it
// receives, on the REAL screen. The parent therefore maps each value back, per
// tab:
//
//   p_real = p_declared - d,   d = StealthDeclaredMinusRealOrigin(top tab)
//
// where d is (declared W + declared T) - (real W + real T) in device px of the
// top-level widget (StealthWindowOrigin.h). The map is a translation: it needs
// no scale for a point in device px, and the scale of the chrome page only for
// a rect in CSS px.
//
// The three methods of CanonicalBrowsingContext are [ChromeOnly]: a page has
// no BrowsingContext object to ask. The pure parts are here, so that a gtest
// pins them.

#include "Units.h"

namespace mozilla {

namespace dom {
class WindowContext;
}  // namespace dom

// A point in device px of the top-level widget.
inline double StealthRealFromDeclaredDevPx(double aDeclaredDevPx,
                                           int32_t aDeltaDevPx) {
  return aDeclaredDevPx - double(aDeltaDevPx);
}

// A coordinate in CSS px of the chrome page (what getElementBoundingScreenRect
// returns): d is in device px, the chrome page has aDevPxPerCssPx device px
// per CSS px.
inline double StealthRealFromDeclaredCssPx(double aDeclaredCssPx,
                                           int32_t aDeltaDevPx,
                                           double aDevPxPerCssPx) {
  if (!(aDevPxPerCssPx > 0.0)) {
    return aDeclaredCssPx;
  }
  return aDeclaredCssPx - double(aDeltaDevPx) / aDevPxPerCssPx;
}

inline LayoutDeviceIntRect StealthRealFromDeclaredDevRect(
    const LayoutDeviceIntRect& aDeclared, const LayoutDeviceIntPoint& aDelta) {
  LayoutDeviceIntRect real(aDeclared);
  real.MoveBy(-aDelta.x, -aDelta.y);
  return real;
}

// The rect of a drag image, mapped in place to the real screen. nsBaseDragSession
// calls it in DrawDrag once the rect is final, where the parent consumes what
// the child of aTopWindowContext (the top window context of the drag source)
// sent. The drag service of the parent places the image of the OS drag at it.
// With no top window context in a content process the rect is left as it is.
void StealthMapDragRect(dom::WindowContext* aTopWindowContext,
                        LayoutDeviceIntRect* aRect);

}  // namespace mozilla

#endif  // mozilla_dom_StealthScreenToReal_h
