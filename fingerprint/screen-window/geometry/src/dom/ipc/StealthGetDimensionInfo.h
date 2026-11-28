/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthGetDimensionInfo_h
#define mozilla_dom_StealthGetDimensionInfo_h

// The one out-of-line definition of the window origin declaration. It is
// included by BrowserParent.cpp ONLY, and dom/ipc/moz.build registers no source
// file for it: a second translation unit that included it would define
// BrowserParent::GetDimensionInfo twice. Everything else is in
// StealthWindowOrigin.h, which any file may include.

#include "StealthChromeOffset.h"
#include "StealthScreenToReal.h"
#include "StealthWindowOrigin.h"

namespace mozilla::dom {

// BrowserParent::GetDimensionInfo is ours: Mozilla's body is
// GetDimensionInfo_Mozilla, and both senders (UpdateDimensions, and the first
// DimensionInfo of a window.open tab, in ContentParent.cpp) go through here.
// Defined once, here: BrowserParent.cpp is the only file that includes this.
DimensionInfo BrowserParent::GetDimensionInfo() {
  return StealthDeclaredDimensionInfo(this, GetDimensionInfo_Mozilla());
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthGetDimensionInfo_h
