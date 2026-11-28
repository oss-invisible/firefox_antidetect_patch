/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthSnapOffset_h
#define mozilla_StealthSnapOffset_h

// The pure part of StealthRemoteLayerOffset.h (the rounding, with no frame and
// no process in it), so a gtest runs it as it is. Header-only: it needs no line
// in a moz.build of layout.

#include "Units.h"
#include "nsCoord.h"

namespace mozilla {

// aOffset rounded to a whole number of device pixels on each axis, as
// LayoutDeviceIntPoint::FromAppUnitsRounded rounds the same point in app units.
inline LayoutDevicePoint StealthSnapToWholeDevicePx(
    const LayoutDevicePoint& aOffset) {
  return LayoutDevicePoint(float(NSToIntRound(aOffset.x)),
                           float(NSToIntRound(aOffset.y)));
}

}  // namespace mozilla

#endif  // mozilla_StealthSnapOffset_h
