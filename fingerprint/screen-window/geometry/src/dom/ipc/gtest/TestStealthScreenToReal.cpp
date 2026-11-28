/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared-to-real map of the chrome popups that content anchors on the
// screen (dom/ipc/StealthScreenToReal.h): a content process computes screen
// coordinates on the declared window origin, and the parent opens the popup on
// the real screen at p_real = p_declared - d, d = declared origin - real origin
// of the tab in device px.

#include "StealthScreenToReal.h"

#include "gtest/gtest.h"

using namespace mozilla;

TEST(StealthScreenToReal, APointInDevicePixelsLosesTheDelta)
{
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredDevPx(1000.0, 0), 1000.0);
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredDevPx(1000.0, 42), 958.0);
  // The declared origin can sit above or left of the real one.
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredDevPx(10.0, -7), 17.0);
}

TEST(StealthScreenToReal, ACssCoordinateLosesTheDeltaInTheUnitsOfTheChromePage)
{
  // 1.25 device px per CSS px: a delta of 10 device px is 8 CSS px.
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 10, 1.25), 92.0);
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 10, 2.0), 95.0);
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 0, 1.75), 100.0);
  // A fractional delta in CSS px stays fractional: the popup manager truncates.
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 3, 1.5), 98.0);
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 5, 1.25), 96.0);
}

TEST(StealthScreenToReal, ANonPositiveScaleLeavesTheCoordinateAlone)
{
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 10, 0.0), 100.0);
  EXPECT_DOUBLE_EQ(StealthRealFromDeclaredCssPx(100.0, 10, -1.0), 100.0);
}

TEST(StealthScreenToReal, TheRectOfADragImageMovesAndKeepsItsSize)
{
  const LayoutDeviceIntRect declared(300, 200, 64, 48);
  const LayoutDeviceIntRect real = StealthRealFromDeclaredDevRect(
      declared, LayoutDeviceIntPoint(12, 80));
  EXPECT_EQ(real.x, 288);
  EXPECT_EQ(real.y, 120);
  EXPECT_EQ(real.width, 64);
  EXPECT_EQ(real.height, 48);

  const LayoutDeviceIntRect same =
      StealthRealFromDeclaredDevRect(declared, LayoutDeviceIntPoint(0, 0));
  EXPECT_TRUE(same.IsEqualEdges(declared));
}
