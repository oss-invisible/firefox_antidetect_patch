/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthRemoteLayerOffset_h
#define mozilla_StealthRemoteLayerOffset_h

// Header-only on purpose: it is included by nsSubDocumentFrame.cpp alone (the
// hook), so it needs no line in a moz.build of layout. The rounding itself is
// in StealthSnapOffset.h, which dom/ipc/gtest runs as it is.
//
// THE CHROME OFFSET T IS WHOLE AT ITS BIRTH.
//
// The parent's remote browser (the <browser> of a chrome window) is composited
// at nsDisplayRemote::mOffset, the unrounded layout offset of its frame. That
// float is the translation of the matrix that BrowserParent sends to the child
// (SendChildToParentMatrix), so every input event's client coordinate in the
// child is R(R(x*s + T) - T) with a fractional T: off by one depending on the
// host's chrome layout (a Linux title bar, a font-sized toolbar, scale 1.75).
// With a whole T the same expression is R(x*s) on every host, which is what
// retail gives at the scales where its chrome heights are whole.
//
// The rounding is the one BrowserParent::GetChildProcessOffset() applies to
// the same point: LayoutDeviceIntPoint::FromAppUnitsRounded, that is
// NSToIntRound(float(au) / float(appUnitsPerDevPixel)) on each axis.
// LayoutDevicePoint::FromAppUnits computes the very same float, so rounding
// it with NSToIntRound is that function, bit for bit (a gtest sweeps it).
//
// Only a remote browser laid out in a chrome document of the parent process is
// snapped: a frame in a content process keeps its offset F as Mozilla computes
// it, because F is read by the page (mozInnerScreen, screenX in an
// out-of-process iframe).

#include "StealthDeclarationGate.h"
#include "StealthSnapOffset.h"
#include "Units.h"
#include "nsIFrame.h"
#include "nsPresContext.h"
#include "nsXULAppAPI.h"

namespace mozilla {

// The layer offset of a nsDisplayRemote: aOffset (Mozilla's, unrounded)
// unless the engine is on and the frame is a remote browser of a chrome
// document in the parent process, where it is whole.
inline LayoutDevicePoint StealthRemoteLayerOffset(
    const nsIFrame* aFrame, const LayoutDevicePoint& aOffset) {
  if (!gfx::StealthEngineActive() || !XRE_IsParentProcess() || !aFrame ||
      !aFrame->PresContext()->IsChrome()) {
    return aOffset;
  }
  return StealthSnapToWholeDevicePx(aOffset);
}

}  // namespace mozilla

#endif  // mozilla_StealthRemoteLayerOffset_h
