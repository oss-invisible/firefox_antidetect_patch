/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared content origin (gfx::StealthDeclaredOriginShift), which
// mozInnerScreenX/Y and every mouse event's screenX/Y follow. A window in
// fullscreen is the declared screen: its content starts at (0, 0), as on
// retail. Before 2026-11-01 the main window kept the maximized window's 85
// device pixels of UI after requestFullscreen().

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/ScopeExit.h"

using namespace mozilla;

namespace {

constexpr int32_t kAuPerDevPx = 60;
const char* const kPrefs[] = {
    "zoom.stealth.fpp.hw_seed",           "zoom.stealth.screen.frame_border",
    "zoom.stealth.screen.maximized_ui",   "zoom.stealth.screen.popup_ui",
    "zoom.stealth.screen.popup_position",
};

// A declared window frame like retail's at 100%, the engine on.
void Declare() {
  Preferences::SetInt(kPrefs[0], 7);
  Preferences::SetInt(kPrefs[1], 8);
  Preferences::SetInt(kPrefs[2], 85);
  Preferences::SetInt(kPrefs[3], 62);
  Preferences::SetInt(kPrefs[4], 26);
}

nsPoint Declared(const Maybe<LayoutDeviceIntPoint>& aPopup, bool aFullscreen) {
  // A real origin of zero: the shift is then the declared origin itself.
  const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
      nsPoint(0, 0), aPopup, aFullscreen, kAuPerDevPx);
  EXPECT_TRUE(shift);
  return shift ? *shift : nsPoint(-1, -1);
}

}  // namespace

TEST(StealthWindowGeometry, FullscreenContentStartsAtTheScreenOrigin)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  Declare();
  // The main window in fullscreen: no UI above the content.
  EXPECT_EQ(Declared(Nothing(), true), nsPoint(0, 0));
  // A popup in fullscreen too, wherever it was.
  EXPECT_EQ(Declared(Some(LayoutDeviceIntPoint(300, 200)), true),
            nsPoint(0, 0));
}

TEST(StealthWindowGeometry, OutsideFullscreenNothingChanges)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  Declare();
  // The maximized main window: the UI height below the screen top.
  EXPECT_EQ(Declared(Nothing(), false), nsPoint(0, 85 * kAuPerDevPx));
  // A popup: a border in, the popup UI down from where it really is.
  EXPECT_EQ(Declared(Some(LayoutDeviceIntPoint(300, 200)), false),
            nsPoint((300 + 8) * kAuPerDevPx, (200 + 62) * kAuPerDevPx));
  // The shift is relative to the real origin, so frames keep their offset.
  const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
      nsPoint(10 * kAuPerDevPx, 20 * kAuPerDevPx), Nothing(), true,
      kAuPerDevPx);
  ASSERT_TRUE(shift);
  EXPECT_EQ(*shift, nsPoint(-10 * kAuPerDevPx, -20 * kAuPerDevPx));
}

// An out-of-process iframe that starts before the parent sent its dimensions
// has a real outer size of 0x0, and inner 0x0 with it. Retail answers 0x0 for
// outerWidth/outerHeight there; the declared window (1936x1048) only stands in
// for a real window that has a size. Before this the declaration was put over
// the 0x0, and a page read outer 1936x1048 around inner 0x0.
TEST(StealthWindowGeometry, ARealZeroOuterSizeStaysZero)
{
  EXPECT_FALSE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(0, 0)));
}

TEST(StealthWindowGeometry, AnyOtherRealOuterSizeIsStillDeclared)
{
  // The states outside the zero one are unchanged: the declaration replaces
  // the real size, whatever it is (a headless widget, a popup, a main window).
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(1280, 1024)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(500, 400)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(1, 1)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(0, 600)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(800, 0)));
}

namespace {

using Matrix4 = LayoutDeviceToLayoutDeviceMatrix4x4;

// The matrices the parent process holds for a tab and for an out-of-process
// frame in it. The tab's translation is the real chrome offset T of the host;
// the frame's matrix (child to top-level widget) holds the frame's place F in
// the top document on top of it.
Matrix4 TabMatrix(const LayoutDevicePoint& aT) {
  return Matrix4::Translation(aT);
}

Matrix4 FrameMatrix(const LayoutDevicePoint& aF, const LayoutDevicePoint& aT) {
  return Matrix4::Translation(LayoutDevicePoint(aF.x + aT.x, aF.y + aT.y));
}

LayoutDeviceIntPoint RoundedBy(const Matrix4& aMatrix,
                               const LayoutDevicePoint& aP) {
  return LayoutDeviceIntPoint::Round(aMatrix.TransformPoint(aP));
}

// The host chrome offsets the readings must not depend on: a whole number of
// device pixels, and a fractional one.
const LayoutDevicePoint kHostChromeOffsets[] = {
    LayoutDevicePoint(0.0f, 77.0f), LayoutDevicePoint(0.4f, 93.75f)};

// Round 5 of the window geometry captures: a cross-site iframe at CSS (10, 200)
// in the top document, in device pixels. mDeclaredTop is the declared top
// content origin D at that scale and state; mFrame is the frame's place F;
// mExpected is what retail reads, D + R(F).
struct FrameCase {
  double mScale;
  const char* mState;
  LayoutDeviceIntPoint mDeclaredTop;
  LayoutDevicePoint mFrame;
  LayoutDeviceIntPoint mExpected;
};

const FrameCase kFrameCases[] = {
    {1.0, "maximized", LayoutDeviceIntPoint(0, 85), LayoutDevicePoint(10, 200),
     LayoutDeviceIntPoint(10, 285)},
    {1.25, "maximized", LayoutDeviceIntPoint(0, 106),
     LayoutDevicePoint(12.5f, 250), LayoutDeviceIntPoint(13, 356)},
    {1.25, "windowed", LayoutDeviceIntPoint(13, 110),
     LayoutDevicePoint(12.5f, 250), LayoutDeviceIntPoint(26, 360)},
    {1.5, "maximized", LayoutDeviceIntPoint(0, 109), LayoutDevicePoint(15, 300),
     LayoutDeviceIntPoint(15, 409)},
    {2.0, "windowed", LayoutDeviceIntPoint(17, 150), LayoutDevicePoint(20, 400),
     LayoutDeviceIntPoint(37, 550)},
};

}  // namespace

// The frame reads the declared top origin D plus Firefox's own rounded offset
// of the frame in the top, R(F), whatever the real chrome offset T of the host
// is: T is in both the tab's and the frame's matrix and cancels.
TEST(StealthWindowGeometry, AnOutOfProcessFrameReadsTheDeclaredOriginPlusItsOffset)
{
  for (const FrameCase& c : kFrameCases) {
    for (const LayoutDevicePoint& t : kHostChromeOffsets) {
      SCOPED_TRACE(c.mScale);
      SCOPED_TRACE(c.mState);
      SCOPED_TRACE(t.y);
      const Maybe<Matrix4> rel = gfx::StealthFrameToTopContent(
          FrameMatrix(c.mFrame, t), TabMatrix(t));
      ASSERT_TRUE(rel);
      const LayoutDeviceIntPoint reading =
          c.mDeclaredTop + gfx::StealthFrameOffsetInTop(*rel);
      EXPECT_EQ(reading, c.mExpected);
    }
  }
}

// The negative controls: the published formula reads D alone, and the
// rejected literal fix, which anchors the shift on the frame's widget offset in
// the top-level widget, reads D + R(F + T), which carries the host's chrome
// offset into the page. Both give a wrong number with the fractional host
// offset. Hand-computed at 100% maximized (D (0, 85), F (10, 200),
// T (0.4, 93.75)): expected (10, 285); published (0, 85); literal fix
// (0 + R(10.4), 85 + R(293.75)) = (10, 379).
TEST(StealthWindowGeometry, ThePublishedAndTheLiteralFixReadWrongNumbers)
{
  const LayoutDevicePoint hostT(0.4f, 93.75f);
  for (const FrameCase& c : kFrameCases) {
    SCOPED_TRACE(c.mScale);
    SCOPED_TRACE(c.mState);
    const Matrix4 frame = FrameMatrix(c.mFrame, hostT);
    const LayoutDeviceIntPoint published = c.mDeclaredTop;
    const LayoutDeviceIntPoint literal =
        c.mDeclaredTop + RoundedBy(frame, LayoutDevicePoint());
    EXPECT_NE(published, c.mExpected);
    EXPECT_NE(literal, c.mExpected);
  }
  const FrameCase& first = kFrameCases[0];
  EXPECT_EQ(first.mDeclaredTop + RoundedBy(FrameMatrix(first.mFrame, hostT),
                                           LayoutDevicePoint()),
            LayoutDeviceIntPoint(10, 379));
}

// The event path. Mozilla computes R(M_iframe * p) and the shift removes
// R(M_iframe * 0), which is exact for a translation only when the host's offset
// is a whole number. StealthFrameEventTransform makes the event follow M_rel:
// the page reads D + R(M_rel * p) for every p, with the transform of the frame
// kept. Reading above D: R(result * p) - R(M_iframe * 0) + R(M_rel * 0).
// Scale 1.5, F (12.5, 250), T (0.4, 93.75): M_iframe * 0 = (12.9, 343.75),
// rounded (13, 344); M_rel * 0 = (12.5, 250), rounded (13, 250); K = (0, 94).
// At p = (1, 1): M_rel * p = (14, 251.5), read (14, 252); the event path
// R((14, 345.5)) = (14, 346), 346 - 344 + 250 = 252: equal. Mozilla's own path
// R((14.4, 345.25)) = (14, 345), 345 - 344 + 250 = 251: one device pixel off.
TEST(StealthWindowGeometry, TheEventTransformReadsTheFramesOwnPlaceForAnyTransform)
{
  const LayoutDevicePoint f(12.5f, 250.0f);
  const LayoutDevicePoint t(0.4f, 93.75f);
  const LayoutDevicePoint zero;

  // Scale 1.5 and a rotation of 10 degrees about the origin, then the frame's
  // place and the host's offset.
  Matrix4 scaled = Matrix4::Scaling(1.5f, 1.5f, 1.0f);
  scaled.PostTranslate(f.x + t.x, f.y + t.y, 0.0f);
  const float c = 0.98480775f;  // cos 10 degrees
  const float s = 0.17364818f;  // sin 10 degrees
  Matrix4 rotated(c, s, 0.0f, 0.0f, -s, c, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f,
                  0.0f, 0.0f, 0.0f, 1.0f);
  rotated.PostTranslate(f.x + t.x, f.y + t.y, 0.0f);

  const LayoutDeviceIntPoint points[] = {
      LayoutDeviceIntPoint(1, 1),  LayoutDeviceIntPoint(0, 1),
      LayoutDeviceIntPoint(3, 1),  LayoutDeviceIntPoint(5, 3),
      LayoutDeviceIntPoint(10, 10), LayoutDeviceIntPoint(20, 7),
      LayoutDeviceIntPoint(100, 50), LayoutDeviceIntPoint(37, 91)};
  bool mozillaDiffersOnce = false;
  for (const Matrix4& iframe : {scaled, rotated}) {
    const Maybe<Matrix4> rel =
        gfx::StealthFrameToTopContent(iframe, TabMatrix(t));
    ASSERT_TRUE(rel);
    const Matrix4 event = gfx::StealthFrameEventTransform(*rel, iframe);
    const LayoutDeviceIntPoint mozillaOrigin = RoundedBy(iframe, zero);
    const LayoutDeviceIntPoint relOrigin = RoundedBy(*rel, zero);
    for (const LayoutDeviceIntPoint& p : points) {
      SCOPED_TRACE(p.x.value);
      SCOPED_TRACE(p.y.value);
      const LayoutDevicePoint pf(float(p.x.value), float(p.y.value));
      const LayoutDeviceIntPoint wanted = RoundedBy(*rel, pf);
      EXPECT_EQ(RoundedBy(event, pf) - mozillaOrigin + relOrigin, wanted);
      if (RoundedBy(iframe, pf) - mozillaOrigin + relOrigin != wanted) {
        mozillaDiffersOnce = true;
      }
    }
  }
  // Mozilla's untouched path is not retail's with the fractional host offset:
  // that is why Event.cpp asks StealthTopLevelTransform.
  EXPECT_TRUE(mozillaDiffersOnce);

  // The scale case, by hand: p = (1, 1).
  const Maybe<Matrix4> rel = gfx::StealthFrameToTopContent(scaled, TabMatrix(t));
  ASSERT_TRUE(rel);
  const LayoutDevicePoint one(1.0f, 1.0f);
  EXPECT_EQ(RoundedBy(*rel, one), LayoutDeviceIntPoint(14, 252));
  EXPECT_EQ(RoundedBy(gfx::StealthFrameEventTransform(*rel, scaled), one),
            LayoutDeviceIntPoint(14, 346));
  EXPECT_EQ(RoundedBy(scaled, one), LayoutDeviceIntPoint(14, 345));
}

// A tab matrix that is not a translation has no place to give: the parent sets
// Nothing and the frame reads the declared origin alone.
TEST(StealthWindowGeometry, ATabMatrixThatIsNotATranslationGivesNoPlace)
{
  const LayoutDevicePoint f(10.0f, 200.0f);
  const LayoutDevicePoint t(0.0f, 77.0f);
  EXPECT_FALSE(gfx::StealthFrameToTopContent(
      FrameMatrix(f, t), Matrix4::Scaling(1.5f, 1.5f, 1.0f)));
  Matrix4 skewed = TabMatrix(t);
  skewed._21 = 0.25f;
  EXPECT_FALSE(gfx::StealthFrameToTopContent(FrameMatrix(f, t), skewed));
  // A 3D tab matrix is no translation either.
  Matrix4 deep = TabMatrix(t);
  deep._43 = 1.0f;
  EXPECT_FALSE(gfx::StealthFrameToTopContent(FrameMatrix(f, t), deep));
  // The translation itself is.
  EXPECT_TRUE(gfx::StealthFrameToTopContent(FrameMatrix(f, t), TabMatrix(t)));
}
