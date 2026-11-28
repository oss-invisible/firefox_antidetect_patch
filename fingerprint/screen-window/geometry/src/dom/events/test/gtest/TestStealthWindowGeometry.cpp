/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared window: its outer rect, client offset and chrome offset, and the
// request that a declared-space moveTo/resizeTo stands for. Pure functions of
// the gate (gfx/thebes/StealthDeclarationGate), fed the DECLARED values of the
// window frame as inputs, with the retail measurements of Firefox 159.0 on
// Windows 11 build 26100 as expected values (RetailCaptures,
// WINDOW_GEOMETRY_POPUP_FRAME.csv and WINDOW_GEOMETRY_FRAME_EARLY.csv, run
// 2026-11-27-window-geometry-r5, r6 and r7 read the same).

#include <cmath>
#include <iterator>

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/ScopeExit.h"

using namespace mozilla;

namespace {

const char* const kPrefs[] = {
    "zoom.stealth.fpp.hw_seed",           "zoom.stealth.screen.frame_border",
    "zoom.stealth.screen.maximized_ui",   "zoom.stealth.screen.popup_ui",
    "zoom.stealth.screen.popup_position",
    "zoom.stealth.screen.popup_client_top",
};

}  // namespace

// The engine off is stock Firefox: nothing is declared, Mozilla's DimensionInfo
// goes out as it is.
TEST(StealthWindowGeometry, TheEngineOffDeclaresNothing)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  for (const char* pref : kPrefs) {
    Preferences::ClearUser(pref);
  }
  gfx::StealthDeclaredWindowState state;
  state.mRealOuter = LayoutDeviceIntSize(1280, 1024);
  EXPECT_TRUE(gfx::StealthDeclaredWindowDimensionsNow(
                  CSSToLayoutDeviceScale(1.0f), state)
                  .isNothing());
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

// The window frame that retail Firefox 159.0 on Windows 11 build 26100 shows at
// the four persona scales, in device pixels: WINDOW_GEOMETRY_POPUP_FRAME.csv of
// the RetailCaptures repo, run 2026-11-27-window-geometry-r5 (r6 and r7 read
// the same). The border is the popup's left offset in the client origin, the
// client top is client_top_offset, the popup UI is content_top_minus_window_top
// and the maximized UI is the parent's mozInnerScreenY of the maximized frame
// rows (iframes_max) times the scale.
struct RetailFrame {
  double mScale;
  int32_t mBorder;
  int32_t mMaximizedUi;
  int32_t mPopupUi;
  int32_t mClientTop;
};

const RetailFrame kRetailFrames[] = {
    {1.0, 8, 85, 72, 31},
    {1.25, 9, 106, 89, 38},
    {1.5, 11, 109, 106, 45},
    {2.0, 13, 146, 140, 58},
};

gfx::StealthWindowFrame FrameOf(const RetailFrame& aRetail) {
  // The popup position is where a popup opened without left/top is put:
  // (4, 4) device px at every scale (the popup rows: window_left, window_top).
  return gfx::StealthWindowFrame{aRetail.mBorder, aRetail.mMaximizedUi,
                                 aRetail.mPopupUi, 4, aRetail.mClientTop};
}

}  // namespace

// The declared client origin of the top-level window, at the 4 scales: (0, 0)
// for the maximized window, the popup's position plus (border, client top) for
// a popup, (0, 0) in fullscreen. Expected: client_origin_x/y of the popup rows
// of the capture named above, (12, 35), (13, 42), (15, 49), (17, 62) for the
// popup at (4, 4) and (108, 111) at scale 1 for the popup at (100, 80).
TEST(StealthWindowGeometry, TheDeclaredClientOriginIsTheWindowsClientAreaTopLeft)
{
  const LayoutDeviceIntPoint expectedAtDefault[] = {
      LayoutDeviceIntPoint(12, 35), LayoutDeviceIntPoint(13, 42),
      LayoutDeviceIntPoint(15, 49), LayoutDeviceIntPoint(17, 62)};
  for (size_t i = 0; i < std::size(kRetailFrames); i++) {
    SCOPED_TRACE(kRetailFrames[i].mScale);
    const gfx::StealthWindowFrame frame = FrameOf(kRetailFrames[i]);
    EXPECT_EQ(gfx::StealthDeclaredClientOrigin(frame, Nothing(), false),
              LayoutDeviceIntPoint(0, 0));
    EXPECT_EQ(gfx::StealthDeclaredClientOrigin(
                  frame, Some(LayoutDeviceIntPoint(4, 4)), false),
              expectedAtDefault[i]);
    // Fullscreen, main or popup: the content is the screen.
    EXPECT_EQ(gfx::StealthDeclaredClientOrigin(frame, Nothing(), true),
              LayoutDeviceIntPoint(0, 0));
    EXPECT_EQ(gfx::StealthDeclaredClientOrigin(
                  frame, Some(LayoutDeviceIntPoint(100, 80)), true),
              LayoutDeviceIntPoint(0, 0));
  }
  EXPECT_EQ(gfx::StealthDeclaredClientOrigin(
                FrameOf(kRetailFrames[0]),
                Some(LayoutDeviceIntPoint(100, 80)), false),
            LayoutDeviceIntPoint(108, 111));
}

// The declared content origin D, at the 4 scales, from the same capture: the
// maximized window (0, maximized UI) is the parent's mozInnerScreenY of the
// maximized rows times the scale (85, 84.8 * 1.25, 72.667 * 1.5, 73 * 2); a
// popup at (4, 4) has its content at (border + 4, popup UI + 4), the
// mozInnerScreen of the popup rows times the scale (12/76, 13/93, 15/110,
// 17/144). The chrome offset T = D - client origin is 0 + maximized UI for the
// main window, and the toolbar part of a popup, 41/51/61/82.
TEST(StealthWindowGeometry, TheDeclaredChromeOffsetIsTheContentOriginMinusTheClientOrigin)
{
  const LayoutDeviceIntPoint popupContent[] = {
      LayoutDeviceIntPoint(12, 76), LayoutDeviceIntPoint(13, 93),
      LayoutDeviceIntPoint(15, 110), LayoutDeviceIntPoint(17, 144)};
  const int32_t popupChromeY[] = {41, 51, 61, 82};
  for (size_t i = 0; i < std::size(kRetailFrames); i++) {
    SCOPED_TRACE(kRetailFrames[i].mScale);
    const gfx::StealthWindowFrame frame = FrameOf(kRetailFrames[i]);
    const Maybe<LayoutDeviceIntPoint> popup = Some(LayoutDeviceIntPoint(4, 4));
    EXPECT_EQ(gfx::StealthDeclaredContentOrigin(frame, Nothing(), false),
              LayoutDeviceIntPoint(0, kRetailFrames[i].mMaximizedUi));
    EXPECT_EQ(gfx::StealthDeclaredContentOrigin(frame, popup, false),
              popupContent[i]);
    EXPECT_EQ(gfx::StealthDeclaredContentOrigin(frame, popup, false) -
                  gfx::StealthDeclaredClientOrigin(frame, popup, false),
              LayoutDeviceIntPoint(0, popupChromeY[i]));
    EXPECT_EQ(gfx::StealthDeclaredContentOrigin(frame, Nothing(), false) -
                  gfx::StealthDeclaredClientOrigin(frame, Nothing(), false),
              LayoutDeviceIntPoint(0, kRetailFrames[i].mMaximizedUi));
    // In fullscreen D is the client origin: nothing above the content.
    EXPECT_EQ(gfx::StealthDeclaredContentOrigin(frame, Nothing(), true) -
                  gfx::StealthDeclaredClientOrigin(frame, Nothing(), true),
              LayoutDeviceIntPoint(0, 0));
  }
}

namespace {

// What a page reads from a declared outer rect: Firefox's own conversion, the
// device value over the window's scale, rounded (nsGlobalWindowOuter's
// RoundedToInt(windowPos / scale) and RoundedToInt(outer / scale)).
int32_t Css(int32_t aDevice, float aScale) {
  return int32_t(floorf(float(aDevice) / aScale + 0.5f));
}

// One persona scale: the declared maximized window (the work area plus a border
// on each side) and the popup the retail captures opened at that scale. Every
// number is a row of WINDOW_GEOMETRY_POPUP_FRAME.csv, run
// 2026-11-27-window-geometry-r5, launch a:
//   - mMaximized: the iframes_max rows, outerWidth/outerHeight (CSS) times the
//     scale and screenX/screenY; the work area is the device screen minus the
//     taskbar (1920x1080 at 1, 1.25 and 1.5; 1600x1200 at 2, a taskbar of 96).
//   - mInner: the popup's inner size, innerWidth x innerHeight (500x400 CSS)
//     times the scale, and 799 high at scale 2: retail rounds the chrome height
//     to whole CSS pixels, and window_h 952 minus the popup UI 140 and the
//     border 13 leaves 799 device pixels.
//   - mDefaultPopup and mExplicitPopup: window_left/window_top and
//     window_w/window_h of the popup rows `popup` (no left/top) and `popup_pos`
//     (left=100,top=80), and the client_origin_x/y of each.
struct RetailScale {
  float mScale;
  gfx::StealthWindowFrame mFrame;
  LayoutDeviceIntRect mMaximized;
  LayoutDeviceIntSize mInner;
  LayoutDeviceIntRect mDefaultPopup;
  LayoutDeviceIntPoint mDefaultClientOrigin;
  LayoutDeviceIntRect mExplicitPopup;
  LayoutDeviceIntPoint mExplicitClientOrigin;
};

const RetailScale kRetail[] = {
    {1.0f,
     {8, 85, 72, 4, 31},
     LayoutDeviceIntRect(-8, -8, 1936, 1048),
     LayoutDeviceIntSize(500, 400),
     LayoutDeviceIntRect(4, 4, 516, 480),
     LayoutDeviceIntPoint(12, 35),
     LayoutDeviceIntRect(100, 80, 516, 480),
     LayoutDeviceIntPoint(108, 111)},
    {1.25f,
     {9, 106, 89, 4, 38},
     LayoutDeviceIntRect(-9, -9, 1938, 1038),
     LayoutDeviceIntSize(625, 500),
     LayoutDeviceIntRect(4, 4, 643, 598),
     LayoutDeviceIntPoint(13, 42),
     LayoutDeviceIntRect(125, 100, 643, 598),
     LayoutDeviceIntPoint(134, 138)},
    {1.5f,
     {11, 109, 106, 4, 45},
     LayoutDeviceIntRect(-11, -11, 1942, 1030),
     LayoutDeviceIntSize(750, 600),
     LayoutDeviceIntRect(4, 4, 772, 717),
     LayoutDeviceIntPoint(15, 49),
     LayoutDeviceIntRect(150, 120, 772, 717),
     LayoutDeviceIntPoint(161, 165)},
    {2.0f,
     {13, 146, 140, 4, 58},
     LayoutDeviceIntRect(-13, -13, 1626, 1130),
     LayoutDeviceIntSize(1000, 799),
     LayoutDeviceIntRect(4, 4, 1026, 952),
     LayoutDeviceIntPoint(17, 62),
     LayoutDeviceIntRect(200, 152, 1026, 952),
     LayoutDeviceIntPoint(213, 210)},
};

// The retail readings of the maximized window, CSS px: outerWidth/outerHeight
// and screenX/screenY of the iframes_max rows, and the parent's
// mozInnerScreenY of the same rows (what the declared chrome offset reads).
struct MaximizedReading {
  int32_t mOuterWidth;
  int32_t mOuterHeight;
  int32_t mScreen;
  float mInnerScreenY;
};

const MaximizedReading kMaximizedReading[] = {
    {1936, 1048, -8, 85.0f},
    {1550, 830, -7, 84.80000305175781f},
    {1295, 687, -7, 72.66666412353516f},
    {813, 565, -6, 73.0f},
};

// The device screen of the runs: 1920x1080, and 1600x1200 at scale 2.
const LayoutDeviceIntSize kScreenDevice[] = {
    LayoutDeviceIntSize(1920, 1080), LayoutDeviceIntSize(1920, 1080),
    LayoutDeviceIntSize(1920, 1080), LayoutDeviceIntSize(1600, 1200)};

gfx::StealthDeclaredWindowState Sized(const LayoutDeviceIntSize& aInner) {
  gfx::StealthDeclaredWindowState state;
  state.mTopInner = aInner;
  // Any real outer size but 0x0: the declaration does not read its value.
  state.mRealOuter = LayoutDeviceIntSize(1280, 1024);
  return state;
}

gfx::StealthDeclaredDimensions Declared(const RetailScale& aRetail,
                                        const gfx::StealthDeclaredWindowState& aState,
                                        size_t aIndex) {
  return gfx::StealthDeclaredWindowDimensions(
      aRetail.mFrame, aRetail.mMaximized, kScreenDevice[aIndex], aState);
}

// The window origin W the content process computes from a DimensionInfo:
// PuppetWidget::GetWindowPosition, the outer rect's origin plus the client
// offset.
LayoutDeviceIntPoint WindowOrigin(const gfx::StealthDeclaredDimensions& aDim) {
  return aDim.mRect.TopLeft() + aDim.mClientOffset;
}

}  // namespace

// The declared position of a popup at birth (gfx::StealthDeclaredPopupPosition).
// The expected values are retail Firefox 159 on Windows, round 5
// (RetailCaptures captures/WINDOW_GEOMETRY_POPUP_FRAME.csv, run 45952171443):
// window.open('', '', 'width=500,height=400') opened from the maximized window,
// with and without left=100,top=80. The declared inputs are written out, never
// recomputed: the frame (border, popup UI), the work area, the scale, and the
// maximized opener's declared position (-border, -border).
//
// A second unpositioned popup staggers to (26, 26) at scale 1 by the source
// (AppWindow.cpp:1347); no retail run has measured it, so that case has no
// expected value here. The test is added from capture round 8.
namespace {

struct PopupCase {
  float mScale;
  int32_t mBorder;
  int32_t mPopupUi;
  LayoutDeviceIntRect mAvail;  // the declared work area
  int32_t mLeft;               // left=100 in device px at this scale
  int32_t mTop;                // top=80 in device px at this scale
  LayoutDeviceIntPoint mUnpositioned;  // measured window_left, window_top
  LayoutDeviceIntPoint mPositioned;    // measured window_left, window_top
  int32_t mChromeWidthCss;             // outerWidth - 500
  int32_t mChromeHeightCss;            // outerHeight - 400
};

const PopupCase kPopupCases[] = {
    {1.0f, 8, 72, LayoutDeviceIntRect(0, 0, 1920, 1032), 100, 80,
     LayoutDeviceIntPoint(4, 4), LayoutDeviceIntPoint(100, 80), 16, 80},
    {1.25f, 9, 89, LayoutDeviceIntRect(0, 0, 1920, 1020), 125, 100,
     LayoutDeviceIntPoint(4, 4), LayoutDeviceIntPoint(125, 100), 14, 78},
    {1.5f, 11, 106, LayoutDeviceIntRect(0, 0, 1920, 1008), 150, 120,
     LayoutDeviceIntPoint(4, 4), LayoutDeviceIntPoint(150, 120), 15, 78},
    // At 2x the 952-device-pixel window (476 CSS) does not fit under the work area's
    // top edge: 160 + 952 > 1104, so the top is 1104 - 952 = 152.
    {2.0f, 13, 140, LayoutDeviceIntRect(0, 0, 1600, 1104), 200, 160,
     LayoutDeviceIntPoint(4, 4), LayoutDeviceIntPoint(200, 152), 13, 76},
};

gfx::StealthWindowFrame FrameOf(const PopupCase& aCase) {
  // maximized_ui and popup_position are not read by the popup rule.
  return gfx::StealthWindowFrame{aCase.mBorder, 1, aCase.mPopupUi, 0, 0};
}

}  // namespace

// The maximized main window, at the 4 scales: the rect is the declared
// maximized window, the client offset is the border on both axes (W = (0, 0),
// the client area starts at the screen corner), the chrome offset is the
// maximized UI. A page reads outerWidth/outerHeight and screenX/screenY of the
// retail rows, and mozInnerScreenY = (W + chrome offset) / scale.
TEST(StealthWindowGeometry, TheMaximizedWindowIsDeclaredAtTheFourScales)
{
  for (size_t i = 0; i < std::size(kRetail); i++) {
    const RetailScale& r = kRetail[i];
    const MaximizedReading& want = kMaximizedReading[i];
    SCOPED_TRACE(r.mScale);
    const gfx::StealthDeclaredDimensions d =
        Declared(r, Sized(LayoutDeviceIntSize(1280, 800)), i);
    EXPECT_EQ(d.mRect, r.mMaximized);
    EXPECT_EQ(d.mClientOffset,
              LayoutDeviceIntPoint(r.mFrame.mBorder, r.mFrame.mBorder));
    EXPECT_EQ(d.mChromeOffset, LayoutDeviceIntPoint(0, r.mFrame.mMaximizedUi));
    EXPECT_EQ(WindowOrigin(d), LayoutDeviceIntPoint(0, 0));
    EXPECT_EQ(Css(d.mRect.width, r.mScale), want.mOuterWidth);
    EXPECT_EQ(Css(d.mRect.height, r.mScale), want.mOuterHeight);
    EXPECT_EQ(Css(d.mRect.x, r.mScale), want.mScreen);
    EXPECT_EQ(Css(d.mRect.y, r.mScale), want.mScreen);
    EXPECT_FLOAT_EQ(float((WindowOrigin(d) + d.mChromeOffset).y) / r.mScale,
                    want.mInnerScreenY);
  }
}

// The popup, at the 4 scales, opened without left/top and with left=100,top=80:
// the rect is the declared position and the top's inner size plus the frame
// (2 border, popup UI + border), W is the retail client origin, the chrome
// offset is the toolbar part of the popup (popup UI - client top).
TEST(StealthWindowGeometry, ThePopupIsDeclaredAtTheFourScales)
{
  const int32_t toolbar[] = {41, 51, 61, 82};
  for (size_t i = 0; i < std::size(kRetail); i++) {
    const RetailScale& r = kRetail[i];
    SCOPED_TRACE(r.mScale);
    gfx::StealthDeclaredWindowState state = Sized(r.mInner);
    state.mPopup = true;

    // No position declared yet: the declared default stands in.
    const gfx::StealthDeclaredDimensions byDefault = Declared(r, state, i);
    EXPECT_EQ(byDefault.mRect, r.mDefaultPopup);
    EXPECT_EQ(WindowOrigin(byDefault), r.mDefaultClientOrigin);
    EXPECT_EQ(byDefault.mClientOffset,
              LayoutDeviceIntPoint(r.mFrame.mBorder, r.mFrame.mPopupClientTop));
    EXPECT_EQ(byDefault.mChromeOffset, LayoutDeviceIntPoint(0, toolbar[i]));

    // The same position declared.
    state.mPopupPosition = Some(LayoutDeviceIntPoint(4, 4));
    EXPECT_EQ(Declared(r, state, i).mRect, r.mDefaultPopup);

    // left=100,top=80: the declared position is round(100 s), round(80 s),
    // clamped into the work area (152 at scale 2).
    state.mPopupPosition = Some(r.mExplicitPopup.TopLeft());
    const gfx::StealthDeclaredDimensions explicitPos = Declared(r, state, i);
    EXPECT_EQ(explicitPos.mRect, r.mExplicitPopup);
    EXPECT_EQ(WindowOrigin(explicitPos), r.mExplicitClientOrigin);
    EXPECT_EQ(explicitPos.mChromeOffset, LayoutDeviceIntPoint(0, toolbar[i]));
  }
  // What the page reads at scale 1.25 for the default popup: the retail row
  // says outerWidth 514, outerHeight 478, screenX/screenY 3.
  gfx::StealthDeclaredWindowState at125 = Sized(kRetail[1].mInner);
  at125.mPopup = true;
  const gfx::StealthDeclaredDimensions d = Declared(kRetail[1], at125, 1);
  EXPECT_EQ(Css(d.mRect.width, 1.25f), 514);
  EXPECT_EQ(Css(d.mRect.height, 1.25f), 478);
  EXPECT_EQ(Css(d.mRect.x, 1.25f), 3);
  EXPECT_EQ(Css(d.mRect.y, 1.25f), 3);
}

// Fullscreen, main window or popup: the window is the declared screen at the
// origin and the content is the screen, so both offsets are 0. (No retail row:
// the fullscreen reading is the declared screen itself, round 8 of the
// captures measures it.)
TEST(StealthWindowGeometry, FullscreenIsTheDeclaredScreen)
{
  for (size_t i = 0; i < std::size(kRetail); i++) {
    const RetailScale& r = kRetail[i];
    SCOPED_TRACE(r.mScale);
    for (const bool popup : {false, true}) {
      gfx::StealthDeclaredWindowState state = Sized(r.mInner);
      state.mPopup = popup;
      state.mPopupPosition = Some(LayoutDeviceIntPoint(100, 80));
      state.mFullscreen = true;
      const gfx::StealthDeclaredDimensions d = Declared(r, state, i);
      EXPECT_EQ(d.mRect, LayoutDeviceIntRect(LayoutDeviceIntPoint(0, 0),
                                             kScreenDevice[i]));
      EXPECT_EQ(d.mClientOffset, LayoutDeviceIntPoint(0, 0));
      EXPECT_EQ(d.mChromeOffset, LayoutDeviceIntPoint(0, 0));
    }
  }
}

// An out-of-process frame: the rect and the client offset are the top's, and
// the chrome offset is 0 (BrowserChild asserts it): before its first matrix
// the frame reads the declared client origin, retail's round 7 value.
TEST(StealthWindowGeometry, ABridgedFrameHasNoChromeOffset)
{
  for (size_t i = 0; i < std::size(kRetail); i++) {
    const RetailScale& r = kRetail[i];
    SCOPED_TRACE(r.mScale);
    gfx::StealthDeclaredWindowState top = Sized(r.mInner);
    gfx::StealthDeclaredWindowState frame = top;
    frame.mBridged = true;
    EXPECT_EQ(Declared(r, frame, i).mRect, Declared(r, top, i).mRect);
    EXPECT_EQ(Declared(r, frame, i).mClientOffset,
              Declared(r, top, i).mClientOffset);
    EXPECT_EQ(Declared(r, frame, i).mChromeOffset, LayoutDeviceIntPoint());
    // The frame before its first matrix: W + Translation(0) is the client
    // origin of the retail rows: (0, 0) maximized, the popup's client_origin.
    EXPECT_EQ(WindowOrigin(Declared(r, frame, i)), LayoutDeviceIntPoint(0, 0));
    top.mPopup = frame.mPopup = true;
    EXPECT_EQ(WindowOrigin(Declared(r, frame, i)), r.mDefaultClientOrigin);
    EXPECT_EQ(Declared(r, frame, i).mChromeOffset, LayoutDeviceIntPoint());
    EXPECT_NE(Declared(r, top, i).mChromeOffset, LayoutDeviceIntPoint());
  }
}

// f(0x0) = 0x0: a window that has no size yet is declared empty, in every
// state, as on retail before the first layout; any other real size is replaced
// by the declaration.
TEST(StealthWindowGeometry, AWindowWithNoSizeYetStaysEmpty)
{
  for (size_t i = 0; i < std::size(kRetail); i++) {
    const RetailScale& r = kRetail[i];
    SCOPED_TRACE(r.mScale);
    for (const bool popup : {false, true}) {
      for (const bool fullscreen : {false, true}) {
        for (const bool bridged : {false, true}) {
          gfx::StealthDeclaredWindowState state = Sized(r.mInner);
          state.mPopup = popup;
          state.mFullscreen = fullscreen;
          state.mBridged = bridged;
          state.mRealOuter = LayoutDeviceIntSize(0, 0);
          const gfx::StealthDeclaredDimensions d = Declared(r, state, i);
          EXPECT_EQ(d.mRect, LayoutDeviceIntRect());
          EXPECT_EQ(d.mClientOffset, LayoutDeviceIntPoint());
          EXPECT_EQ(d.mChromeOffset, LayoutDeviceIntPoint());
          // One real side of the size is enough.
          state.mRealOuter = LayoutDeviceIntSize(0, 600);
          EXPECT_NE(Declared(r, state, i).mRect, LayoutDeviceIntRect());
          state.mRealOuter = LayoutDeviceIntSize(800, 0);
          EXPECT_NE(Declared(r, state, i).mRect, LayoutDeviceIntRect());
        }
      }
    }
  }
}

// Idempotence: the declaration is the same whether it is asked about the real
// window or about the declared one (the bridged path alternates between the
// real rect and the embedder's declared one). Nothing of the real rect but its
// emptiness is read, so the output fed back as the real outer size changes
// nothing, and so does any other real size.
TEST(StealthWindowGeometry, TheDeclarationDoesNotDependOnTheRealRect)
{
  for (size_t i = 0; i < std::size(kRetail); i++) {
    const RetailScale& r = kRetail[i];
    SCOPED_TRACE(r.mScale);
    for (const bool popup : {false, true}) {
      gfx::StealthDeclaredWindowState real = Sized(r.mInner);
      real.mPopup = popup;
      real.mPopupPosition = Some(LayoutDeviceIntPoint(100, 80));
      real.mRealOuter = LayoutDeviceIntSize(1317, 911);  // some host's window
      const gfx::StealthDeclaredDimensions once = Declared(r, real, i);
      gfx::StealthDeclaredWindowState declaredInput = real;
      declaredInput.mRealOuter = once.mRect.Size();
      const gfx::StealthDeclaredDimensions twice =
          Declared(r, declaredInput, i);
      EXPECT_EQ(once.mRect, twice.mRect);
      EXPECT_EQ(once.mClientOffset, twice.mClientOffset);
      EXPECT_EQ(once.mChromeOffset, twice.mChromeOffset);
    }
  }
}

// The request conversion, window.resizeBy / resizeTo / moveBy / moveTo of a
// popup whose real window is not where or what the declaration says (a Linux
// WM frame): the page computes from the declared rect, and the real window
// moves and resizes by the same amounts. Declared: the retail popup at scale 1,
// (4, 4, 516, 480). Real: a window at (30, 50), 700 x 640.
TEST(StealthWindowGeometry, ADeclaredRequestMovesAndResizesTheRealWindowByTheSameAmounts)
{
  const LayoutDeviceIntRect declared(4, 4, 516, 480);
  const LayoutDeviceIntRect real(30, 50, 700, 640);

  // resizeBy(0, 0) asks for the declared size: the real window keeps its own.
  const gfx::StealthOuterRequest same = gfx::StealthRealOuterRequest(
      {Nothing(), Nothing(), Some(516), Some(480)}, declared, real);
  EXPECT_EQ(same.mWidth, Some(700));
  EXPECT_EQ(same.mHeight, Some(640));
  EXPECT_TRUE(same.mX.isNothing());
  EXPECT_TRUE(same.mY.isNothing());

  // resizeBy(100, 50): the inner size grows by (100, 50) on both sides.
  const gfx::StealthOuterRequest bigger = gfx::StealthRealOuterRequest(
      {Nothing(), Nothing(), Some(616), Some(530)}, declared, real);
  EXPECT_EQ(bigger.mWidth, Some(800));
  EXPECT_EQ(bigger.mHeight, Some(690));

  // moveBy(10, -4): the real window moves by (10, -4), not to (14, 0).
  const gfx::StealthOuterRequest moved = gfx::StealthRealOuterRequest(
      {Some(14), Some(0), Nothing(), Nothing()}, declared, real);
  EXPECT_EQ(moved.mX, Some(40));
  EXPECT_EQ(moved.mY, Some(46));
  EXPECT_TRUE(moved.mWidth.isNothing());

  // The window where the declaration says it is: the request goes as it is.
  const gfx::StealthOuterRequest asIs = gfx::StealthRealOuterRequest(
      {Some(14), Some(0), Some(616), Some(530)}, declared, declared);
  EXPECT_EQ(asIs.mX, Some(14));
  EXPECT_EQ(asIs.mY, Some(0));
  EXPECT_EQ(asIs.mWidth, Some(616));
  EXPECT_EQ(asIs.mHeight, Some(530));

  // Maximized main window, scale 1: the declared rect is (-8, -8, 1936, 1048),
  // the real one a headless 1280 x 1024 window at (0, 0). resizeTo(1900, 1000)
  // asks for 36 less in width and 48 less in height than the declared window,
  // and the real window gets the same.
  const gfx::StealthOuterRequest main = gfx::StealthRealOuterRequest(
      {Nothing(), Nothing(), Some(1900), Some(1000)},
      LayoutDeviceIntRect(-8, -8, 1936, 1048),
      LayoutDeviceIntRect(0, 0, 1280, 1024));
  EXPECT_EQ(main.mWidth, Some(1244));
  EXPECT_EQ(main.mHeight, Some(976));
}

// A popup's new declared position is the requested one, over the current one
// on the axis the page did not touch (screenX = n sets only X).
TEST(StealthWindowGeometry, ARequestedPositionIsTheNewDeclaredPosition)
{
  const LayoutDeviceIntPoint current(4, 4);
  EXPECT_EQ(gfx::StealthRequestedPosition(
                {Some(100), Some(80), Nothing(), Nothing()}, current),
            Some(LayoutDeviceIntPoint(100, 80)));
  EXPECT_EQ(gfx::StealthRequestedPosition(
                {Some(100), Nothing(), Nothing(), Nothing()}, current),
            Some(LayoutDeviceIntPoint(100, 4)));
  EXPECT_EQ(gfx::StealthRequestedPosition(
                {Nothing(), Some(80), Nothing(), Nothing()}, current),
            Some(LayoutDeviceIntPoint(4, 80)));
  // A resize moves nothing.
  EXPECT_TRUE(gfx::StealthRequestedPosition(
                  {Nothing(), Nothing(), Some(616), Some(530)}, current)
                  .isNothing());
}

TEST(StealthWindowGeometry, UnpositionedPopupIsBornAtTheMarkupPosition)
{
  for (const PopupCase& c : kPopupCases) {
    const LayoutDeviceIntPoint maximizedOpener(-c.mBorder, -c.mBorder);
    EXPECT_EQ(gfx::StealthDeclaredPopupPosition(
                  gfx::StealthPopupRequest(), FrameOf(c), c.mAvail, c.mScale,
                  Span<const LayoutDeviceIntPoint>(&maximizedOpener, 1)),
              c.mUnpositioned)
        << "scale " << c.mScale;
  }
}

TEST(StealthWindowGeometry, PopupWithLeftAndTopIsClampedIntoTheWorkArea)
{
  for (const PopupCase& c : kPopupCases) {
    gfx::StealthPopupRequest request;
    request.mLeft = Some(c.mLeft);
    request.mTop = Some(c.mTop);
    request.mWidth = Some(500);
    request.mHeight = Some(400);
    request.mWidthIsInner = true;
    request.mHeightIsInner = true;
    const LayoutDeviceIntPoint maximizedOpener(-c.mBorder, -c.mBorder);
    EXPECT_EQ(gfx::StealthDeclaredPopupPosition(
                  request, FrameOf(c), c.mAvail, c.mScale,
                  Span<const LayoutDeviceIntPoint>(&maximizedOpener, 1)),
              c.mPositioned)
        << "scale " << c.mScale;
  }
}

TEST(StealthWindowGeometry, PopupChromeInCssPixelsIsRoundedTermByTerm)
{
  // outerWidth/outerHeight minus 500/400 in the capture. At 2x the height's
  // 153 device pixels are 76 CSS pixels (240 - 164), not 153 / 2.
  for (const PopupCase& c : kPopupCases) {
    EXPECT_EQ(gfx::StealthPopupChromeCssPixels(615, 2 * c.mBorder, c.mScale),
              c.mChromeWidthCss)
        << "scale " << c.mScale;
    EXPECT_EQ(gfx::StealthPopupChromeCssPixels(480, c.mPopupUi + c.mBorder,
                                               c.mScale),
              c.mChromeHeightCss)
        << "scale " << c.mScale;
  }
}

TEST(StealthWindowGeometry, PopupClampKeepsTheWindowInsideTheWorkArea)
{
  // The end first, then the start (nsWindowWatcher.cpp:2434-2452).
  EXPECT_EQ(gfx::StealthClampPopupAxis(160, 952, 0, 1104), 152);
  EXPECT_EQ(gfx::StealthClampPopupAxis(80, 480, 0, 1032), 80);
  // A window larger than the work area keeps its start on screen.
  EXPECT_EQ(gfx::StealthClampPopupAxis(50, 2000, 0, 1104), 0);
  EXPECT_EQ(gfx::StealthClampPopupAxis(-30, 480, 0, 1032), 0);
}

TEST(StealthWindowGeometry, MaximizedOpenerDoesNotStaggerAPopup)
{
  // The maximized window sits at (-border, -border), more than the stagger's
  // slop (round(4 * scale)) from the markup position (4, 4).
  for (const PopupCase& c : kPopupCases) {
    const LayoutDeviceIntPoint maximizedOpener(-c.mBorder, -c.mBorder);
    EXPECT_EQ(gfx::StealthStaggerPopupPosition(
                  LayoutDeviceIntPoint(4, 4), c.mScale,
                  Span<const LayoutDeviceIntPoint>(&maximizedOpener, 1),
                  LayoutDeviceIntSize(615, 480), c.mAvail),
              LayoutDeviceIntPoint(4, 4))
        << "scale " << c.mScale;
  }
}
