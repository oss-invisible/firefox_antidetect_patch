/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthChromeDelta_h
#define mozilla_dom_StealthChromeDelta_h

// The arithmetic of the chrome offset, with no process or frame in it, so a
// gtest runs it as it is. Header-only: it is included by
// StealthChromeOffset.h and by dom/ipc/gtest, so it needs no line in a
// moz.build of dom/ipc.
//
// d = T_decl - T_real: the declared chrome offset of the top browser of a tab
// minus the real one. The real chrome offset is whole at its birth
// (layout/generic/StealthRemoteLayerOffset.h), and the declared one is
// integer device pixels, so d is a whole number and nothing below rounds.
//
// The child sees every parent-side point p through M_decl = M.PostTranslate(d):
// M_decl(c) = M(c) + d for any M (translation, scale, rotation, perspective
// included), so M_decl^-1(p + d) = M^-1(p). A parent-side point that the child
// takes back (a rect of the viewport, the end and the drop point of a drag)
// therefore travels as p + d.

#include "Units.h"
#include "mozilla/Maybe.h"
#include "mozilla/gfx/Matrix.h"

namespace mozilla::dom {

inline LayoutDeviceIntPoint StealthChromeDelta(
    const LayoutDeviceIntPoint& aDeclared, const LayoutDeviceIntPoint& aReal) {
  return aDeclared - aReal;
}

// The matrix as the child sees it: aMatrix, then the translation aDelta.
inline Maybe<gfx::Matrix4x4> StealthTranslatedMatrix(
    const Maybe<gfx::Matrix4x4>& aMatrix, const LayoutDeviceIntPoint& aDelta) {
  if (!aMatrix) {
    return aMatrix;
  }
  gfx::Matrix4x4 matrix = *aMatrix;
  matrix.PostTranslate(float(aDelta.x), float(aDelta.y), 0.0f);
  return Some(matrix);
}

inline ScreenRect StealthTranslatedRect(const ScreenRect& aRect,
                                        const LayoutDeviceIntPoint& aDelta) {
  ScreenRect rect = aRect;
  rect.MoveBy(float(aDelta.x), float(aDelta.y));
  return rect;
}

inline LayoutDeviceIntPoint StealthTranslatedPoint(
    const LayoutDeviceIntPoint& aPoint, const LayoutDeviceIntPoint& aDelta) {
  return aPoint + aDelta;
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthChromeDelta_h
