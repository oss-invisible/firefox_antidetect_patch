/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef TOOLKIT_COMPONENTS_WINDOWWATCHER_STEALTHWINDOWPLACEMENT_H_
#define TOOLKIT_COMPONENTS_WINDOWWATCHER_STEALTHWINDOWPLACEMENT_H_

#include "Units.h"
#include "mozilla/Maybe.h"

class nsIBaseWindow;

namespace mozilla {

/**
 * What window.open's features gave, as SizeOpenedWindow's SizeSpec holds it:
 * the position in desktop pixels, the sizes in CSS pixels. Nothing() = the page
 * gave none.
 */
struct StealthPopupFeatures {
  Maybe<int32_t> mLeft;
  Maybe<int32_t> mTop;
  Maybe<int32_t> mOuterWidth;
  Maybe<int32_t> mOuterHeight;
  Maybe<int32_t> mInnerWidth;
  Maybe<int32_t> mInnerHeight;
};

/**
 * Called by SizeOpenedWindow (nsWindowWatcher.cpp) right after it has set
 * `positionSpecified` from the page's features. left and top were taken from
 * the features before; the statements between them and this call only set the
 * local width and height, which this function neither reads nor writes.
 *
 * A window a page opens without left/top is born at the declared default
 * position. Writes aLeft only when no left was given and aTop only when no top
 * was, and then sets aPositionSpecified (the caller treats the position as
 * specified); nothing written and nothing read from the window for a chrome
 * caller, or when the engine is off.
 *
 * It also DECLARES the popup's position (StealthDeclaredPopupPosition: the
 * markup's 4, the stagger, the clamp into the declared work area, from the
 * declared frame and the declared positions of the other browser windows) and
 * stores it on the new window's top CanonicalBrowsingContext
 * (StealthSetPopupPosition). The real window's position is never read.
 */
void StealthPlacePopup(bool aIsCallerChrome, nsIBaseWindow* aTreeOwnerAsWin,
                       const StealthPopupFeatures& aFeatures,
                       DesktopIntCoord& aLeft, DesktopIntCoord& aTop,
                       bool& aPositionSpecified);

/**
 * The hook's entry: SizeOpenedWindow passes its SizeSpec, a type local to
 * nsWindowWatcher.cpp, and this copies the six fields the rule reads.
 */
template <typename SizeSpecT>
void StealthPlacePopupAtDefault(bool aIsCallerChrome,
                                nsIBaseWindow* aTreeOwnerAsWin,
                                const SizeSpecT& aSizeSpec,
                                DesktopIntCoord& aLeft, DesktopIntCoord& aTop,
                                bool& aPositionSpecified) {
  StealthPopupFeatures features;
  auto copy = [](Maybe<int32_t>& aTo, const auto& aFrom) {
    if (aFrom) {
      aTo = Some(int32_t(aFrom->value));
    }
  };
  copy(features.mLeft, aSizeSpec.mLeft);
  copy(features.mTop, aSizeSpec.mTop);
  copy(features.mOuterWidth, aSizeSpec.mOuterWidth);
  copy(features.mOuterHeight, aSizeSpec.mOuterHeight);
  copy(features.mInnerWidth, aSizeSpec.mInnerWidth);
  copy(features.mInnerHeight, aSizeSpec.mInnerHeight);
  StealthPlacePopup(aIsCallerChrome, aTreeOwnerAsWin, features, aLeft, aTop,
                    aPositionSpecified);
}

}  // namespace mozilla

#endif  // TOOLKIT_COMPONENTS_WINDOWWATCHER_STEALTHWINDOWPLACEMENT_H_
