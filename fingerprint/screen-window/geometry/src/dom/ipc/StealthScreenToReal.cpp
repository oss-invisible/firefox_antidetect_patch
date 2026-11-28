/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared-to-real map of the chrome popups that content anchors on the
// screen; see StealthScreenToReal.h. The three methods are the bodies of the
// [ChromeOnly] members that BrowsingContext.webidl registers on
// CanonicalBrowsingContext, and are called by the parent-side actors only.

#include "StealthScreenToReal.h"

#include "AppUnits.h"
#include "StealthWindowOrigin.h"
#include "mozilla/dom/BrowserParent.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"
#include "mozilla/dom/DOMRect.h"
#include "mozilla/dom/Document.h"
#include "mozilla/dom/DocumentInlines.h"
#include "mozilla/dom/Element.h"
#include "mozilla/dom/WindowGlobalParent.h"
#include "nsPresContext.h"

namespace mozilla {

void StealthMapDragRect(dom::WindowContext* aTopWindowContext,
                        LayoutDeviceIntRect* aRect) {
  dom::WindowGlobalParent* wgp =
      aTopWindowContext ? aTopWindowContext->Canonical() : nullptr;
  dom::BrowserParent* top =
      dom::StealthTopBrowserParent(wgp ? wgp->GetBrowserParent() : nullptr);
  if (!top) {
    return;
  }
  *aRect = StealthRealFromDeclaredDevRect(*aRect,
                                          StealthDeclaredMinusRealOrigin(top));
}

namespace dom {

namespace {

// The map of the tab that a BrowsingContext belongs to. A tab whose top
// document is not in a content process has no BrowserParent: its coordinates
// were never declared, so the map is the identity.
struct StealthScreenMap {
  LayoutDeviceIntPoint mDelta;
  // Device px per CSS px of the chrome page that hosts the tab: the unit of
  // getElementBoundingScreenRect (nsDOMWindowUtils::ToScreenRectInCSSUnits).
  double mDevPxPerCssPx = 1.0;
};

StealthScreenMap StealthScreenMapOf(CanonicalBrowsingContext* aContext) {
  StealthScreenMap map;
  // The BrowserParent that hosts this context's current window, which is the
  // one of a frame, in-process or out-of-process; StealthTopBrowserParent
  // takes it to the tab. The current window global stays set while a tab's
  // process switch is pending, which mCurrentBrowserParent does not.
  WindowGlobalParent* wgp = aContext->GetCurrentWindowGlobal();
  BrowserParent* browserParent = StealthTopBrowserParent(
      wgp ? wgp->GetBrowserParent() : aContext->GetBrowserParent());
  if (!browserParent) {
    return map;
  }
  map.mDelta = StealthDeclaredMinusRealOrigin(browserParent);
  Element* owner = browserParent->GetOwnerElement();
  Document* chromeDoc = owner ? owner->OwnerDoc() : nullptr;
  nsPresContext* presContext = chromeDoc ? chromeDoc->GetPresContext() : nullptr;
  if (presContext && presContext->AppUnitsPerDevPixel() > 0) {
    map.mDevPxPerCssPx = double(AppUnitsPerCSSPixel()) /
                         double(presContext->AppUnitsPerDevPixel());
  }
  return map;
}

}  // namespace

already_AddRefed<DOMRectReadOnly>
CanonicalBrowsingContext::StealthScreenRectToReal(DOMRectReadOnly& aRect) {
  const StealthScreenMap map = StealthScreenMapOf(this);
  return MakeAndAddRef<DOMRectReadOnly>(
      GetParentObject(),
      StealthRealFromDeclaredCssPx(aRect.X(), map.mDelta.x, map.mDevPxPerCssPx),
      StealthRealFromDeclaredCssPx(aRect.Y(), map.mDelta.y, map.mDevPxPerCssPx),
      aRect.Width(), aRect.Height());
}

double CanonicalBrowsingContext::StealthScreenXDevPxToReal(double aXDevPx) {
  return StealthRealFromDeclaredDevPx(aXDevPx,
                                      StealthScreenMapOf(this).mDelta.x);
}

double CanonicalBrowsingContext::StealthScreenYDevPxToReal(double aYDevPx) {
  return StealthRealFromDeclaredDevPx(aYDevPx,
                                      StealthScreenMapOf(this).mDelta.y);
}

}  // namespace dom
}  // namespace mozilla
