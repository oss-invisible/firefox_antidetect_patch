# port-02: the stable retail of the target

**Rule.** The series moves only to an official stable release tag (`FIREFOX_<version>_RELEASE`, e.g. `FIREFOX_160_0_1_RELEASE`), never to a beta or a release candidate. The engine of Firefox N is exactly retail Firefox N. Every value that was pinned to the old retail (a window frame, a table, a default) is measured again on the retail of the new version, and nothing is carried over without that measure.

**Why.** The aim is to be a retail Firefox ([product-03](product-03-windows-retail-is-the-reference.md)); a beta differs from the stable release in code and in values, and a value measured on version N-1 can be wrong on N without any conflict showing. The measure of a move to 160.0.1 lists as open the retail-measured values that must be confirmed again, with the window frame as the first one measured.

**Files.** `UPSTREAM.json` (`mozilla_tag`), `tools/engine.py` (`--to` is described as "a stable release, never a beta"), [NEXT.md](../NEXT.md); how to move: [port-01](port-01-one-run.md).

**Don't.**
- Port to a beta tag, or to a commit of Mozilla's repository that is not a release tag.
- Keep a measured value across versions because the hunk around it merged clean.
