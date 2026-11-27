/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The one writer of the main window's state (gfx::StealthWindowState): Juggler
// tells the engine it is about to resize the window, with the page's
// BrowsingContext and the requested CSS size, and this observer computes the
// state the resize leaves behind. Nothing else moves the state: a change of the
// top-level inner size is not a resize (the first layout reports the host's
// real size, fullscreen the screen's), and on retail only Juggler restores the
// window.

#include <cstring>

#include "StealthDeclarationGate.h"
#include "mozilla/Atomics.h"
#include "mozilla/RefPtr.h"
#include "mozilla/ScopeExit.h"
#include "mozilla/Services.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"
#include "nsCOMPtr.h"
#include "nsIObserver.h"
#include "nsIObserverService.h"
#include "nsString.h"
#include "nsThreadUtils.h"
#include "nsXULAppAPI.h"

namespace mozilla {
namespace gfx {

namespace {

constexpr char kViewportResizeTopic[] = "stealth-viewport-resize";

class StealthViewportResizeObserver final : public nsIObserver {
 public:
  NS_DECL_ISUPPORTS
  NS_DECL_NSIOBSERVER

 private:
  ~StealthViewportResizeObserver() = default;
};

NS_IMPL_ISUPPORTS(StealthViewportResizeObserver, nsIObserver)

NS_IMETHODIMP StealthViewportResizeObserver::Observe(nsISupports* aSubject,
                                                     const char* aTopic,
                                                     const char16_t* aData) {
  if (std::strcmp(aTopic, kViewportResizeTopic) != 0 || !aData ||
      !StealthEngineActive()) {
    return NS_OK;
  }
  nsCOMPtr<dom::BrowsingContext> bc = do_QueryInterface(aSubject);
  CSSIntSize requested;
  if (!bc || !StealthParseViewportResize(nsDependentString(aData), requested)) {
    return NS_OK;
  }
  dom::BrowsingContext* top = bc->Canonical()->Top();
  // A popup is declared from its own frame; without a declaration there is no
  // window to describe.
  const Maybe<StealthWindowFrame> frame = StealthDeclaredWindowFrame();
  const Maybe<LayoutDeviceIntRect> maximized = StealthDeclaredMaximizedWindow();
  const Maybe<float> scale = StealthDeclaredScale();
  if (!top || top->GetIsPopupRequested() || !frame || !maximized || !scale) {
    return NS_OK;
  }
  const uint64_t current = top->GetStealthWindowState();
  const uint64_t next = StealthPackWindowState(
      StealthWindowStateAfterViewportResize(StealthUnpackWindowState(current),
                                            requested, *maximized, *frame,
                                            *scale));
  if (next != current) {
    (void)top->SetStealthWindowState(next);
  }
  return NS_OK;
}

}  // namespace

void StealthRegisterViewportResizeObserver() {
  // StealthEngineActive calls this, so it is not re-entered: a call that
  // arrives while it runs (main thread only) returns at once.
  static bool sInProgress = false;
  if (gStealthViewportObserverRegistered || sInProgress ||
      !XRE_IsParentProcess() || !NS_IsMainThread()) {
    return;
  }
  sInProgress = true;
  auto done = MakeScopeExit([] { sInProgress = false; });
  nsCOMPtr<nsIObserverService> observerService = services::GetObserverService();
  if (!observerService) {
    return;
  }
  RefPtr<StealthViewportResizeObserver> observer =
      new StealthViewportResizeObserver();
  if (NS_SUCCEEDED(
          observerService->AddObserver(observer, kViewportResizeTopic, false))) {
    gStealthViewportObserverRegistered = true;
  }
}

}  // namespace gfx
}  // namespace mozilla
