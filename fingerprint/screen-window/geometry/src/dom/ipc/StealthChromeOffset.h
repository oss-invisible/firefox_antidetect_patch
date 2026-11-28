/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthChromeOffset_h
#define mozilla_dom_StealthChromeOffset_h

// What the parent sends to a child about the chrome offset T, in declared
// space. Header-only: it is included by BrowserParent.cpp (the matrix send) and
// by nsBaseDragService.cpp (the two drag points), whose moz.build already
// reach /dom/ipc, so it needs no line in a moz.build.
//
// THE DEPENDENCY ON StealthWindowOrigin.h: StealthDeclaredChromeOffset (T_decl,
// the declared chrome offset of the top browser of a tab) is declared there,
// not here.
//
// T_real is read from ONE source, BrowserParent::GetChildProcessOffset() of
// the TOP browser: computed straight from the chrome layout, with no message
// of the APZ walk in it, so d does not depend on the order in which a tab's
// and its frames' matrices arrive. After StealthRemoteLayerOffset
// (layout/generic) it is also the translation of the matrix of the top tab.
// The stored mChildToParentConversionMatrix is never changed: every input
// conversion in the parent stays real.

#include "StealthChromeDelta.h"
#include "StealthDeclarationGate.h"
#include "StealthScreenToReal.h"
#include "StealthWindowOrigin.h"
#include "Units.h"
#include "mozilla/Maybe.h"
#include "mozilla/dom/BrowserParent.h"

namespace mozilla::dom {

// d of the tab that aBrowser belongs to; Nothing() with the engine off or
// without a top browser, which means: send the real value.
inline Maybe<LayoutDeviceIntPoint> StealthChromeDeltaOf(
    BrowserParent* aBrowser) {
  if (!aBrowser || !gfx::StealthEngineActive()) {
    return Nothing();
  }
  BrowserParent* top = StealthTopBrowserParent(aBrowser);
  return Some(StealthChromeDelta(StealthDeclaredChromeOffset(top),
                                 top->GetChildProcessOffset()));
}

// SendChildToParentMatrix with the matrix and the rect in declared space:
// M.PostTranslate(d) and the rect moved by d. The original values with the
// engine off.
inline bool StealthSendChildToParentMatrix(
    BrowserParent* aBrowser, const Maybe<gfx::Matrix4x4>& aMatrix,
    const ScreenRect& aRemoteDocumentRect) {
  const Maybe<LayoutDeviceIntPoint> delta = StealthChromeDeltaOf(aBrowser);
  if (!delta) {
    return aBrowser->SendChildToParentMatrix(aMatrix, aRemoteDocumentRect);
  }
  return aBrowser->SendChildToParentMatrix(
      StealthTranslatedMatrix(aMatrix, *delta),
      StealthTranslatedRect(aRemoteDocumentRect, *delta));
}

// A parent-side point that the child of aBrowser takes back through its
// matrix (the end and the drop point of a drag): aPoint + d, aPoint itself
// with the engine off.
inline LayoutDeviceIntPoint StealthDragPoint(
    BrowserParent* aBrowser, const LayoutDeviceIntPoint& aPoint) {
  const Maybe<LayoutDeviceIntPoint> delta = StealthChromeDeltaOf(aBrowser);
  return delta ? StealthTranslatedPoint(aPoint, *delta) : aPoint;
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthChromeOffset_h
