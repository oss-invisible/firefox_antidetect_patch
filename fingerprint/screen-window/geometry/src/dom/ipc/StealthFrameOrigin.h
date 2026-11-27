/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthFrameOrigin_h
#define mozilla_dom_StealthFrameOrigin_h

// Everything is inline, so dom/ipc/moz.build gets no line for it. Included by
// BrowserParent.cpp only.

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "mozilla/Maybe.h"
#include "mozilla/dom/BrowserBridgeParent.h"
#include "mozilla/dom/BrowserParent.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"

namespace mozilla {

// Where an out-of-process iframe sits inside the top document's content, for
// the screen origin the frame reads (StealthScreenCoords.h).
//
// The place is the frame's child-to-top-level-widget matrix with the tab's
// matrix taken off, so the host's real chrome offset cancels and never reaches
// a page (gfx::StealthFrameToTopContent). Both matrices live in the parent
// process only, so the parent computes it and hands it to the frame's process
// in a field of the frame's own BrowsingContext.
//
// Why the field is ParentOnly: a content process cannot write it. The parent
// refuses any transaction on a ParentOnly field that comes from a content
// process (SyncedContext.h:47-49), so a compromised or scripted content
// process cannot set the place of its own frame. No page can reach it either:
// there is no WebIDL attribute and no JS accessor for it, only our C++ in
// StealthScreenCoords.h reads it.
//
// Ordering: the transaction is sent from here, the first statement of
// BrowserParent::SetChildToParentConversionMatrix, so it goes out before
// Mozilla's SendChildToParentMatrix of the same call. Both travel to the
// frame's process on the same PContent channel (PBrowser is managed by
// PContent), so the field is set when the new matrix arrives.
//
// Nothing as the value means "no matrix yet", or "the tab's matrix is not a
// translation": the frame then reads the declared top origin alone.
inline void StealthNoteChildToParentMatrix(
    dom::BrowserParent* aParent,
    const Maybe<LayoutDeviceToLayoutDeviceMatrix4x4>& aMatrix) {
  if (!gfx::StealthEngineActive() || aParent->IsDestroyed() ||
      !aParent->GetBrowserBridgeParent()) {
    return;
  }
  dom::CanonicalBrowsingContext* bc = aParent->GetBrowsingContext();
  if (!bc || bc->IsDiscarded()) {
    return;
  }
  dom::BrowserParent* top = bc->Top()->GetBrowserParent();
  if (!top) {
    return;
  }
  const Maybe<LayoutDeviceToLayoutDeviceMatrix4x4> value =
      aMatrix ? gfx::StealthFrameToTopContent(
                    *aMatrix, top->GetChildToParentConversionMatrix())
              : Nothing();
  if (value != bc->GetStealthFrameToTopContent()) {
    (void)bc->SetStealthFrameToTopContent(value);
  }
}

}  // namespace mozilla

#endif  // mozilla_dom_StealthFrameOrigin_h
