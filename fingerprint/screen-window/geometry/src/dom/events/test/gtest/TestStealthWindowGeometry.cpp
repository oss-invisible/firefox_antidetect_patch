/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared content origin (gfx::StealthDeclaredOriginShift), which
// mozInnerScreenX/Y and every mouse event's screenX/Y follow. A window in
// fullscreen is the declared screen: its content starts at (0, 0), as on
// retail. Before 2026-11-01 the main window kept the maximized window's 85
// device pixels of UI after requestFullscreen().

#include <cmath>
#include <vector>

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/ScopeExit.h"
#include "mozilla/Services.h"
#include "mozilla/dom/BrowsingContext.h"
#include "nsCOMPtr.h"
#include "nsIObserverService.h"
#include "nsString.h"

using namespace mozilla;

namespace {

constexpr int32_t kAuPerDevPx = 60;
const char* const kPrefs[] = {
    "zoom.stealth.fpp.hw_seed",
    "zoom.stealth.screen.frame_border",
    "zoom.stealth.screen.maximized_ui",
    "zoom.stealth.screen.popup_ui",
    "zoom.stealth.screen.popup_position",
    "zoom.stealth.screen.ui_normal",
    "zoom.stealth.screen.ui_compact",
    "zoom.stealth.screen.compact_below_css",
    "zoom.stealth.screen.restored_position",
    "zoom.stealth.screen.min_inner_width_css",
    "zoom.stealth.screen.min_inner_height_css",
};

// A SYNTHETIC window frame, not a retail measurement: the values at 100% the
// first-resize measurements were taken with, plus popup values. In the order of
// StealthWindowFrame: border, maximizedUi, popupUi, popupPosition, uiNormal,
// uiCompact, compactBelowCss, restoredPosition, minInnerWidthCss,
// minInnerHeightCss.
const gfx::StealthWindowFrame kSyntheticFrame = {8,  85,  62,  26, 85,
                                                 73, 720, 4,   500, 120};

// The synthetic work area, in device pixels, at 100%.
constexpr int32_t kSyntheticAvailWidth = 1920;
constexpr int32_t kSyntheticAvailHeight = 1032;

// The declared frame, the engine on.
void DeclareFrame(const gfx::StealthWindowFrame& aFrame) {
  Preferences::SetInt(kPrefs[0], 7);
  Preferences::SetInt(kPrefs[1], aFrame.mBorder);
  Preferences::SetInt(kPrefs[2], aFrame.mMaximizedUi);
  Preferences::SetInt(kPrefs[3], aFrame.mPopupUi);
  Preferences::SetInt(kPrefs[4], aFrame.mPopupPosition);
  Preferences::SetInt(kPrefs[5], aFrame.mUiNormal);
  Preferences::SetInt(kPrefs[6], aFrame.mUiCompact);
  Preferences::SetInt(kPrefs[7], aFrame.mCompactBelowCss);
  Preferences::SetInt(kPrefs[8], aFrame.mRestoredPosition);
  Preferences::SetInt(kPrefs[9], aFrame.mMinInnerWidthCss);
  Preferences::SetInt(kPrefs[10], aFrame.mMinInnerHeightCss);
}

void Declare() { DeclareFrame(kSyntheticFrame); }

nsPoint Declared(const Maybe<LayoutDeviceIntPoint>& aPopup, bool aFullscreen) {
  // A real origin of zero: the shift is then the declared origin itself.
  const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
      nsPoint(0, 0), aPopup, Nothing(), aFullscreen, kAuPerDevPx);
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
      nsPoint(10 * kAuPerDevPx, 20 * kAuPerDevPx), Nothing(), Nothing(), true,
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

// The MAIN window after Page.setViewportSize (gfx::StealthWindowState). Retail
// restores the window on that resize: it sits at the restored position, its
// outer size is what Juggler's resizeBy makes of it, and the UI density is
// decided again from the new chrome height. Until the state existed the page
// read the MAXIMIZED window: outer 1936x1048 around inner 390x844, screenX -8,
// content origin (0, 85).

namespace {

// One window: the work area in device pixels at a scale, and the frame the
// core declares for it.
struct Scenario {
  float mScale;
  int32_t mAvailWidth;
  int32_t mAvailHeight;
  gfx::StealthWindowFrame mFrame;
};

// The maximized window as StealthDeclaredMaximizedWindow builds it: a border
// off the screen on every side around the work area.
LayoutDeviceIntRect MaximizedOf(const Scenario& aScenario) {
  const int32_t b = aScenario.mFrame.mBorder;
  return LayoutDeviceIntRect(-b, -b, aScenario.mAvailWidth + 2 * b,
                             aScenario.mAvailHeight + 2 * b);
}

// The content area of that maximized window in CSS pixels, rounded as Gecko
// rounds: the inner size a page reads unresized.
CSSIntSize MaximizedContentOf(const Scenario& aScenario) {
  const gfx::StealthWindowFrame& f = aScenario.mFrame;
  const LayoutDeviceIntSize device(aScenario.mAvailWidth,
                                   aScenario.mAvailHeight - f.mMaximizedUi);
  return gfx::RoundedToInt(device / CSSToLayoutDeviceScale(aScenario.mScale));
}

// One Juggler call (the "stealth-viewport-resize" notification): the pure core
// of the observer, with the declared scale.
gfx::StealthWindowState JugglerCall(const Scenario& aScenario,
                                    const gfx::StealthWindowState& aState,
                                    const CSSIntSize& aRequested) {
  return gfx::StealthWindowStateAfterViewportResize(
      aState, aRequested, MaximizedOf(aScenario), aScenario.mFrame,
      aScenario.mScale);
}

// The first Page.setViewportSize: from the maximized window.
gfx::StealthWindowState FirstResize(const Scenario& aScenario,
                                    const CSSIntSize& aTo) {
  return JugglerCall(aScenario, gfx::StealthWindowState(), aTo);
}

CSSIntSize OuterCss(const gfx::StealthWindowState& aState,
                    const Scenario& aScenario) {
  const Maybe<LayoutDeviceIntRect> rect =
      gfx::StealthRestoredWindowRect(aState, aScenario.mFrame);
  EXPECT_TRUE(rect);
  return rect ? gfx::RoundedToInt(rect->Size() /
                                  CSSToLayoutDeviceScale(aScenario.mScale))
              : CSSIntSize();
}

const Scenario kSynthetic100 = {1.0f, kSyntheticAvailWidth,
                                kSyntheticAvailHeight, kSyntheticFrame};

}  // namespace

TEST(StealthWindowGeometry, ARequestWithASideOfZeroKeepsTheState)
{
  // No size was asked for: the window is still the maximized one.
  for (const CSSIntSize& inner :
       {CSSIntSize(0, 0), CSSIntSize(0, 844), CSSIntSize(390, 0)}) {
    const gfx::StealthWindowState state = JugglerCall(
        kSynthetic100, gfx::StealthWindowState(), inner);
    EXPECT_FALSE(state.mRestored) << inner.width << "x" << inner.height;
  }
  // A restored window stays what it was too.
  const gfx::StealthWindowState restored =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(restored.mRestored);
  EXPECT_EQ(JugglerCall(kSynthetic100, restored,
                   CSSIntSize(0, 0)),
            restored);
}

TEST(StealthWindowGeometry, TheMaximizedContentIsTheMaximizedWindow)
{
  // Synthetic frame, at 100% and at 125% (where the content size rounds).
  for (float scale : {1.0f, 1.25f}) {
    const Scenario s = {scale, kSyntheticAvailWidth, kSyntheticAvailHeight,
                        kSyntheticFrame};
    const CSSIntSize content = MaximizedContentOf(s);
    EXPECT_FALSE(
        JugglerCall(s, gfx::StealthWindowState(), content)
            .mRestored)
        << "scale " << scale;
    // One CSS pixel less on either side is no longer the maximized content.
    EXPECT_TRUE(JugglerCall(s, gfx::StealthWindowState(),
                       CSSIntSize(content.width - 1, content.height))
                    .mRestored)
        << "scale " << scale;
    EXPECT_TRUE(JugglerCall(s, gfx::StealthWindowState(),
                       CSSIntSize(content.width, content.height - 1))
                    .mRestored)
        << "scale " << scale;
  }
}

// RED on the old behaviour: a 390x844 content area inside the maximized
// declaration answered the maximized outer size (1936x1048 at 100%).
TEST(StealthWindowGeometry, ASmallContentAreaIsNotTheMaximizedWindow)
{
  const gfx::StealthWindowState state =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(state.mRestored);
  EXPECT_NE(state.mOuter, MaximizedOf(kSynthetic100).Size());
}

// The way back to the maximized content size: retail does not maximize a
// restored window again. It stays restored, and the outer size goes through
// the same resize as any other (synthetic frame at 100%: a 1920x947 content
// area is a 1936x1040 window, not the 1936x1048 maximized one).
TEST(StealthWindowGeometry, ARestoredWindowIsNeverMaximizedAgain)
{
  const gfx::StealthWindowState restored =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(restored.mRestored);
  const gfx::StealthWindowState back =
      JugglerCall(kSynthetic100, restored,
             MaximizedContentOf(kSynthetic100));
  EXPECT_TRUE(back.mRestored);
  EXPECT_EQ(back.mOuter, LayoutDeviceIntSize(1936, 1040));
  EXPECT_NE(back.mOuter, MaximizedOf(kSynthetic100).Size());
}

TEST(StealthWindowGeometry, TheFirstResizeNeverGoesUnderTheMinimumWidth)
{
  // 390 CSS pixels wide is under the 500 the chrome needs: the window is 500
  // plus a border on each side, and a wider content area is that plus the
  // borders.
  const gfx::StealthWindowState narrow =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  EXPECT_EQ(narrow.mOuter.width, 500 + 2 * 8);
  const gfx::StealthWindowState wide =
      FirstResize(kSynthetic100, CSSIntSize(800, 600));
  EXPECT_EQ(wide.mOuter.width, 800 + 2 * 8);
  // And the same at 1.5, rounded through device pixels.
  const Scenario s = {1.5f, 1600, 1128, {11, 127, 106, 4, 127, 109, 720, 4, 500, 120}};
  EXPECT_EQ(FirstResize(s, CSSIntSize(390, 630)).mOuter.width, 750 + 2 * 11);
}

// The first resize, from the maximized window: the outer height is the new
// height, the bar of the MAXIMIZED window and the borders, in CSS rounding.
TEST(StealthWindowGeometry, TheFirstResizeUsesTheMaximizedBar)
{
  const gfx::StealthWindowState state =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(state.mRestored);
  EXPECT_EQ(state.mOuter, LayoutDeviceIntSize(516, 844 + 85 + 2 * 8));
  EXPECT_FALSE(state.mCompact);
}

// The second resize, from a restored window: one border fewer, because the top
// border the maximized window kept off the screen is already inside the window.
// The bar is the one of the density the window has before the resize.
TEST(StealthWindowGeometry, TheSecondResizeCountsOneBorderLess)
{
  const CSSIntSize first(390, 844);
  const gfx::StealthWindowState one = FirstResize(kSynthetic100, first);
  ASSERT_TRUE(one.mRestored);

  // The same height again.
  const gfx::StealthWindowState same = JugglerCall(
      kSynthetic100, one, first);
  ASSERT_TRUE(same.mRestored);
  EXPECT_EQ(same.mOuter.height, 844 + 85 + 8);

  // A smaller one: the outer height follows, the width stays at the minimum.
  const gfx::StealthWindowState two =
      JugglerCall(kSynthetic100, one, CSSIntSize(390, 700));
  ASSERT_TRUE(two.mRestored);
  EXPECT_EQ(two.mOuter, LayoutDeviceIntSize(516, 700 + 85 + 8));
}

// The density is decided again after the resize: the outer size comes from the
// bar BEFORE, the content top from the bar AFTER.
TEST(StealthWindowGeometry, TheDensityFlipsAfterTheResize)
{
  // Synthetic frame at 100%: 600 CSS pixels of content is a chrome under 720.
  const gfx::StealthWindowState state =
      FirstResize(kSynthetic100, CSSIntSize(390, 600));
  ASSERT_TRUE(state.mRestored);
  // The outer height came from the maximized (normal) bar, 85.
  EXPECT_EQ(state.mOuter.height, 600 + 85 + 2 * 8);
  EXPECT_TRUE(state.mCompact);
  // The content top is the compact bar below the window top.
  const Maybe<LayoutDeviceIntPoint> origin =
      gfx::StealthRestoredContentOrigin(state, kSyntheticFrame);
  ASSERT_TRUE(origin);
  EXPECT_EQ(origin->y, 4 + 73);

  // The window that stays tall keeps the normal bar.
  const gfx::StealthWindowState tall =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  EXPECT_FALSE(tall.mCompact);
  EXPECT_EQ(gfx::StealthRestoredContentOrigin(tall, kSyntheticFrame)->y,
            4 + 85);
}

TEST(StealthWindowGeometry, TheWindowStateRoundTripsThroughItsField)
{
  // The maximized state is the field's default.
  EXPECT_EQ(gfx::StealthPackWindowState(gfx::StealthWindowState()), 0u);
  EXPECT_FALSE(gfx::StealthUnpackWindowState(0).mRestored);
  for (const bool compact : {false, true}) {
    gfx::StealthWindowState state;
    state.mRestored = true;
    state.mCompact = compact;
    state.mOuter = LayoutDeviceIntSize(1626, 1130);
    const gfx::StealthWindowState back =
        gfx::StealthUnpackWindowState(gfx::StealthPackWindowState(state));
    EXPECT_EQ(back, state);
  }
}

// The largest outer size of each side comes back as it went in, and neither
// side spills into the other or into the flags; a larger value is clamped, not
// wrapped.
TEST(StealthWindowGeometry, TheWindowStateFieldKeepsEveryPartAtItsLimit)
{
  constexpr int32_t kMaxSide = (1 << 24) - 1;
  gfx::StealthWindowState state;
  state.mRestored = true;
  state.mCompact = true;
  state.mOuter = LayoutDeviceIntSize(kMaxSide, kMaxSide);
  EXPECT_EQ(gfx::StealthUnpackWindowState(gfx::StealthPackWindowState(state)),
            state);
  state.mCompact = false;
  state.mOuter = LayoutDeviceIntSize(kMaxSide, 3);
  EXPECT_EQ(gfx::StealthUnpackWindowState(gfx::StealthPackWindowState(state)),
            state);
  state.mOuter = LayoutDeviceIntSize(3, kMaxSide);
  EXPECT_EQ(gfx::StealthUnpackWindowState(gfx::StealthPackWindowState(state)),
            state);
  state.mOuter = LayoutDeviceIntSize(1 << 26, 3);
  const gfx::StealthWindowState clamped =
      gfx::StealthUnpackWindowState(gfx::StealthPackWindowState(state));
  EXPECT_EQ(clamped.mOuter, LayoutDeviceIntSize(kMaxSide, 3));
  EXPECT_FALSE(clamped.mCompact);
}

// outerWidth/outerHeight, screenX/screenY and the content origin
// (mozInnerScreenX/Y, event screenX - clientX) all read the ONE state: the
// content sits at the restored position plus the border and the bar, and the
// window around it is the state's outer size.
TEST(StealthWindowGeometry, EveryRestoredValueDerivesFromTheSameState)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  Declare();
  const Maybe<gfx::StealthWindowFrame> declared =
      gfx::StealthDeclaredWindowFrame();
  ASSERT_TRUE(declared);
  const gfx::StealthWindowFrame& frame = *declared;

  for (float scale : {1.0f, 1.25f, 1.5f, 2.0f}) {
    const Scenario s = {scale, kSyntheticAvailWidth, kSyntheticAvailHeight,
                        frame};
    const gfx::StealthWindowState state =
        FirstResize(s, CSSIntSize(390, 844));
    ASSERT_TRUE(state.mRestored) << "scale " << scale;

    // outerWidth/outerHeight and screenX/screenY as the page reads them.
    const Maybe<LayoutDeviceIntRect> rect =
        gfx::StealthRestoredWindowRect(state, frame);
    ASSERT_TRUE(rect) << "scale " << scale;
    EXPECT_EQ(rect->Size(), state.mOuter) << "scale " << scale;
    EXPECT_EQ(rect->TopLeft(), LayoutDeviceIntPoint(frame.mRestoredPosition,
                                                    frame.mRestoredPosition));
    EXPECT_NE(rect->TopLeft(), MaximizedOf(s).TopLeft());

    // The content origin: the window's top-left plus the border and the bar,
    // and the one the origin shift declares (from a real origin of zero).
    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(state, frame);
    ASSERT_TRUE(origin) << "scale " << scale;
    const int32_t bar = state.mCompact ? frame.mUiCompact : frame.mUiNormal;
    EXPECT_EQ(*origin - rect->TopLeft(),
              LayoutDeviceIntPoint(frame.mBorder, bar));
    const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
        nsPoint(0, 0), Nothing(), origin, false, kAuPerDevPx);
    ASSERT_TRUE(shift) << "scale " << scale;
    EXPECT_EQ(*shift, nsPoint(origin->x * kAuPerDevPx, origin->y * kAuPerDevPx))
        << "scale " << scale;
  }
}

// What retail Windows 11 answers after the FIRST Page.setViewportSize, one row
// per measured case: the declaration the core makes for the panel and the
// scale, the size asked for, and the CSS values a page reads.
namespace {

struct RetailFirstResize {
  float mScale;
  // The panel in device pixels; the work area is the panel less the 48 CSS
  // pixel taskbar at this scale.
  int32_t mPanelWidth;
  int32_t mPanelHeight;
  // The frame at this scale: border, normal and compact bar.
  int32_t mBorder;
  int32_t mUiNormal;
  int32_t mUiCompact;
  // Page.setViewportSize(width, height).
  CSSIntSize mInner;
  // What the page reads: outerWidth/outerHeight, screenX/screenY,
  // mozInnerScreenX/Y.
  CSSIntSize mOuter;
  CSSIntPoint mScreen;
  float mContentOriginX;
  float mContentOriginY;
};

const RetailFirstResize kRetailFirstResize[] = {
    {1.0f, 1920, 1080, 8, 85, 73, CSSIntSize(390, 844), CSSIntSize(516, 945),
     CSSIntPoint(4, 4), 12.0f, 89.0f},
    {1.25f, 1920, 1080, 9, 106, 91, CSSIntSize(390, 690), CSSIntSize(514, 789),
     CSSIntPoint(3, 3), 10.4f, 88.0f},
    {1.5f, 1600, 1200, 11, 127, 109, CSSIntSize(390, 630), CSSIntSize(515, 730),
     CSSIntPoint(3, 3), 10.0f, 87.333f},
    {1.5f, 1920, 1080, 11, 127, 109, CSSIntSize(390, 550), CSSIntSize(515, 638),
     CSSIntPoint(3, 3), 10.0f, 75.333f},
    {2.0f, 1600, 1200, 13, 170, 146, CSSIntSize(390, 430), CSSIntSize(513, 516),
     CSSIntPoint(2, 2), 8.5f, 75.0f},
};

// The declared scenario of a measured case: the maximized window's bar is the
// one of the density its work area has (compact under 720 CSS pixels).
Scenario ScenarioOf(const RetailFirstResize& aCase) {
  const int32_t taskbar = int32_t(floorf(48.0f * aCase.mScale + 0.5f));
  const int32_t availHeight = aCase.mPanelHeight - taskbar;
  const bool compact = float(availHeight) / aCase.mScale < 720.0f;
  return {aCase.mScale,
          aCase.mPanelWidth,
          availHeight,
          {aCase.mBorder, compact ? aCase.mUiCompact : aCase.mUiNormal, 72, 4,
           aCase.mUiNormal, aCase.mUiCompact, 720, 4, 500, 120}};
}

}  // namespace

TEST(StealthWindowGeometry, TheFirstResizeAtEveryDomainScale)
{
  for (const RetailFirstResize& r : kRetailFirstResize) {
    const Scenario s = ScenarioOf(r);
    const CSSToLayoutDeviceScale toDevice(r.mScale);
    const gfx::StealthWindowState state = FirstResize(s, r.mInner);
    ASSERT_TRUE(state.mRestored) << "scale " << r.mScale;

    const CSSIntSize outer = OuterCss(state, s);
    EXPECT_EQ(outer, r.mOuter) << "scale " << r.mScale << ", inner "
                               << r.mInner.width << "x" << r.mInner.height;

    const Maybe<LayoutDeviceIntRect> rect =
        gfx::StealthRestoredWindowRect(state, s.mFrame);
    ASSERT_TRUE(rect);
    EXPECT_EQ(gfx::RoundedToInt(rect->TopLeft() / toDevice), r.mScreen)
        << "scale " << r.mScale;

    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(state, s.mFrame);
    ASSERT_TRUE(origin);
    EXPECT_NEAR(float(origin->x) / r.mScale, r.mContentOriginX, 0.01)
        << "scale " << r.mScale;
    EXPECT_NEAR(float(origin->y) / r.mScale, r.mContentOriginY, 0.01)
        << "scale " << r.mScale;
  }
}

// The SECOND Page.setViewportSize, from a restored window, and the return to
// the maximized content size, as retail answers them: one sequence per panel,
// each starting from the first resize of the same row of kRetailFirstResize
// (first call, second call, return).
namespace {

struct RetailSequence {
  size_t mFirst;  // the row of kRetailFirstResize the window starts from
  // The second Page.setViewportSize and what the page reads after it.
  CSSIntSize mSecondInner;
  CSSIntSize mSecondOuter;
  float mSecondContentOriginY;  // mozInnerScreenY
  // The return to the maximized content size and what the page reads after it:
  // the window stays restored.
  CSSIntSize mReturnInner;
  CSSIntSize mReturnOuter;
  float mReturnContentOriginY;
};

const RetailSequence kRetailSequence[] = {
    {0, CSSIntSize(414, 896), CSSIntSize(516, 989), 89.0f,
     CSSIntSize(1920, 947), CSSIntSize(1936, 1040), 89.0f},
    {1, CSSIntSize(414, 640), CSSIntSize(514, 733), 88.0f,
     CSSIntSize(1536, 731), CSSIntSize(1550, 823), 88.0f},
    {2, CSSIntSize(414, 580), CSSIntSize(515, 672), 75.333f,
     CSSIntSize(1067, 667), CSSIntSize(1082, 746), 87.333f},
    {3, CSSIntSize(414, 500), CSSIntSize(515, 580), 75.333f,
     CSSIntSize(1280, 599), CSSIntSize(1295, 678), 75.333f},
    {4, CSSIntSize(414, 380), CSSIntSize(513, 460), 75.0f,
     CSSIntSize(800, 479), CSSIntSize(813, 558), 75.0f},
};

}  // namespace

TEST(StealthWindowGeometry, TheSecondResizeAtEveryDomainScale)
{
  for (const RetailSequence& r : kRetailSequence) {
    const RetailFirstResize& first = kRetailFirstResize[r.mFirst];
    const Scenario s = ScenarioOf(first);
    const gfx::StealthWindowState one = FirstResize(s, first.mInner);
    const gfx::StealthWindowState two =
        JugglerCall(s, one, r.mSecondInner);
    ASSERT_TRUE(two.mRestored) << "scale " << first.mScale;
    EXPECT_EQ(OuterCss(two, s), r.mSecondOuter)
        << "scale " << first.mScale << ", panel " << first.mPanelWidth << "x"
        << first.mPanelHeight;
    // screenX/screenY do not move, the content origin follows the density the
    // window has after the resize.
    const Maybe<LayoutDeviceIntRect> rect =
        gfx::StealthRestoredWindowRect(two, s.mFrame);
    ASSERT_TRUE(rect);
    EXPECT_EQ(gfx::RoundedToInt(rect->TopLeft() /
                                CSSToLayoutDeviceScale(first.mScale)),
              first.mScreen);
    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(two, s.mFrame);
    ASSERT_TRUE(origin);
    EXPECT_NEAR(float(origin->x) / first.mScale, first.mContentOriginX, 0.01)
        << "scale " << first.mScale;
    EXPECT_NEAR(float(origin->y) / first.mScale, r.mSecondContentOriginY, 0.01)
        << "scale " << first.mScale;
  }
}

TEST(StealthWindowGeometry, TheWayBackAtEveryDomainScale)
{
  for (const RetailSequence& r : kRetailSequence) {
    const RetailFirstResize& first = kRetailFirstResize[r.mFirst];
    const Scenario s = ScenarioOf(first);
    // The size asked for is the maximized content.
    ASSERT_EQ(r.mReturnInner, MaximizedContentOf(s)) << "scale " << first.mScale;
    const gfx::StealthWindowState one = FirstResize(s, first.mInner);
    const gfx::StealthWindowState two =
        JugglerCall(s, one, r.mSecondInner);
    const gfx::StealthWindowState back =
        JugglerCall(s, two, r.mReturnInner);
    // Retail does not maximize the window again.
    ASSERT_TRUE(back.mRestored) << "scale " << first.mScale;
    EXPECT_EQ(OuterCss(back, s), r.mReturnOuter)
        << "scale " << first.mScale << ", panel " << first.mPanelWidth << "x"
        << first.mPanelHeight;
    // The density is decided again from the new chrome height: at 1.5 on
    // 1600x1200 the window turned compact on the second call and is normal
    // again here.
    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(back, s.mFrame);
    ASSERT_TRUE(origin);
    EXPECT_NEAR(float(origin->y) / first.mScale, r.mReturnContentOriginY, 0.01)
        << "scale " << first.mScale;
  }
}

// A repeated Page.setViewportSize to the SAME size is a Juggler call like any
// other: resizeBy runs again, with the delta from the restored window's own
// chrome, trunc(844 + 85 - 937) = -8, and answers 937 (one border fewer than
// the first call's 945, as in the measured second-call rule).
// MEASUREMENT PENDING (round 5 of retail-window-geometry, after firefox-70): the repeat of the SECOND call is measured (run 45952171443, see
// TheRepeatOfTheSecondResizeChangesNothingAtEveryDomainScale); the repeat of the FIRST call is being measured, and 937 stays Juggler's arithmetic, deduced from the measured second-call rule, until its run id replaces this comment.
TEST(StealthWindowGeometry,
     ARepeatedResizeToTheSameSizeAnswersJugglersArithmetic)
{
  const Scenario s = ScenarioOf(kRetailFirstResize[0]);  // 100%, b 8, bar 85
  const CSSIntSize size(390, 844);
  const gfx::StealthWindowState one =
      JugglerCall(s, gfx::StealthWindowState(), size);
  ASSERT_TRUE(one.mRestored);
  EXPECT_EQ(OuterCss(one, s), CSSIntSize(516, 945));

  // The same size again is a call: the outer height is 937.
  const gfx::StealthWindowState again = JugglerCall(s, one, size);
  ASSERT_TRUE(again.mRestored);
  EXPECT_EQ(OuterCss(again, s), CSSIntSize(516, 937));
}

// The repeat of the SECOND Page.setViewportSize, as retail answers it: retail
// capture round 5 (GitHub run oss-invisible/core 45952171443, step
// juggler2_repeat) repeats the second call at the same size and nothing
// changes at any scale. From the maximized window: (390, h1), then (414, h2),
// then (414, h2) again; the state after the repeat is bit for bit the state
// after the second call, and the page reads the second call's outer size.
TEST(StealthWindowGeometry,
     TheRepeatOfTheSecondResizeChangesNothingAtEveryDomainScale)
{
  // The measured rows: 100%, 125% and 150% on 1920x1080, 200% on 1600x1200.
  for (const size_t row : {size_t(0), size_t(1), size_t(3), size_t(4)}) {
    const RetailSequence& r = kRetailSequence[row];
    const RetailFirstResize& first = kRetailFirstResize[r.mFirst];
    const Scenario s = ScenarioOf(first);
    const gfx::StealthWindowState one =
        JugglerCall(s, gfx::StealthWindowState(), first.mInner);
    const gfx::StealthWindowState two = JugglerCall(s, one, r.mSecondInner);
    ASSERT_TRUE(two.mRestored) << "scale " << first.mScale;
    ASSERT_EQ(OuterCss(two, s), r.mSecondOuter) << "scale " << first.mScale;

    const gfx::StealthWindowState repeat = JugglerCall(s, two, r.mSecondInner);
    ASSERT_TRUE(repeat.mRestored) << "scale " << first.mScale;
    EXPECT_EQ(repeat, two) << "scale " << first.mScale << ", panel "
                           << first.mPanelWidth << "x" << first.mPanelHeight;
    EXPECT_EQ(OuterCss(repeat, s), r.mSecondOuter)
        << "scale " << first.mScale << ", panel " << first.mPanelWidth << "x"
        << first.mPanelHeight;
  }
}

// A first call for the maximized content size does nothing (resizeBy with a
// zero delta): the window stays the maximized one.
TEST(StealthWindowGeometry,
     AJugglerCallForTheMaximizedContentKeepsTheMaximizedWindow)
{
  for (const RetailFirstResize& r : kRetailFirstResize) {
    const Scenario s = ScenarioOf(r);
    EXPECT_EQ(JugglerCall(s, gfx::StealthWindowState(), MaximizedContentOf(s)),
              gfx::StealthWindowState())
        << "scale " << r.mScale;
  }
}

// The window state is a field of a real top-level BrowsingContext (gtests run in
// the parent process, which is where the observer and Juggler are): the tests
// below drive the field the way the engine does, and read it back bit for bit.
namespace {

already_AddRefed<dom::BrowsingContext> NewTopContext() {
  RefPtr<dom::BrowsingContext> bc = dom::BrowsingContext::CreateIndependent(
      dom::BrowsingContext::Type::Content, true);
  return bc.forget();
}

// The prefs of a scenario's declaration, the engine on, as the gate validates
// them: the frame, the work area in device pixels, the screen in CSS pixels and
// the scale (the screen times the scale is the work area's width).
const char* const kWindowPrefs[] = {
    "zoom.stealth.screen.width",
    "zoom.stealth.screen.avail_device_width",
    "zoom.stealth.screen.avail_device_height",
};
const char kScalePref[] = "layout.css.devPixelsPerPx";

void DeclareScenario(const Scenario& aScenario) {
  DeclareFrame(aScenario.mFrame);
  Preferences::SetInt(kWindowPrefs[0], int32_t(floorf(
                          float(aScenario.mAvailWidth) / aScenario.mScale + 0.5f)));
  Preferences::SetInt(kWindowPrefs[1], aScenario.mAvailWidth);
  Preferences::SetInt(kWindowPrefs[2], aScenario.mAvailHeight);
  Preferences::SetFloat(kScalePref, aScenario.mScale);
}

void ClearScenario() {
  for (const char* pref : kPrefs) {
    Preferences::ClearUser(pref);
  }
  for (const char* pref : kWindowPrefs) {
    Preferences::ClearUser(pref);
  }
  Preferences::ClearUser(kScalePref);
}

// What Juggler's Page.setViewportSize sends the engine, as the engine receives
// it: the "stealth-viewport-resize" notification, the page's BrowsingContext as
// the subject and the requested CSS size as the data.
void NotifyViewportResize(dom::BrowsingContext* aBrowsingContext,
                          const char16_t* aData) {
  nsCOMPtr<nsIObserverService> observerService = services::GetObserverService();
  ASSERT_TRUE(observerService);
  nsISupports* subject = static_cast<nsILoadContext*>(aBrowsingContext);
  observerService->NotifyObservers(subject, "stealth-viewport-resize", aData);
}

// What nsPresContext::UpdateInnerSizeSpoofedForRFP does on every change of the
// top-level visible area: it sets the synced inner size, and nothing else.
void InnerSizeChanged(dom::BrowsingContext* aBrowsingContext,
                      const CSSIntSize& aInner) {
  ASSERT_EQ(aBrowsingContext->SetInnerSizeSpoofedForRFP(aInner), NS_OK);
}

}  // namespace

// The observer the engine registers moves the field of the TOP context, and
// only for a Juggler call: the state after the first call is the arithmetic's.
TEST(StealthWindowGeometry, TheViewportResizeNotificationMovesTheTopContextField)
{
  auto restore = MakeScopeExit([] { ClearScenario(); });
  const Scenario& s = kSynthetic100;
  DeclareScenario(s);
  // The engine on is what registers the observer, in this (the parent) process.
  ASSERT_TRUE(gfx::StealthEngineActive());
  RefPtr<dom::BrowsingContext> bc = NewTopContext();
  ASSERT_TRUE(bc);
  ASSERT_EQ(bc->GetStealthWindowState(), 0u);

  NotifyViewportResize(bc, u"390,844");
  const gfx::StealthWindowState one = FirstResize(s, CSSIntSize(390, 844));
  EXPECT_EQ(bc->GetStealthWindowState(), gfx::StealthPackWindowState(one));
  EXPECT_EQ(OuterCss(gfx::StealthUnpackWindowState(bc->GetStealthWindowState()), s),
            CSSIntSize(516, 945));

  // The same size again is a call (937), and malformed data is not one.
  NotifyViewportResize(bc, u"390,844");
  EXPECT_EQ(bc->GetStealthWindowState(),
            gfx::StealthPackWindowState(JugglerCall(s, one, CSSIntSize(390, 844))));
  const uint64_t before = bc->GetStealthWindowState();
  NotifyViewportResize(bc, u"390x844");
  NotifyViewportResize(bc, u"0,844");
  EXPECT_EQ(bc->GetStealthWindowState(), before);

  // A popup is declared from its own frame: its field does not move.
  RefPtr<dom::BrowsingContext> popup = NewTopContext();
  ASSERT_TRUE(popup);
  ASSERT_EQ(popup->SetIsPopupRequested(true), NS_OK);
  NotifyViewportResize(popup, u"390,844");
  EXPECT_EQ(popup->GetStealthWindowState(), 0u);
}

// RED on the first version of the window state, which advanced it on every
// change of the top-level inner size (nsPresContext::
// UpdateInnerSizeSpoofedForRFP) and not only on Juggler's calls. The first
// layout reports the host's own inner size (a window the host sized, 1920x900
// or 1920x1000 here, not the declared maximized content), and the declared
// content 1920x947 follows. The old updater, from the maximized window 1936x1048
// (work area 1920x1032, bar 85, border 8):
//   1920x900:  dh = trunc(900 + 85 - 1032) = -47, outer 1048 - 47 = 1001
//   1920x947:  from 1001 (chrome 993): dh = trunc(947 + 85 - 993) = 39, outer 1040
//   1920x1000: dh = trunc(1000 + 85 - 1032) = 53, outer 1101
//   1920x947:  from 1101 (chrome 1093): dh = trunc(947 + 85 - 1093) = -61, outer 1040
// so a page read outerHeight 1040 and screenX 4 before any setViewportSize.
// Retail reads the maximized window: 1936x1048 at (-8, -8). Without a Juggler
// call the field does not move.
TEST(StealthWindowGeometry, TheFirstLayoutLeavesTheFieldAlone)
{
  auto restore = MakeScopeExit([] { ClearScenario(); });
  const Scenario& s = kSynthetic100;
  DeclareScenario(s);
  ASSERT_EQ(MaximizedContentOf(s), CSSIntSize(1920, 947));
  for (const CSSIntSize& host :
       {CSSIntSize(1920, 900), CSSIntSize(1920, 1000)}) {
    RefPtr<dom::BrowsingContext> bc = NewTopContext();
    ASSERT_TRUE(bc);
    // The maximized window: the field's default.
    ASSERT_EQ(bc->GetStealthWindowState(), 0u);
    InnerSizeChanged(bc, host);
    EXPECT_EQ(bc->GetStealthWindowState(), 0u)
        << host.width << "x" << host.height;
    InnerSizeChanged(bc, MaximizedContentOf(s));
    EXPECT_EQ(bc->GetStealthWindowState(), 0u)
        << host.width << "x" << host.height << " then the declared content";
    // The readers answer the maximized window.
    const gfx::StealthWindowState state =
        gfx::StealthUnpackWindowState(bc->GetStealthWindowState());
    EXPECT_FALSE(gfx::StealthRestoredWindowRect(state, s.mFrame));
    EXPECT_FALSE(gfx::StealthRestoredContentOrigin(state, s.mFrame));
  }
}

// RED on the first version, which skipped only while the widget's size mode was
// fullscreen. The fullscreen inner size (1280x720 at 1.5 on a 1920x1080 panel:
// work area 1920x1008, bar 109 compact, border 11) that arrived while the size
// mode was not (yet, or no longer) fullscreen counted as a resize. The old
// updater, from the compact window of 678 CSS pixels (1017 device, chrome
// 1006 / 1.5 = 670.667, bar 109 / 1.5 = 72.667):
//   1280x720:  dh = trunc(720 + 72.667 - 670.667) = 121 in float (122 in exact
//              arithmetic), outer 799 CSS (normal density, the window grew)
//   1280x599:  from 799 (1199 device, chrome 1188 / 1.5 = 792, normal bar
//              127 / 1.5 = 84.667): dh = trunc(599 + 84.667 - 792) = -108,
//              outer 799 - 108 = 691
// where the window should be what it was, 678. The state is declared and only
// Juggler moves it: a size-mode change is not a field of the context, so the
// order of "size mode" and "resize" is the order of the two inner sets as the
// candidate saw them (a size-mode change in between changes nothing). The
// field, set by the Juggler calls that made the window, is bit for bit what it
// was after both inner sets, in both orders.
TEST(StealthWindowGeometry, FullscreenLeavesTheFieldAlone)
{
  auto restore = MakeScopeExit([] { ClearScenario(); });
  const RetailFirstResize& first = kRetailFirstResize[3];  // 1.5, 1920x1080
  const RetailSequence& seq = kRetailSequence[3];
  const Scenario s = ScenarioOf(first);
  DeclareScenario(s);

  // The compact window of 678 CSS pixels, from Juggler's calls through the
  // observer, and the maximized window.
  gfx::StealthWindowState expected;
  for (const CSSIntSize& call :
       {first.mInner, seq.mSecondInner, seq.mReturnInner}) {
    expected = JugglerCall(s, expected, call);
  }
  ASSERT_TRUE(expected.mRestored);
  ASSERT_TRUE(expected.mCompact);
  ASSERT_EQ(OuterCss(expected, s), CSSIntSize(1295, 678));

  const CSSIntSize kFullscreen(1280, 720);
  const CSSIntSize kBack(1280, 599);
  // The two inner sets, in both orders: a size-mode change has no field on the
  // context, so "size mode first" and "resize first" are the same sets, in the
  // order the candidate saw them, with or without a mode change between them.
  const CSSIntSize kOrders[][2] = {{kFullscreen, kBack}, {kBack, kFullscreen}};
  for (const auto& order : kOrders) {
    for (const bool restoredStart : {true, false}) {
      RefPtr<dom::BrowsingContext> bc = NewTopContext();
      ASSERT_TRUE(bc);
      if (restoredStart) {
        // Built through the observer, as Juggler's three calls make it.
        NotifyViewportResize(bc, u"390,550");
        NotifyViewportResize(bc, u"414,500");
        NotifyViewportResize(bc, u"1280,599");
        ASSERT_EQ(bc->GetStealthWindowState(),
                  gfx::StealthPackWindowState(expected));
      }
      const uint64_t start = bc->GetStealthWindowState();
      for (const CSSIntSize& inner : order) {
        InnerSizeChanged(bc, inner);
        EXPECT_EQ(bc->GetStealthWindowState(), start)
            << "restored start " << restoredStart << ", inner " << inner.width
            << "x" << inner.height;
      }
    }
  }

  // What counting the fullscreen inner sizes as resizes made of the window
  // (the old updater's arithmetic, through the same function): 799, then 691.
  const gfx::StealthWindowState entered = JugglerCall(s, expected, kFullscreen);
  EXPECT_EQ(OuterCss(entered, s), CSSIntSize(1295, 799));
  const gfx::StealthWindowState left = JugglerCall(s, entered, kBack);
  EXPECT_EQ(OuterCss(left, s), CSSIntSize(1295, 691));
}

TEST(StealthWindowGeometry, TheViewportResizeDataIsTwoDecimalIntegers)
{
  CSSIntSize size(-1, -1);
  EXPECT_TRUE(gfx::StealthParseViewportResize(u"390,844"_ns, size));
  EXPECT_EQ(size, CSSIntSize(390, 844));
  EXPECT_TRUE(gfx::StealthParseViewportResize(u"1,16383"_ns, size));
  EXPECT_EQ(size, CSSIntSize(1, 16383));
  // Anything else is ignored and leaves the output alone.
  size = CSSIntSize(7, 9);
  const nsLiteralString kBad[] = {
      u""_ns,          u"390"_ns,        u"390,"_ns,     u",844"_ns,
      u"0,844"_ns,     u"390,0"_ns,      u"-5,100"_ns,   u"390x844"_ns,
      u"390, 844"_ns,  u" 390,844"_ns,   u"390,844,1"_ns, u"390.5,844"_ns,
      u"1e3,5"_ns,     u"16384,10"_ns,   u"10,16384"_ns, u"123456,10"_ns,
      u"+5,5"_ns};
  for (const nsLiteralString& bad : kBad) {
    EXPECT_FALSE(gfx::StealthParseViewportResize(bad, size))
        << NS_ConvertUTF16toUTF8(bad).get();
    EXPECT_EQ(size, CSSIntSize(7, 9));
  }
}
