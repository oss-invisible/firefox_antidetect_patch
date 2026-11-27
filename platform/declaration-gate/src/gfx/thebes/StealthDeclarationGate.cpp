/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthDeclarationGate.h"

#include <algorithm>
#include <cmath>

#include "mozilla/Assertions.h"
#include "mozilla/Atomics.h"
#include "mozilla/gfx/StealthRefuse.h"
#include "mozilla/Preferences.h"
#include "nsXULAppAPI.h"
#include "mozilla/StaticPrefs_layout.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "mozilla/net/StealthBranding.h"
#include "nsIFile.h"
#include "nsString.h"

namespace mozilla {
namespace gfx {

namespace {

// The refusal of a missing declaration, one sentence for every list below.
[[noreturn]] void RefuseUndeclared(const char* aName) {
  StealthRefuse(
      "stealth: %s is not declared. Engine rule 7 - a finite-domain value "
      "lives only in invisible_core, and a missing declaration refuses "
      "rather than falling back to a compiled default or to the host. "
      "Launch through invisible_core, or clear zoom.stealth.fpp.hw_seed to "
      "run as stock Firefox.",
      aName);
}

// One row per declaration whose domain is finite, i.e. per value that
// the core is the single source of. Adding a declared surface means
// adding a row here, and forgetting to is caught the first time a profile is
// generated without it rather than by a page noticing months later.
//
// The message names the pref, not "a declaration", because the person reading
// it is looking at a browser that refused to start and needs to know which one.
// The string prefs are DataMutexString, so reading one means taking the lock
// and copying out; there is no accessor that hands back a plain string.
struct StringDeclaration {
  const char* mName;
  bool (*mIsEmpty)();
};

struct IntDeclaration {
  const char* mName;
  int32_t (*mGet)();
  int32_t mFloor;  // a value below this means "not declared"
};

}  // namespace

void StealthAssertDeclarationsComplete() {
  // Stock behaviour when the engine is off: no seed, no declarations, nothing
  // to be complete about.
  if (!StealthEngineActive()) {
    return;
  }

  // PARENT PROCESS ONLY, on first use. This is the THIRD placement and the two
  // failures behind it are the reason it is written down rather than tidied.
  //
  // Attempt 1, gfxPlatform::Init: every legitimate launch hung. On the
  // production path Playwright hands the prefs over once the process is already
  // up, so at gfx-init time they do not exist. Same timing that forced the font
  // manifest onto an environment variable.
  //
  // Attempt 2, first use with no process guard: nsScreen::GetAvailRect runs in
  // the CONTENT process, and a launch with all fifteen declarations present in
  // the profile still killed that process on the first read of
  // screen.availWidth, in a restart loop. The child's MOZ_CRASH text never
  // reached the parent's stderr, so the refusal was wrong AND invisible - the
  // worst of both. WHY those prefs read as missing in a content process is not
  // established yet; that is the open follow-up, and guessing at it here would
  // be the second mistake.
  //
  // The parent is where the check belongs regardless. Prefs travel parent to
  // child, so a complete parent is the precondition for a complete child, and
  // the parent is the process whose exit code the launcher can see. A refusal
  // the parent converts into a silent child restart is not a refusal.
  if (!XRE_IsParentProcess()) {
    return;
  }
  // The observer of Juggler's viewport resizes is registered by
  // StealthEngineActive the first time it answers true in the parent; asking
  // again here is harmless (see StealthRegisterViewportResizeObserver).
  StealthRegisterViewportResizeObserver();
  static Atomic<bool> sChecked(false);
  if (sChecked.exchange(true)) {
    return;
  }

  const StringDeclaration kStrings[] = {
      {"zoom.stealth.fonts.manifest", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_fonts_manifest();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.fonts.generics", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_fonts_generics();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.media.decode_support", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_media_decode_support();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.media.decoding_info", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_media_decoding_info();
         return lock->IsEmpty();
       }},
      // The WebRTC encode set, added 2026-11-01. Missing, encodingInfo's
      // H.264 row would follow the OpenH264 plugin and the host's platform
      // encoders, and the H.264 gate the GPU blocklist.
      {"zoom.stealth.media.encode_support", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_media_encode_support();
         return lock->IsEmpty();
       }},
      // The WebGPU adapter, added 2026-10-31. Missing, a page would read the
      // host's adapter: its backend, its features, its limits, and on a
      // machine with no GPU an isFallbackAdapter of true.
      {"zoom.stealth.webgpu.adapter", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_webgpu_adapter();
         return lock->IsEmpty();
       }},
      // The graphics feature decisions, added 2026-11-01. Missing, Mozilla
      // would decide WebGL2, ANGLE, WebGPU and the video paths from this
      // machine's adapter. Validated in full by StealthGfxFeatureStatus.cpp.
      {"zoom.stealth.gfx.feature_status", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_gfx_feature_status();
         return lock->IsEmpty();
       }},
      // The WebGL renderer and vendor, added 2026-11-01. Empty, ClientWebGLContext
      // reports the host's own GL strings.
      {"zoom.stealth.webgl.renderer", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_webgl_renderer();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.webgl.vendor", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_webgl_vendor();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.webgpu.features", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_webgpu_features();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.webgpu.limits", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_webgpu_limits();
         return lock->IsEmpty();
       }},
      {"zoom.stealth.text.coverage_ladder", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_text_coverage_ladder();
         return lock->IsEmpty();
       }},
      // The speech-synthesis voice list, added 2026-08-09 with the six ints
      // below. When it is empty SpeechSynthesis::GetVoices falls through to
      // nsSynthVoiceRegistry, i.e. the OS TTS registry - which names the real
      // operating system and every language pack installed on it, in one
      // `speechSynthesis.getVoices()`.
      {"zoom.stealth.voices.list", []() -> bool {
         auto lock = StaticPrefs::zoom_stealth_voices_list();
         return lock->IsEmpty();
       }},
      // The branding a page reads, added 2026-10-16. Missing, it would serve
      // the build's own brand: the compiled fallback this gate exists against.
      // "Not declared" here also means "not usable": the same predicate the
      // content sandbox uses to open the archive, so a launch this gate lets
      // through is one whose content processes can read the files.
      {"zoom.stealth.branding.archive", []() -> bool {
         nsCOMPtr<nsIFile> archive =
             mozilla::net::StealthBrandingDeclaredArchive();
         return !archive;
       }},
  };

  for (const auto& d : kStrings) {
    if (d.mIsEmpty()) {
      RefuseUndeclared(d.mName);
    }
  }

  const IntDeclaration kInts[] = {
      {"zoom.stealth.screen.taskbar_px",
       []() { return StaticPrefs::zoom_stealth_screen_taskbar_px(); }, 0},
      {"zoom.stealth.screen.color_depth",
       []() { return StaticPrefs::zoom_stealth_screen_color_depth(); }, 1},
      {"zoom.stealth.max_touch_points",
       []() { return StaticPrefs::zoom_stealth_max_touch_points(); }, 0},
      // The FreeType hinting style and antialias, added 2026-08-16. Without
      // them `PrepareFontOptions` goes back to asking the fontconfig pattern,
      // that is, the machine: same binary, same page, different pixel hash as
      // `/etc/fonts` varies - 3842037683 with the host (which here is
      // `hintslight`), 1512591551 with an empty configuration, 2489286717 with
      // `hintnone`, measured through the product.
      //
      // The floor is 0 and the sentinel is -1, because 0 is a legal value for
      // both: `FC_HINT_NONE` is 0 and so is antialias off.
      //
      // They are read only by the GTK branch, and the gate requires them on
      // every platform on purpose: a declaration that holds for one build only
      // is a declaration somebody will forget to ship, and the build that
      // forgets it is not the one that notices.
      // The tolerance of the canvas noise's two-colour test, added 2026-10-19
      // with the single canvas function: a pixel whose neighbourhood is a
      // blend of two colours within it (text, two-colour antialiasing) is left
      // as drawn. 0 is a valid declaration; the undeclared -1 is not.
      {"zoom.stealth.canvas.edge_tolerance",
       []() { return StaticPrefs::zoom_stealth_canvas_edge_tolerance(); }, 0},
      // The Windows text quality, added 2026-10-19 ([B362]): read by
      // gfxDWriteFonts' GetSystemTextQuality instead of SystemParametersInfo.
      // Required on both platforms, like the cleartype_params it gates: a
      // profile is complete or it is not. The floor refuses the undeclared -1;
      // a value outside 0/4/5 is refused where it is read.
      {"zoom.stealth.text.system_quality",
       []() { return StaticPrefs::zoom_stealth_text_system_quality(); }, 0},
      {"zoom.stealth.text.freetype_hintstyle",
       []() { return StaticPrefs::zoom_stealth_text_freetype_hintstyle(); }, 0},
      {"zoom.stealth.text.freetype_antialias",
       []() { return StaticPrefs::zoom_stealth_text_freetype_antialias(); }, 0},
      // The window geometry, in DEVICE pixels since firefox-38 (B258, B261).
      // Until then four CSS integers - window_x, window_y, chrome_w, chrome_h -
      // added 2026-08-09 after screenX + outerWidth came to 1924 on a 1920
      // screen. The group is still declared whole or not at all, for the same
      // reason. Floors: a maximized window and a popup always have UI above
      // their content, a work area narrower than 320 is a bug; the border and
      // the popup position may be 0, so the sentinel is -1.
      {"zoom.stealth.screen.frame_border",
       []() { return StaticPrefs::zoom_stealth_screen_frame_border(); }, 0},
      {"zoom.stealth.screen.maximized_ui",
       []() { return StaticPrefs::zoom_stealth_screen_maximized_ui(); }, 1},
      {"zoom.stealth.screen.popup_ui",
       []() { return StaticPrefs::zoom_stealth_screen_popup_ui(); }, 1},
      {"zoom.stealth.screen.popup_position",
       []() { return StaticPrefs::zoom_stealth_screen_popup_position(); }, 0},
      // The restored main window (Page.setViewportSize resizes the maximized
      // one): the UI height of each density, the density threshold in CSS
      // pixels, the position, the smallest chrome in CSS pixels. The position
      // may be 0; the rest never is.
      {"zoom.stealth.screen.ui_normal",
       []() { return StaticPrefs::zoom_stealth_screen_ui_normal(); }, 1},
      {"zoom.stealth.screen.ui_compact",
       []() { return StaticPrefs::zoom_stealth_screen_ui_compact(); }, 1},
      {"zoom.stealth.screen.compact_below_css",
       []() { return StaticPrefs::zoom_stealth_screen_compact_below_css(); },
       1},
      {"zoom.stealth.screen.restored_position",
       []() { return StaticPrefs::zoom_stealth_screen_restored_position(); },
       0},
      {"zoom.stealth.screen.min_inner_width_css",
       []() { return StaticPrefs::zoom_stealth_screen_min_inner_width_css(); },
       1},
      {"zoom.stealth.screen.min_inner_height_css",
       []() { return StaticPrefs::zoom_stealth_screen_min_inner_height_css(); },
       1},
      {"zoom.stealth.screen.avail_device_width",
       []() { return StaticPrefs::zoom_stealth_screen_avail_device_width(); },
       320},
      {"zoom.stealth.screen.avail_device_height",
       []() { return StaticPrefs::zoom_stealth_screen_avail_device_height(); },
       240},
      // The CSS interaction media features, added 2026-08-09. Floor 1 rather
      // than 0: PointerCapabilities::None is a legal value of the enum and a
      // nonsensical value for a machine somebody is browsing from, so a zero
      // here is a bug rather than a persona.
      {"zoom.stealth.pointer.primary",
       []() { return StaticPrefs::zoom_stealth_pointer_primary(); }, 1},
      {"zoom.stealth.pointer.all",
       []() { return StaticPrefs::zoom_stealth_pointer_all(); }, 1},
      // Six that this gate did NOT cover until 2026-08-09, and every one of
      // them is declared unconditionally by the core. That is exactly
      // what made the hole invisible: nothing is broken in normal operation,
      // so no measurement could see it. What it costs is the refusal - if any
      // of these six ever went missing (a refactor dropping a line from
      // prefs.py, an older launcher, a direct launch), the engine would not
      // stop. It would read the REAL MACHINE and carry on:
      //
      //   screen.width / height  -> nsScreen::GetRect falls to the real
      //                             monitor, and GetAvailRect and
      //                             GetOuterSize fall with it
      //   hw_concurrency         -> the real CPU core count, on the main
      //                             thread AND inside every Worker
      //   audio.sample_rate      -> the real device rate through cubeb
      //   audio.max_channel_count-> the real sound card's channel count
      //   voices.list            -> the OS TTS registry, which names the
      //                             installed language packs
      //
      // The floors say what "declared" means for each: a screen narrower than
      // 320 or a machine with no cores is a bug, not a persona.
      {"zoom.stealth.screen.width",
       []() { return StaticPrefs::zoom_stealth_screen_width(); }, 320},
      {"zoom.stealth.screen.height",
       []() { return StaticPrefs::zoom_stealth_screen_height(); }, 240},
      {"zoom.stealth.hw_concurrency",
       []() { return StaticPrefs::zoom_stealth_hw_concurrency(); }, 1},
      {"zoom.stealth.audio.sample_rate",
       []() { return StaticPrefs::zoom_stealth_audio_sample_rate(); }, 8000},
      {"zoom.stealth.audio.max_channel_count",
       []() { return StaticPrefs::zoom_stealth_audio_max_channel_count(); }, 1},
      {"zoom.stealth.audio.output_latency_ms",
       []() { return StaticPrefs::zoom_stealth_audio_output_latency_ms(); }, 1},
  };

  // The rasterisation parameters are checked here too, and they are the reason
  // this list is worth keeping rather than trusting the callers.
  // gfxDWriteFont::UpdateClearTypeVars opens with five hard-coded values -
  // ClearType level 1.0, contrast 1.0, gamma 2.2, RGB geometry, DEFAULT
  // rendering mode - and only then lets these prefs override them, each on a
  // -1 sentinel. With the engine on and one pref missing, the compiled value
  // wins in silence, which is the second source of truth engine rule 7
  // forbids. It is not hypothetical: the core declares rendering_mode 5 while
  // the compiled default is DWRITE_RENDERING_MODE_DEFAULT, which is 0, so the
  // two answers were never even the same number.
  //
  // Plain Preferences rather than StaticPrefs because that is how the
  // rasteriser reads them, and a gate has to check the value the code will
  // actually see. Both platforms' sets are required on both platforms: a
  // profile is complete or it is not, and which half the host happens to use
  // is not the profile's business.
  static const char* const kRasterInts[] = {
      "gfx.font_rendering.cleartype_params.gamma",
      "gfx.font_rendering.cleartype_params.enhanced_contrast",
      "gfx.font_rendering.cleartype_params.cleartype_level",
      "gfx.font_rendering.cleartype_params.pixel_structure",
      "gfx.font_rendering.cleartype_params.rendering_mode",
      "gfx.font_rendering.freetype.gamma",
      "gfx.font_rendering.freetype.enhanced_contrast",
  };
  for (const char* name : kRasterInts) {
    if (Preferences::GetInt(name, -1) < 0) {
      RefuseUndeclared(name);
    }
  }

  for (const auto& d : kInts) {
    if (d.mGet() < d.mFloor) {
      RefuseUndeclared(d.mName);
    }
  }

  // One scale for the whole window geometry, added 2026-11-02. The screen is
  // declared in CSS pixels and the work area and window frame in device
  // pixels; the page reads every CSS value through layout.css.devPixelsPerPx.
  // A scale that is not the one the declaration was made at (run 41325657085:
  // a 100% persona under a forced 1.5 read innerWidth 1920 inside an
  // outerWidth of 1291) is an identity no machine has, and a missing one (-1)
  // is the host's own scale. Both refuse.
  const float dpr = StaticPrefs::layout_css_devPixelsPerPx();
  const int32_t screenWidth = StaticPrefs::zoom_stealth_screen_width();
  const int32_t availDeviceWidth =
      StaticPrefs::zoom_stealth_screen_avail_device_width();
  if (!StealthScaleMatchesDeclaration(dpr, screenWidth, availDeviceWidth)) {
    StealthRefuse(
        "stealth: layout.css.devPixelsPerPx is %.4f, but the declared screen "
        "is %d CSS pixels over a %d device-pixel work area. The scale is part "
        "of the declaration (invisible_core sets it from the persona's DPR): "
        "pin screen.dpr instead of overriding the pref.",
        double(dpr), screenWidth, availDeviceWidth);
  }
}

bool StealthScaleMatchesDeclaration(float aDevPixelsPerPx,
                                    int32_t aScreenWidth,
                                    int32_t aAvailDeviceWidth) {
  if (!(aDevPixelsPerPx > 0.0f) || aScreenWidth <= 0 ||
      aAvailDeviceWidth <= 0) {
    return false;
  }
  // The work area spans the screen's width (the taskbar is at the bottom), so
  // the CSS width times the scale is the device width, give or take the
  // rounding of a fractional CSS width (1707 x 1.5 = 2560.5 for 2560).
  const double device = double(aScreenWidth) * double(aDevPixelsPerPx);
  return std::abs(device - double(aAvailDeviceWidth)) <= 1.0;
}

Maybe<StealthWindowFrame> StealthDeclaredWindowFrame() {
  if (!StealthEngineActive()) {
    // Stock Firefox. Not an incomplete declaration, the absence of one.
    return Nothing();
  }
  const StealthWindowFrame frame{
      StaticPrefs::zoom_stealth_screen_frame_border(),
      StaticPrefs::zoom_stealth_screen_maximized_ui(),
      StaticPrefs::zoom_stealth_screen_popup_ui(),
      StaticPrefs::zoom_stealth_screen_popup_position(),
      StaticPrefs::zoom_stealth_screen_ui_normal(),
      StaticPrefs::zoom_stealth_screen_ui_compact(),
      StaticPrefs::zoom_stealth_screen_compact_below_css(),
      StaticPrefs::zoom_stealth_screen_restored_position(),
      StaticPrefs::zoom_stealth_screen_min_inner_width_css(),
      StaticPrefs::zoom_stealth_screen_min_inner_height_css()};
  if (frame.mBorder < 0 || frame.mMaximizedUi < 1 || frame.mPopupUi < 1 ||
      frame.mPopupPosition < 0 || frame.mUiNormal < 1 || frame.mUiCompact < 1 ||
      frame.mCompactBelowCss < 1 || frame.mRestoredPosition < 0 ||
      frame.mMinInnerWidthCss < 1 || frame.mMinInnerHeightCss < 1) {
    // Unreachable in practice: the gate refuses at launch in the parent, so a
    // process that is serving pages has these. Kept as a refusal rather than a
    // fallback, because the day it becomes reachable the right behaviour is
    // still to stop, not to answer with the machine's real window.
    StealthAssertDeclarationsComplete();
    return Nothing();
  }
  return Some(frame);
}

Maybe<LayoutDeviceIntRect> StealthDeclaredMaximizedWindow() {
  const Maybe<StealthWindowFrame> frame = StealthDeclaredWindowFrame();
  if (frame.isNothing()) {
    return Nothing();
  }
  const int32_t w = StaticPrefs::zoom_stealth_screen_avail_device_width();
  const int32_t h = StaticPrefs::zoom_stealth_screen_avail_device_height();
  if (w < 320 || h < 240) {
    StealthAssertDeclarationsComplete();
    return Nothing();
  }
  const int32_t b = frame->mBorder;
  return Some(LayoutDeviceIntRect(-b, -b, w + 2 * b, h + 2 * b));
}

uint64_t StealthPackWindowState(const StealthWindowState& aState) {
  if (!aState.mRestored) {
    return 0;
  }
  constexpr int32_t kMax = (1 << 24) - 1;
  const uint64_t width = uint64_t(std::clamp(aState.mOuter.width, 0, kMax));
  const uint64_t height = uint64_t(std::clamp(aState.mOuter.height, 0, kMax));
  return 1 | (uint64_t(aState.mCompact) << 1) | (width << 2) | (height << 26);
}

StealthWindowState StealthUnpackWindowState(uint64_t aPacked) {
  StealthWindowState state;
  if (!(aPacked & 1)) {
    return state;
  }
  constexpr uint64_t kMask = (uint64_t(1) << 24) - 1;
  state.mRestored = true;
  state.mCompact = ((aPacked >> 1) & 1) != 0;
  state.mOuter = LayoutDeviceIntSize(int32_t((aPacked >> 2) & kMask),
                                     int32_t((aPacked >> 26) & kMask));
  return state;
}

Maybe<float> StealthDeclaredScale() {
  if (!StealthEngineActive()) {
    return Nothing();
  }
  const float dpr = StaticPrefs::layout_css_devPixelsPerPx();
  if (!StealthScaleMatchesDeclaration(
          dpr, StaticPrefs::zoom_stealth_screen_width(),
          StaticPrefs::zoom_stealth_screen_avail_device_width())) {
    // Unreachable in practice, like the frame: the gate refuses at launch in
    // the parent. Never the widget's scale in its place.
    StealthAssertDeclarationsComplete();
    return Nothing();
  }
  return Some(dpr);
}

CSSIntSize StealthMaximizedContent(const LayoutDeviceIntRect& aMaximized,
                                   const StealthWindowFrame& aFrame,
                                   float aScale) {
  const int32_t b = aFrame.mBorder;
  return RoundedToInt(
      LayoutDeviceIntSize(aMaximized.width - 2 * b,
                          aMaximized.height - 2 * b - aFrame.mMaximizedUi) /
      CSSToLayoutDeviceScale(aScale));
}

StealthWindowState StealthNextWindowState(const StealthWindowState& aOld,
                                          const CSSIntSize& aNewInner,
                                          const LayoutDeviceIntRect& aMaximized,
                                          const StealthWindowFrame& aFrame,
                                          float aScale) {
  // A size with a side of zero is no request.
  if (aNewInner.width <= 0 || aNewInner.height <= 0) {
    return aOld;
  }
  const CSSToLayoutDeviceScale scale(aScale);
  const int32_t b = aFrame.mBorder;
  // A window that was never restored and is asked for the maximized content is
  // the maximized window (resizeBy(0, 0) does nothing). A restored one stays
  // restored, whatever size it is resized to (retail does not maximize it
  // again): it goes through the same resize as any other.
  if (!aOld.mRestored &&
      aNewInner == StealthMaximizedContent(aMaximized, aFrame, aScale)) {
    return aOld;
  }

  // The window the resize starts from: its outer size, its chrome (the client
  // area, the part of the outer size inside the frame) and the bar over the
  // content.
  LayoutDeviceIntSize outer;
  LayoutDeviceIntSize chrome;
  int32_t bar;
  if (aOld.mRestored) {
    outer = aOld.mOuter;
    chrome = LayoutDeviceIntSize(outer.width - 2 * b, outer.height - b);
    bar = aOld.mCompact ? aFrame.mUiCompact : aFrame.mUiNormal;
  } else {
    outer = aMaximized.Size();
    chrome = LayoutDeviceIntSize(outer.width - 2 * b, outer.height - 2 * b);
    bar = aFrame.mMaximizedUi;
  }

  // Juggler: resizeBy(w - innerWidth, h + toolbarTop - innerHeight) on the
  // window, CSS pixels, a long each (truncated toward zero). The chrome's
  // inner size and the bar are FRACTIONAL CSS pixels (Firefox 159, device
  // pixels over the scale, in float as Gecko holds them), not rounded before
  // the delta; resizeBy adds the deltas to the outer size rounded to CSS
  // pixels and converts back with rounding.
  const CSSIntSize outerCss = RoundedToInt(outer / scale);
  const CSSSize chromeCss = chrome / scale;
  const float barCss = float(bar) / aScale;
  const int32_t dw = int32_t(double(aNewInner.width) - double(chromeCss.width));
  const int32_t dh = int32_t(double(aNewInner.height) + double(barCss) -
                             double(chromeCss.height));
  LayoutDeviceIntSize next =
      RoundedToInt(CSSIntSize(std::max(0, outerCss.width + dw),
                              std::max(0, outerCss.height + dh)) *
                   scale);
  // Not under the smallest chrome.
  const LayoutDeviceIntSize minChrome = RoundedToInt(
      CSSIntSize(aFrame.mMinInnerWidthCss, aFrame.mMinInnerHeightCss) * scale);
  next.width = std::max(next.width, minChrome.width + 2 * b);
  next.height = std::max(next.height, minChrome.height + b);

  StealthWindowState state;
  state.mRestored = true;
  state.mOuter = next;
  // The density is decided again from the chrome height after the resize.
  state.mCompact = double(next.height - b) / double(aScale) <
                   double(aFrame.mCompactBelowCss);
  return state;
}

StealthWindowState StealthWindowStateAfterViewportResize(
    const StealthWindowState& aOld, const CSSIntSize& aRequested,
    const LayoutDeviceIntRect& aMaximized, const StealthWindowFrame& aFrame,
    float aDeclaredScale) {
  return StealthNextWindowState(aOld, aRequested, aMaximized, aFrame,
                                aDeclaredScale);
}

namespace {

// One or more decimal digits, nothing else, at most five of them.
bool ParseDecimal(const nsAString& aText, int32_t& aOut) {
  if (aText.IsEmpty() || aText.Length() > 5) {
    return false;
  }
  int32_t value = 0;
  for (uint32_t i = 0; i < aText.Length(); ++i) {
    const char16_t c = aText[i];
    if (c < u'0' || c > u'9') {
      return false;
    }
    value = value * 10 + int32_t(c - u'0');
  }
  aOut = value;
  return true;
}

}  // namespace

bool StealthParseViewportResize(const nsAString& aData, CSSIntSize& aOut) {
  const int32_t comma = aData.FindChar(u',');
  if (comma <= 0) {
    return false;
  }
  int32_t width;
  int32_t height;
  if (!ParseDecimal(Substring(aData, 0, comma), width) ||
      !ParseDecimal(Substring(aData, comma + 1), height) || width < 1 ||
      height < 1 || width > kStealthMaxRequestedCss ||
      height > kStealthMaxRequestedCss) {
    return false;
  }
  aOut = CSSIntSize(width, height);
  return true;
}

Maybe<LayoutDeviceIntRect> StealthRestoredWindowRect(
    const StealthWindowState& aState, const StealthWindowFrame& aFrame) {
  if (!aState.mRestored) {
    return Nothing();
  }
  return Some(LayoutDeviceIntRect(aFrame.mRestoredPosition,
                                  aFrame.mRestoredPosition, aState.mOuter.width,
                                  aState.mOuter.height));
}

Maybe<LayoutDeviceIntPoint> StealthRestoredContentOrigin(
    const StealthWindowState& aState, const StealthWindowFrame& aFrame) {
  if (!aState.mRestored) {
    return Nothing();
  }
  return Some(LayoutDeviceIntPoint(
      aFrame.mRestoredPosition + aFrame.mBorder,
      aFrame.mRestoredPosition +
          (aState.mCompact ? aFrame.mUiCompact : aFrame.mUiNormal)));
}

bool StealthOuterSizeIsDeclared(const LayoutDeviceIntSize& aRealOuter) {
  return aRealOuter.width != 0 || aRealOuter.height != 0;
}

Maybe<nsPoint> StealthDeclaredOriginShift(
    const nsPoint& aRealContentOrigin,
    const Maybe<LayoutDeviceIntPoint>& aPopupWindowOrigin,
    const Maybe<LayoutDeviceIntPoint>& aRestoredContentOrigin, bool aFullscreen,
    int32_t aAppUnitsPerDevPixel) {
  const Maybe<StealthWindowFrame> frame = StealthDeclaredWindowFrame();
  if (frame.isNothing()) {
    return Nothing();
  }
  // A fullscreen window's content is the screen; the maximized window's
  // starts at the screen's left edge, the UI height below its top; a popup's
  // starts a border in and the popup UI down from wherever the popup really
  // is; a restored main window's starts at its own content origin.
  const LayoutDeviceIntPoint declared =
      aFullscreen ? LayoutDeviceIntPoint(0, 0)
      : aPopupWindowOrigin
          ? *aPopupWindowOrigin +
                LayoutDeviceIntPoint(frame->mBorder, frame->mPopupUi)
      : aRestoredContentOrigin
          ? *aRestoredContentOrigin
          : LayoutDeviceIntPoint(0, frame->mMaximizedUi);
  return Some(LayoutDevicePixel::ToAppUnits(declared, aAppUnitsPerDevPixel) -
              aRealContentOrigin);
}

int32_t StealthDeclaredPixelDepth() {
  const int32_t declared = StaticPrefs::zoom_stealth_screen_color_depth();
  return declared > 0 ? declared : 0;
}

Maybe<CSSIntRect> StealthDeclaredScreenRect() {
  const int32_t w = StaticPrefs::zoom_stealth_screen_width();
  const int32_t h = StaticPrefs::zoom_stealth_screen_height();
  if (w > 0 && h > 0) {
    return Some(CSSIntRect(0, 0, w, h));
  }
  return Nothing();
}

Maybe<CSSIntRect> StealthDeclaredAvailRect() {
  const int32_t w = StaticPrefs::zoom_stealth_screen_width();
  const int32_t h = StaticPrefs::zoom_stealth_screen_height();
  if (w > 0 && h > 0) {
    // First use of a declared value in this process refuses if the set is
    // incomplete. Cheap after the first call, and it runs BEFORE the value is
    // handed back, so nothing can be served from a compiled default.
    StealthAssertDeclarationsComplete();
    return Some(
        CSSIntRect(0, 0, w, h - StaticPrefs::zoom_stealth_screen_taskbar_px()));
  }
  return Nothing();
}

}  // namespace gfx
}  // namespace mozilla
