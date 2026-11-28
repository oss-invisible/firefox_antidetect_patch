/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The chrome offset T is whole at its birth and the child sees it declared:
//  - the snap of nsDisplayRemote::mOffset is the rounding of
//    BrowserParent::GetChildProcessOffset (LayoutDeviceIntPoint::
//    FromAppUnitsRounded) for every app-unit point and every scale;
//  - M.PostTranslate(d) with d = T_decl - T_real is exact for a translation, a
//    scale and a rotation: M_decl^-1(r + d) = M^-1(r) and M_decl(c) = M(c) + d;
//  - the end and the drop point of a drag travel as p + d, a whole number, and
//    the child gets back the point it would have got without the declaration.

#include <cmath>

#include "StealthChromeDelta.h"
#include "StealthSnapOffset.h"
#include "Units.h"
#include "gtest/gtest.h"
#include "mozilla/gfx/Matrix.h"
#include "nsPoint.h"

using namespace mozilla;
using namespace mozilla::dom;

namespace {

// The app units per device pixel of the four persona scales (60 / scale), of
// 1.75 where retail's own chrome offset is fractional, and of two odd ones.
const int32_t kAppUnitsPerDevPx[] = {60, 48, 40, 34, 30, 27, 25};

}  // namespace

TEST(StealthChromeOffset, TheSnapIsTheRoundingOfGetChildProcessOffset)
{
  for (int32_t apd : kAppUnitsPerDevPx) {
    // Every app-unit offset from -3 to +300 device pixels in steps that hit
    // whole pixels, halves (the ties of the rounding) and everything between.
    for (int32_t x = -3 * apd; x <= 300 * apd; x += 7) {
      for (int32_t y :
           {0, 1, apd / 2, apd - 1, apd, 44 * 60, 77 * apd + apd / 2}) {
        const nsPoint au(x, y);
        const LayoutDevicePoint raw = LayoutDevicePoint::FromAppUnits(au, apd);
        const LayoutDevicePoint snapped = StealthSnapToWholeDevicePx(raw);
        const LayoutDeviceIntPoint rounded =
            LayoutDeviceIntPoint::FromAppUnitsRounded(au, apd);
        EXPECT_EQ(snapped.x, float(rounded.x.value))
            << "x=" << x << " apd=" << apd;
        EXPECT_EQ(snapped.y, float(rounded.y.value))
            << "y=" << y << " apd=" << apd;
      }
    }
  }
}

TEST(StealthChromeOffset, TheSnapIsWholeAndMovesAtMostHalfAPixel)
{
  // 44 CSS px of chrome at 1.75: 2640 app units over 34 per device pixel is
  // 77.65 device pixels, the one value where retail's own offset is fractional.
  const LayoutDevicePoint raw =
      LayoutDevicePoint::FromAppUnits(nsPoint(0, 2640), 34);
  EXPECT_GT(raw.y, 77.6f);
  EXPECT_LT(raw.y, 77.7f);
  const LayoutDevicePoint snapped = StealthSnapToWholeDevicePx(raw);
  EXPECT_EQ(snapped.x, 0.0f);
  EXPECT_EQ(snapped.y, 78.0f);
  for (float v = -5.0f; v < 200.0f; v += 0.0625f) {
    const LayoutDevicePoint s =
        StealthSnapToWholeDevicePx(LayoutDevicePoint(v, v));
    EXPECT_EQ(s.x, float(int32_t(s.x)));
    EXPECT_LE(std::abs(s.x - v), 0.5f);
  }
  // A whole offset is left as it is.
  const LayoutDevicePoint whole =
      StealthSnapToWholeDevicePx(LayoutDevicePoint(120.0f, 85.0f));
  EXPECT_EQ(whole.x, 120.0f);
  EXPECT_EQ(whole.y, 85.0f);
}

TEST(StealthChromeOffset, TheDeltaIsTheDeclaredMinusTheRealOffset)
{
  const LayoutDeviceIntPoint d = StealthChromeDelta(
      LayoutDeviceIntPoint(0, 74), LayoutDeviceIntPoint(1, 78));
  EXPECT_EQ(d.x.value, -1);
  EXPECT_EQ(d.y.value, -4);
}

static void ExpectDeclaredSpaceIsExact(const gfx::Matrix4x4& aMatrix,
                                       const LayoutDeviceIntPoint& aDelta) {
  const Maybe<gfx::Matrix4x4> declared =
      StealthTranslatedMatrix(Some(aMatrix), aDelta);
  ASSERT_TRUE(declared.isSome());
  const Maybe<gfx::Matrix4x4> inverse = aMatrix.MaybeInverse();
  const Maybe<gfx::Matrix4x4> declaredInverse = declared->MaybeInverse();
  ASSERT_TRUE(inverse.isSome());
  ASSERT_TRUE(declaredInverse.isSome());
  for (float x : {0.0f, 1.0f, 17.0f, 640.0f, 1919.0f}) {
    for (float y : {0.0f, 3.0f, 89.0f, 700.0f, 1079.0f}) {
      const gfx::Point child(x, y);
      // M_decl(c) = M(c) + d.
      const gfx::Point real = aMatrix.TransformPoint(child);
      const gfx::Point decl = declared->TransformPoint(child);
      EXPECT_NEAR(decl.x, real.x + float(aDelta.x), 5e-3f);
      EXPECT_NEAR(decl.y, real.y + float(aDelta.y), 5e-3f);
      // M_decl^-1(r + d) = M^-1(r).
      const gfx::Point parent(x + 5.0f, y + 9.0f);
      const gfx::Point back = inverse->TransformPoint(parent);
      const gfx::Point backDeclared = declaredInverse->TransformPoint(
          gfx::Point(parent.x + float(aDelta.x), parent.y + float(aDelta.y)));
      EXPECT_NEAR(backDeclared.x, back.x, 5e-3f);
      EXPECT_NEAR(backDeclared.y, back.y, 5e-3f);
    }
  }
}

TEST(StealthChromeOffset, PostTranslateIsExactForATranslation)
{
  ExpectDeclaredSpaceIsExact(gfx::Matrix4x4::Translation(0.0f, 78.0f, 0.0f),
                             LayoutDeviceIntPoint(-1, -4));
  ExpectDeclaredSpaceIsExact(gfx::Matrix4x4::Translation(3.0f, 94.0f, 0.0f),
                             LayoutDeviceIntPoint(2, 11));
}

TEST(StealthChromeOffset, PostTranslateIsExactForAScale)
{
  gfx::Matrix4x4 m = gfx::Matrix4x4::Scaling(0.8f, 0.8f, 1.0f);
  m.PostTranslate(0.0f, 78.0f, 0.0f);
  ExpectDeclaredSpaceIsExact(m, LayoutDeviceIntPoint(0, -4));
  gfx::Matrix4x4 n = gfx::Matrix4x4::Scaling(2.0f, 0.5f, 1.0f);
  n.PostTranslate(40.0f, 51.0f, 0.0f);
  ExpectDeclaredSpaceIsExact(n, LayoutDeviceIntPoint(-7, 3));
}

TEST(StealthChromeOffset, PostTranslateIsExactForARotation)
{
  gfx::Matrix4x4 m;
  m.RotateZ(0.3);
  m.PostTranslate(0.0f, 78.0f, 0.0f);
  ExpectDeclaredSpaceIsExact(m, LayoutDeviceIntPoint(1, -4));
  gfx::Matrix4x4 n;
  n.RotateZ(-1.2);
  n.PostTranslate(12.0f, 61.0f, 0.0f);
  ExpectDeclaredSpaceIsExact(n, LayoutDeviceIntPoint(-5, 9));
}

TEST(StealthChromeOffset, ANothingMatrixStaysNothingAndTheRectMovesByTheDelta)
{
  const Maybe<gfx::Matrix4x4> none;
  EXPECT_TRUE(
      StealthTranslatedMatrix(none, LayoutDeviceIntPoint(3, 4)).isNothing());

  const ScreenRect rect(10.0f, 100.0f, 640.0f, 480.0f);
  const ScreenRect moved =
      StealthTranslatedRect(rect, LayoutDeviceIntPoint(-1, -4));
  EXPECT_EQ(moved.x, 9.0f);
  EXPECT_EQ(moved.y, 96.0f);
  EXPECT_EQ(moved.width, 640.0f);
  EXPECT_EQ(moved.height, 480.0f);

  // With d = 0 nothing moves.
  const ScreenRect same =
      StealthTranslatedRect(rect, LayoutDeviceIntPoint(0, 0));
  EXPECT_EQ(same.x, rect.x);
  EXPECT_EQ(same.y, rect.y);
}

TEST(StealthChromeOffset,
     TheDragPointsTravelAsAPlusDAndTheChildGetsTheRealOnesBack)
{
  // For each scale the real chrome offset is the snapped one; the declared one
  // is any whole offset. The parent's end point and drop point p are in the
  // real chrome window; the child takes them back through M_decl.
  const struct {
    int32_t apd;
    int32_t chromeAu;
  } scales[] = {{60, 2640}, {48, 2640}, {40, 2640}, {34, 2640}};
  for (const auto& s : scales) {
    const LayoutDeviceIntPoint real = LayoutDeviceIntPoint::FromAppUnitsRounded(
        nsPoint(0, s.chromeAu), s.apd);
    for (int32_t declaredY : {70, 74, 89, 106}) {
      const LayoutDeviceIntPoint declared(0, declaredY);
      const LayoutDeviceIntPoint d = StealthChromeDelta(declared, real);
      const LayoutDeviceIntPoint p(500, 300);
      const LayoutDeviceIntPoint sent = StealthTranslatedPoint(p, d);
      // Whole in, whole out: nothing is rounded.
      EXPECT_EQ(sent.x.value, p.x.value + d.x.value);
      EXPECT_EQ(sent.y.value, p.y.value + d.y.value);
      // The child's matrix is M_decl: translation T_decl. What it gets back is
      // sent - T_decl, which is p - T_real: the point without the declaration.
      EXPECT_EQ(sent.x.value - declared.x.value, p.x.value - real.x.value);
      EXPECT_EQ(sent.y.value - declared.y.value, p.y.value - real.y.value);
    }
  }
}
