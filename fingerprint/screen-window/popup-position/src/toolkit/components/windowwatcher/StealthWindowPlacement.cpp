/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthWindowPlacement.h"

#include <cmath>

#include "StealthDeclarationGate.h"
#include "mozilla/Assertions.h"
#include "mozilla/Maybe.h"
#include "mozilla/StaticPrefs_layout.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"
#include "nsCOMPtr.h"
#include "nsIAppWindow.h"
#include "nsIBaseWindow.h"
#include "nsIDocShellTreeOwner.h"
#include "nsISimpleEnumerator.h"
#include "nsIWindowMediator.h"
#include "nsServiceManagerUtils.h"
#include "nsTArray.h"

namespace mozilla {

void dom::CanonicalBrowsingContext::StealthSetPopupPosition(
    const LayoutDeviceIntPoint& aPoint) {
  mStealthPopupPosition = Some(aPoint);
}

namespace {

// Declares the popup's position and stores it on its top browsing context.
// Everything read here is declared: the frame, the work area, the scale, and
// the positions the other browser windows were declared at. The real position
// of any window is never read, so on Linux the window manager's choice, and on
// Windows the host's screen, never reach the page.
void DeclarePopupPosition(nsIBaseWindow* aTreeOwnerAsWin,
                          const StealthPopupFeatures& aFeatures,
                          const gfx::StealthWindowFrame& aFrame,
                          const DesktopToLayoutDeviceScale& aDesktopToDevice) {
  const Maybe<LayoutDeviceIntRect> avail = gfx::StealthDeclaredAvailDeviceRect();
  const float scale = StaticPrefs::layout_css_devPixelsPerPx();
  if (!avail || !(scale > 0.0f)) {
    return;
  }
  nsCOMPtr<nsIDocShellTreeOwner> owner = do_QueryInterface(aTreeOwnerAsWin);
  if (!owner) {
    return;
  }
  RefPtr<dom::BrowsingContext> own;
  owner->GetPrimaryContentBrowsingContext(getter_AddRefs(own));
  if (!own) {
    return;
  }
  dom::BrowsingContext* ownTop = own->Top();

  // The other browser windows at their DECLARED positions: a popup where it was
  // declared at birth, any other (the maximized main window) at (-border,
  // -border). StaggerPosition looks at the same windows (AppWindow.cpp:1395).
  nsTArray<LayoutDeviceIntPoint> others;
  nsCOMPtr<nsIWindowMediator> mediator =
      do_GetService(NS_WINDOWMEDIATOR_CONTRACTID);
  if (mediator) {
    nsCOMPtr<nsISimpleEnumerator> windows;
    mediator->GetAppWindowEnumerator(u"navigator:browser",
                                     getter_AddRefs(windows));
    bool more = false;
    while (windows && NS_SUCCEEDED(windows->HasMoreElements(&more)) && more) {
      nsCOMPtr<nsISupports> next;
      windows->GetNext(getter_AddRefs(next));
      nsCOMPtr<nsIAppWindow> other = do_QueryInterface(next);
      if (!other) {
        continue;
      }
      RefPtr<dom::BrowsingContext> bc;
      other->GetPrimaryContentBrowsingContext(getter_AddRefs(bc));
      if (bc && bc->Top() == ownTop) {
        continue;  // this window
      }
      Maybe<LayoutDeviceIntPoint> declared;
      if (bc) {
        declared = bc->Top()->Canonical()->StealthPopupPosition();
      }
      others.AppendElement(declared ? *declared
                                    : LayoutDeviceIntPoint(-aFrame.mBorder,
                                                           -aFrame.mBorder));
    }
  }

  // CalcSizeSpec's desktop pixels are device pixels on Windows (the
  // desktop-to-device scale is 1); the declared model is Windows.
  auto toDevice = [&](const Maybe<int32_t>& aDesktop) -> Maybe<int32_t> {
    if (!aDesktop) {
      return Nothing();
    }
    return Some(int32_t(std::lround(float(*aDesktop) * aDesktopToDevice.scale)));
  };
  gfx::StealthPopupRequest request;
  request.mLeft = toDevice(aFeatures.mLeft);
  request.mTop = toDevice(aFeatures.mTop);
  // SizeOpenedWindow gives an outer size priority over an inner one.
  request.mWidth = aFeatures.mOuterWidth ? aFeatures.mOuterWidth
                                         : aFeatures.mInnerWidth;
  request.mHeight = aFeatures.mOuterHeight ? aFeatures.mOuterHeight
                                           : aFeatures.mInnerHeight;
  request.mWidthIsInner =
      aFeatures.mOuterWidth.isNothing() && aFeatures.mInnerWidth.isSome();
  request.mHeightIsInner =
      aFeatures.mOuterHeight.isNothing() && aFeatures.mInnerHeight.isSome();

  own->Top()->Canonical()->StealthSetPopupPosition(
      gfx::StealthDeclaredPopupPosition(request, aFrame, *avail, scale,
                                        others));
}

}  // namespace

void StealthPlacePopup(bool aIsCallerChrome, nsIBaseWindow* aTreeOwnerAsWin,
                       const StealthPopupFeatures& aFeatures,
                       DesktopIntCoord& aLeft, DesktopIntCoord& aTop,
                       bool& aPositionSpecified) {
  // Stealth: a window a PAGE opens without left/top is born at the declared
  // default position, not wherever the host puts it (70-known-bugs.md B258).
  // Retail Firefox 151 on Windows 11 opens it at 4,4 device pixels (3,3 CSS at
  // 125%, 2,2 at 200%); the host would put it anywhere - Windows staggers from
  // the opener, a bare X server has no window manager at all - and a popup's
  // screenX is its REAL position (nsGlobalWindowOuter::GetScreenXY). Blocked
  // here, at birth, so both builds have the same real position and nothing
  // corrects it afterwards (engine rule 3). Chrome callers keep the stock
  // behaviour.
  //
  // A position the page DOES give needs nothing for the REAL window:
  // CalcSizeSpec has already turned its CSS pixels into desktop pixels with
  // the opener's own CSS-to-desktop scale, which carries the persona's scale
  // and the host display's together. Measured on the Linux build at 1.25, 1.5
  // and 2: a second conversion here put left=100 at screenX 125, 150 and 200.
  //
  // What the PAGE reads is not the real window's position. It is the position
  // declared at birth, below (DeclarePopupPosition), computed from declared
  // inputs only.
  if (aIsCallerChrome) {
    return;
  }
  const Maybe<gfx::StealthWindowFrame> stealthFrame =
      gfx::StealthDeclaredWindowFrame();
  if (!stealthFrame) {
    return;
  }
  MOZ_ASSERT(aTreeOwnerAsWin);
  const DesktopToLayoutDeviceScale devToDesktop =
      aTreeOwnerAsWin->DevicePixelsPerDesktopPixel();
  const DesktopIntCoord byDefault = DesktopIntCoord(
      (LayoutDeviceCoord(stealthFrame->mPopupPosition) / devToDesktop)
          .Rounded());
  if (aFeatures.mLeft.isNothing()) {
    aLeft = byDefault;
  }
  if (aFeatures.mTop.isNothing()) {
    aTop = byDefault;
  }
  aPositionSpecified = true;
  DeclarePopupPosition(aTreeOwnerAsWin, aFeatures, *stealthFrame, devToDesktop);
}

}  // namespace mozilla
