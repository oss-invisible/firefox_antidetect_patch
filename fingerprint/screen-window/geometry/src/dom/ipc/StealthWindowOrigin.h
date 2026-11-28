/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthWindowOrigin_h
#define mozilla_dom_StealthWindowOrigin_h

// The window origin W and the chrome offset T, declared where Firefox builds
// them for the content process: in the parent, in the DimensionInfo that
// BrowserParent sends. No content process holds the host's window position, so
// Firefox's own code in the child (screenX/Y, outerWidth/Height, mozInnerScreen,
// the screen coordinates of events) reads the declared values with no
// correction of ours.
//
// Header-only, every function inline: any translation unit of dom/ipc and
// widget may include it (the parent-side maps of the screen coordinates do).
// The one out-of-line definition, BrowserParent::GetDimensionInfo, is in
// StealthGetDimensionInfo.h, which BrowserParent.cpp ALONE includes. The
// arithmetic is in gfx/thebes/StealthDeclarationGate
// (StealthDeclaredWindowDimensions, StealthRealOuterRequest), where the gtests
// call it.
//
// Main thread, parent process only.

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "mozilla/DimensionRequest.h"
#include "mozilla/Maybe.h"
#include "mozilla/dom/BrowserParent.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"
#include "nsCOMPtr.h"
#include "nsIWidget.h"

namespace mozilla::dom {

// THE ONE LOOKUP OF THE TOP: the BrowserParent of the tab (or popup) whose
// window the content of aParent is in. Every parent-side site of the window
// origin goes through it: the declared DimensionInfo, the map of the chrome
// popups (StealthScreenToReal), the matrix and drag-point sends
// (StealthChromeOffset), and the ChromeOnly methods of
// CanonicalBrowsingContext. aParent is the BrowserParent that hosts the
// content in question; nullptr gives nullptr.
//
// It follows the BrowserBridgeParent chain (BrowserParent::TopLevelBrowserParent):
// - a tab, or a popup: no bridge, so aParent itself;
// - an in-process frame: it lives in its tab's BrowserParent, so the tab;
// - an out-of-process frame, at any depth: each level's bridge is managed by
//   the BrowserParent of its embedder, so the chain ends at the tab.
// It reads no BrowsingContext state. The two other ways to the top do:
// Top()->GetBrowserParent() is mCurrentBrowserParent, which nsFrameLoader::
// SetWillChangeProcess clears while a tab's process switch is pending (the
// old BrowserParent is still the tab and still sends), and
// Top()->GetCurrentWindowGlobal() is null between two loads. The bridge
// pointer is set by BrowserBridgeParent::Init, before the frame's first
// message from the child.
inline BrowserParent* StealthTopBrowserParent(BrowserParent* aParent) {
  return aParent ? aParent->TopLevelBrowserParent() : nullptr;
}

// BrowserParent names this struct as its friend: its static functions read the
// private state of the BrowserParents of one tab (its real rect and inner size,
// its scale), which the declaration is built from.
struct StealthWindowOrigin {
  // The declared state of aParent's window: the top's declared state, plus the
  // top's real inner size and aParent's own real outer size.
  static gfx::StealthWindowState StateOf(BrowserParent* aParent) {
    BrowserParent* top = StealthTopBrowserParent(aParent);
    gfx::StealthWindowState state;
    BrowsingContext* topContext =
        aParent->mBrowsingContext ? aParent->mBrowsingContext->Top() : nullptr;
    state.mPopup = topContext && topContext->GetIsPopupRequested();
    if (state.mPopup) {
      state.mPopupPosition = topContext->Canonical()->StealthPopupPosition();
    }
    // The size mode of the top-level widget: the bridged BrowserParent's own
    // mSizeMode is never updated.
    nsCOMPtr<nsIWidget> widget = aParent->GetTopLevelWidget();
    state.mFullscreen = widget && widget->SizeMode() == nsSizeMode_Fullscreen;
    state.mTopInner = top->mDimensions;
    state.mRealOuter = aParent->mRect.Size();
    state.mBridged = aParent->GetBrowserBridgeParent() != nullptr;
    return state;
  }

  // The declared window of aParent: the outer rect, the client offset and the
  // chrome offset. Nothing() with the engine off.
  static Maybe<gfx::StealthDeclaredDimensions> DeclaredDimensions(
      BrowserParent* aParent) {
    return gfx::StealthDeclaredWindowDimensionsNow(aParent->mDefaultScale,
                                                   StateOf(aParent));
  }

  // aReal (what Mozilla built from the real window) with the window rect, the
  // client offset and the chrome offset declared. The size stays real.
  static DimensionInfo Declared(BrowserParent* aParent,
                                const DimensionInfo& aReal) {
    const Maybe<gfx::StealthDeclaredDimensions> declared =
        DeclaredDimensions(aParent);
    if (declared.isNothing()) {
      return aReal;
    }
    const CSSRect unscaledRect = declared->mRect / aParent->mDefaultScale;
    return DimensionInfo(unscaledRect, aReal.size(), declared->mClientOffset,
                         declared->mChromeOffset);
  }

  // The chrome offset T that Declared() sends for aTop, a top-level
  // BrowserParent. With the engine off, the real one, which is what
  // GetDimensionInfo_Mozilla sends.
  static LayoutDeviceIntPoint DeclaredChromeOffset(BrowserParent* aTop) {
    const Maybe<gfx::StealthDeclaredDimensions> declared =
        DeclaredDimensions(aTop);
    return declared ? declared->mChromeOffset : aTop->GetChildProcessOffset();
  }

  // (declared W + declared T) - (real W + real T) of the top-level BrowserParent
  // of aParent, in device px of the top-level widget. W is the outer rect's
  // origin plus the client offset, T the chrome offset; the real ones are the
  // top's mRect, mClientOffset and GetChildProcessOffset(). (0, 0) with the
  // engine off.
  static LayoutDeviceIntPoint DeclaredMinusRealOrigin(BrowserParent* aParent) {
    BrowserParent* top = StealthTopBrowserParent(aParent);
    const Maybe<gfx::StealthDeclaredDimensions> declared =
        DeclaredDimensions(top);
    if (declared.isNothing()) {
      return LayoutDeviceIntPoint();
    }
    const LayoutDeviceIntPoint declaredOrigin = declared->mRect.TopLeft() +
                                                declared->mClientOffset +
                                                declared->mChromeOffset;
    const LayoutDeviceIntPoint realOrigin =
        top->mRect.TopLeft() + top->mClientOffset + top->GetChildProcessOffset();
    return declaredOrigin - realOrigin;
  }

  static Maybe<int32_t> ValueOf(const Maybe<LayoutDeviceIntCoord>& aCoord) {
    return aCoord ? Some(int32_t(aCoord->value)) : Nothing();
  }

  static Maybe<LayoutDeviceIntCoord> CoordOf(const Maybe<int32_t>& aValue) {
    return aValue ? Some(LayoutDeviceIntCoord(*aValue)) : Nothing();
  }

  // Send the declared DimensionInfo again, to the tab and to its
  // out-of-process frames. BrowserParent::UpdateDimensions only sends when a
  // REAL input changed; a declared position changes none of them.
  static void Resend(BrowserParent* aTop) {
    if (!aTop->mBrowsingContext) {
      return;
    }
    aTop->mBrowsingContext->PreOrderWalk([](BrowsingContext* aContext) {
      BrowserParent* parent = aContext->Canonical()->GetBrowserParent();
      if (parent && !parent->mIsDestroyed && parent->mUpdatedDimensions) {
        (void)parent->SendUpdateDimensions(parent->GetDimensionInfo());
      }
    });
  }

  // A request from the content process, in declared space (the page reads the
  // declared window, so its moveTo/moveBy/resizeTo/resizeBy are computed from
  // it), as the request for the real window. A requested position is also the
  // popup's new declared position.
  static DimensionRequest RealRequest(BrowserParent* aParent,
                                      DimensionRequest&& aRequest) {
    if (aRequest.mDimensionKind != DimensionKind::Outer) {
      // The inner size is the same on both sides.
      return std::move(aRequest);
    }
    BrowserParent* top = StealthTopBrowserParent(aParent);
    const gfx::StealthWindowState state = StateOf(top);
    const Maybe<gfx::StealthDeclaredDimensions> declared =
        gfx::StealthDeclaredWindowDimensionsNow(top->mDefaultScale, state);
    if (declared.isNothing()) {
      return std::move(aRequest);
    }
    const gfx::StealthOuterRequest asked{
        ValueOf(aRequest.mX), ValueOf(aRequest.mY), ValueOf(aRequest.mWidth),
        ValueOf(aRequest.mHeight)};
    if (state.mPopup) {
      const LayoutDeviceIntPoint current = declared->mRect.TopLeft();
      const Maybe<LayoutDeviceIntPoint> moved =
          gfx::StealthRequestedPosition(asked, current);
      if (moved && *moved != current) {
        top->mBrowsingContext->StealthSetPopupPosition(*moved);
        Resend(top);
      }
    }
    const gfx::StealthOuterRequest real =
        gfx::StealthRealOuterRequest(asked, declared->mRect, top->mRect);
    aRequest.mX = CoordOf(real.mX);
    aRequest.mY = CoordOf(real.mY);
    aRequest.mWidth = CoordOf(real.mWidth);
    aRequest.mHeight = CoordOf(real.mHeight);
    return std::move(aRequest);
  }
};

// The DimensionInfo of aParent as the content process is to read it.
inline DimensionInfo StealthDeclaredDimensionInfo(BrowserParent* aParent,
                                                  const DimensionInfo& aReal) {
  return StealthWindowOrigin::Declared(aParent, aReal);
}

// The request for the real window that a declared-space request stands for.
inline DimensionRequest StealthRealDimensionRequest(
    BrowserParent* aParent, DimensionRequest&& aRequest) {
  return StealthWindowOrigin::RealRequest(aParent, std::move(aRequest));
}

// What the parent-side maps of the screen coordinates read
// (StealthScreenToReal.h, StealthChromeOffset.h): d = (declared W + declared T)
// - (real W + real T) of the top browser of aParent, in device px.
inline LayoutDeviceIntPoint StealthDeclaredMinusRealOrigin(
    BrowserParent* aParent) {
  return StealthWindowOrigin::DeclaredMinusRealOrigin(aParent);
}

// The chrome offset T that StealthDeclaredDimensionInfo declares for aTop, the
// top-level BrowserParent of a tab, in device px.
inline LayoutDeviceIntPoint StealthDeclaredChromeOffset(BrowserParent* aTop) {
  return StealthWindowOrigin::DeclaredChromeOffset(aTop);
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthWindowOrigin_h
