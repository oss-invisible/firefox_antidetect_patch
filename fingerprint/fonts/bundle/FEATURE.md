# fingerprint/fonts/bundle

Category: build, other, spoof
Prefs: none read directly
Test: gtest StealthBundleHooks.BorrowedFontDataIsNotFreed, StealthBundleHooks.FallbackNamesTakeThePresentation, StealthBundleHooks.TwoArgumentLookupReadsFaceZeroOfACollection, StealthBundleHooks.CollectionWithNoFaceFindsNothing (TestStealthBundleHooks.h, included by TestStealthFcFontList.cpp on Linux and TestStealthBundledCollection.cpp on Windows), StealthFcBundleFonts.FallbackNeverDefersUnderBundleOnly, StealthTtcFace.* and StealthFallbackNames.* (TestStealthBundledCollection.cpp, TestStealthFcFontList.cpp, folder fingerprint/fonts/font-list); wrapper e2e test_system_fonts_and_colors_are_windows_e2e.py, test_canvas_text_is_windows_e2e.py, test_screenshot_of_text_returns_linux_e2e.py; to write in the wrapper: test_text_widths_do_not_depend_on_load_order_e2e.py

## What it does

The Windows retail fonts (121 files, 218.7 MB) travel in the package under `fonts/` and are the only fonts
the browser has, on every host. DirectWrite and FreeType read each file through ONE shared mapping of the file
(`StealthBundleFontList`, a cache that lives for the process), lent to every face of that file as a borrowed
`FontData` that does not free it. The faces of a `.ttc` are addressed by index (`gfxFontUtils` table lookup
with a face index, `gfxDWriteFontEntry::mBundleFaceIndex`). On Windows the path of the file travels with the
`UnscaledFontDWrite`, so WebRender receives the path and not 65.9 MB of bytes. On Linux the Windows
fallback names come first (`gfxPlatformGtk::GetCommonFallbackFonts`), and the cmap of a bundled face is
published to the shared font list. The font-list side (which faces, which families, which generics) is
fingerprint/fonts/font-list.

## Hooks in Mozilla files

One line each, with the marker `// STEALTH-HOOK(fingerprint/fonts/bundle)` on it (the one of gfx/thebes/moz.build
sits beside the lines of the other folders):

- `browser/fonts/moz.build`: `include("StealthFonts.mozbuild")` after Mozilla's last statement (registration).
- `gfx/2d/ScaledFontDWrite.cpp`: guard `if (StealthGetSeededDescriptor(aCb, aBaton)) return true;` as the first
  statement of `UnscaledFontDWrite::GetFontDescriptor`. The declared path lives where Mozilla keeps the file
  name (`mFontFileName`: path plus terminator), so the callback gets the bytes, the face index and the `true`
  of the block that was here before. For a font that was never seeded the guard says no and Mozilla's lines run.
  Firefox 160 fills `mFontFileName` itself in `CreateFromFontDescriptor`; the hook becomes redundant at the port.
- `gfx/2d/UnscaledFontDWrite.h`: `#include <string>` in a block of ours; two member declarations, `void
  StealthSeedFilePath(const std::wstring&)` and `bool StealthGetSeededDescriptor(FontDescriptorOutput, void*)`
  (defined in StealthDWriteFontList.cpp). Mozilla's two-argument constructor is back, and the data member
  `mPercorsoDichiarato` is gone.
- `gfx/thebes/FontData.h`: members `enum class Borrowed`, the declaration of the `Borrowed` constructor
  (`explicit`, defined in StealthBundleFontList.cpp), `friend uint8_t* StealthFontDataOwned(...)`, `bool const
  mBorrowed`, and the wrap in the destructor: `free(StealthFontDataOwned(this, const_cast<uint8_t*>(mData)))`
  (one Mozilla line rewritten: `free(nullptr)` is a no-op, so a borrowed FontData frees nothing).
- `gfx/thebes/gfxDWriteFontList.h`: `#include <string>` in a block of ours, the members `mBundleFaceIndex`
  and `mBundleFilePath` and the declaration of `CreateStealthBundleFontEntry` (members, one line each).
- `gfx/thebes/gfxFcPlatformFontList.h`: `friend struct StealthFcAccess;` (marker fingerprint/fonts/font-list: the struct
  is in StealthFcFontList.cpp), after Mozilla's first friend.
- `gfx/thebes/gfxFontEntry.h`: member `bool ShouldPublishCharacterMap() const;` (defined in
  StealthBundleFontList.cpp; the back ends' hooks use the same rule through `StealthPublishCharacterMap`,
  fingerprint/fonts/font-list). Declared exception (G35): `AutoHBFace` conversion operators, see below.
- `gfx/thebes/gfxFontUtils.cpp`: `#include "StealthBundleFontList.h"` in a block of ours, and one wrap in Mozilla's
  `FindTableDirEntry`: `const SFNTHeader* header = StealthSfntHeader(reinterpret_cast<const SFNTHeader*>(aFontData));`.
  `GetTableFromFontData` is Mozilla's again. For a collection the two-argument form reads face 0, as the
  three-argument form with index 0 did.
- `gfx/thebes/gfxFontUtils.h`: three members, `FindSfntOffset(const void*, uint32_t)` and the three-argument
  `FindTableDirEntry` and `GetTableFromFontData` (no default argument; the two-argument forms are Mozilla's).
- `gfx/thebes/gfxPlatformGtk.cpp`: `#include "StealthBundleFontList.h"` in a block of ours and the notice
  `StealthAppendWindowsFallbackNames(aPresentation, aFontList);` as the first statement of
  `GetCommonFallbackFonts` (the overload that takes the presentation calls the bool one on `PrefersColor`).
- `gfx/thebes/gfxTextRun.cpp`: `#include "StealthBundleFontList.h"` in a block of ours and one wrap in
  `FindFallbackFaceForChar`: `StealthFallbackMayDefer(StaticPrefs::gfx_font_rendering_fallback_async()) &&`
  as the middle operand of Mozilla's condition (its other two lines are Mozilla's again).
- `gfx/thebes/moz.build`: `include("StealthBundleFontList.mozbuild")`.

Files that left the series: `gfx/thebes/gfxFontEntry.cpp` (the definition of `ShouldPublishCharacterMap` is in our
file) and `browser/installer/package-manifest.in` (the macOS term of the `#if` is dead: macOS support ended on
2026-08-26, and Linux and Windows define `MOZ_WIDGET_GTK` and `XP_WIN`, so the packaged archives are the same).
The CoreText-only helpers (`GetPsname`, and in the font-list folder `StealthDropFamily`,
`StealthSetBundledFamilyNames`, `StealthBundledCTFontEntry`, `StealthUiFamily`) left our files with
`CoreTextFontList.cpp`: no leg of the series builds it (G25).

## Our own files

- `browser/fonts/LEELAWUI.TTF`
- `browser/fonts/LUCON.TTF`
- `browser/fonts/L_10646.TTF`
- `browser/fonts/Nirmala.ttf`
- `browser/fonts/SitkaSmall.ttf`
- `browser/fonts/StealthFonts.mozbuild`
- `browser/fonts/arial7_04.ttf`
- `browser/fonts/arialbd7_04.ttf`
- `browser/fonts/arialbi7_04.ttf`
- `browser/fonts/ariali7_04.ttf`
- `browser/fonts/ariblk.ttf`
- `browser/fonts/bahnschrift2_07.ttf`
- `browser/fonts/bundle-fonts.list`
- `browser/fonts/calibri6_26.ttf`
- `browser/fonts/calibrib6_26.ttf`
- `browser/fonts/calibrii6_26.ttf`
- `browser/fonts/calibriz6_26.ttf`
- `browser/fonts/cambria6_99.ttc`
- `browser/fonts/cambriab6_98.ttf`
- `browser/fonts/cambriai6_98.ttf`
- `browser/fonts/cambriaz6_98.ttf`
- `browser/fonts/candara5_64.ttf`
- `browser/fonts/candarab5_64.ttf`
- `browser/fonts/candarai5_64.ttf`
- `browser/fonts/candaraz5_64.ttf`
- `browser/fonts/comic5_15.ttf`
- `browser/fonts/comicbd5_15.ttf`
- `browser/fonts/comici5_15.ttf`
- `browser/fonts/comicz5_15.ttf`
- `browser/fonts/consola7_00.ttf`
- `browser/fonts/consolab7_00.ttf`
- `browser/fonts/consolai7_00.ttf`
- `browser/fonts/consolaz7_00.ttf`
- `browser/fonts/constan5_93.ttf`
- `browser/fonts/constanb5_93.ttf`
- `browser/fonts/constani5_93.ttf`
- `browser/fonts/constanz5_93.ttf`
- `browser/fonts/corbel6_01.ttf`
- `browser/fonts/corbelb6_01.ttf`
- `browser/fonts/corbeli6_01.ttf`
- `browser/fonts/corbelz6_01.ttf`
- `browser/fonts/cour6_94.ttf`
- `browser/fonts/courbd6_94.ttf`
- `browser/fonts/courbi6_94.ttf`
- `browser/fonts/couri6_94.ttf`
- `browser/fonts/ebrima5_19.ttf`
- `browser/fonts/ebrimabd5_19.ttf`
- `browser/fonts/framd5_02.ttf`
- `browser/fonts/framdit5_01.ttf`
- `browser/fonts/gabriola5_93.ttf`
- `browser/fonts/gadugi1_13.ttf`
- `browser/fonts/gadugib1_13.ttf`
- `browser/fonts/georgia5_59.ttf`
- `browser/fonts/georgiab5_59.ttf`
- `browser/fonts/georgiai5_59.ttf`
- `browser/fonts/georgiaz5_59.ttf`
- `browser/fonts/himalaya5_23.ttf`
- `browser/fonts/impact5_11.ttf`
- `browser/fonts/inkfree2_00.ttf`
- `browser/fonts/javatext1_10.ttf`
- `browser/fonts/leelauib5_06.ttf`
- `browser/fonts/leelawui5_06.ttf`
- `browser/fonts/malgun.ttf`
- `browser/fonts/marlett5_01.ttf`
- `browser/fonts/micross7_03.ttf`
- `browser/fonts/mingliub.ttc`
- `browser/fonts/mmrtext1_21.ttf`
- `browser/fonts/mmrtextb1_21.ttf`
- `browser/fonts/monbaiti5_54.ttf`
- `browser/fonts/msgothic5_32.ttc`
- `browser/fonts/msjh6_15.ttc`
- `browser/fonts/msyh6_31.ttc`
- `browser/fonts/msyi6_00.ttf`
- `browser/fonts/mvboli6_85.ttf`
- `browser/fonts/ntailu5_99.ttf`
- `browser/fonts/ntailub5_99.ttf`
- `browser/fonts/pala5_03.ttf`
- `browser/fonts/palab5_03.ttf`
- `browser/fonts/palabi5_03.ttf`
- `browser/fonts/palai5_03.ttf`
- `browser/fonts/phagspa6_00.ttf`
- `browser/fonts/phagspab6_00.ttf`
- `browser/fonts/segmdl21_86.ttf`
- `browser/fonts/segoeicons1_44.ttf`
- `browser/fonts/segoepr5_04.ttf`
- `browser/fonts/segoeprb5_04.ttf`
- `browser/fonts/segoesc5_03.ttf`
- `browser/fonts/segoescb5_03.ttf`
- `browser/fonts/segoeui5_67.ttf`
- `browser/fonts/segoeuib5_67.ttf`
- `browser/fonts/segoeuii5_66.ttf`
- `browser/fonts/segoeuil.ttf`
- `browser/fonts/segoeuisl.ttf`
- `browser/fonts/segoeuiz5_66.ttf`
- `browser/fonts/seguiemj1_60.ttf`
- `browser/fonts/seguihis1_09.ttf`
- `browser/fonts/seguisym6_24.ttf`
- `browser/fonts/seguivar2_03.ttf`
- `browser/fonts/simsun.ttc`
- `browser/fonts/simsunb5_08.ttf`
- `browser/fonts/sylfaen5_08.ttf`
- `browser/fonts/symbol5_01.ttf`
- `browser/fonts/tahoma7_04.ttf`
- `browser/fonts/tahomabd7_04.ttf`
- `browser/fonts/taile6_00.ttf`
- `browser/fonts/taileb6_00.ttf`
- `browser/fonts/times7_11.ttf`
- `browser/fonts/timesbd7_11.ttf`
- `browser/fonts/timesbi7_11.ttf`
- `browser/fonts/timesi7_11.ttf`
- `browser/fonts/trebuc5_15.ttf`
- `browser/fonts/trebucbd5_15.ttf`
- `browser/fonts/trebucbi5_15.ttf`
- `browser/fonts/trebucit5_15.ttf`
- `browser/fonts/verdana5_33.ttf`
- `browser/fonts/verdanab5_33.ttf`
- `browser/fonts/verdanai5_33.ttf`
- `browser/fonts/verdanaz5_33.ttf`
- `browser/fonts/webdings5_01.ttf`
- `browser/fonts/wingding5_01.ttf`
- `browser/fonts/yugothm1_95.ttc`
- `gfx/tests/gtest/TestStealthBundleHooks.h`
- `gfx/thebes/StealthBundleFontList.cpp`
- `gfx/thebes/StealthBundleFontList.h`
- `gfx/thebes/StealthBundleFontList.mozbuild`
- `gfx/thebes/StealthDWriteFontList.cpp`

## Why StealthBundleFontList.h is exported

StealthBundleFontList.h is exported because dom/canvas reads the coverage ladder from it (the alpha-quantisation hook in CanvasRenderingContext2D).




## gfx/thebes/FontData.h: the Borrowed constructor

Hooks: the `Borrowed` enum and constructor, the `mBorrowed` member, `StealthFontDataOwned` and the destructor that
frees only what it owns. Until 2026-10-29 the borrow lived in `FTUserFontData` (gfx/2d/2D.h, a constructor tagged
`Prestito`) with a second branch in its `CloneFace` (gfx/2d/Factory.cpp). Firefox 159 removes `FTUserFontData`, and
those two hooks were the largest conflict of the 157 -> 159 merge (94 of our lines); `FontData.h` is unchanged across
those releases. Mozilla's `CloneFace` opens a FontData with the same `FT_New_Memory_Face` on the same bytes and
selects the charmap, so the faces are the same.

The comment that stood on the constructor, kept unchanged:

STEALTH: the bytes belong to SOMEONE ELSE and must not be freed here.

Symmetric to the borrowing constructor of `gfxDWriteFontFileStream`: on BOTH platforms a single mapping per FILE is
lent to all the faces of that file, instead of one copy per face. The loan is safe for the same reason as there: the
cache of `StealthBundleFontList` is immortal by construction - the object is deliberately leaked and never empties
`mFileCache` - and the value of the map is a `RefPtr`, so if the hash table reallocates, it is the pointer that
moves and never the bytes.

The destructor of Mozilla's class calls `free()` on what `StealthFontDataOwned` returns: null for a borrowed
FontData (a no-op), the pointer for an owning one. The `friend` gives the function access to `mBorrowed`; it is
found by argument-dependent lookup inside the destructor. `mBorrowed` sits after `mData` and before `mLength`, and
Mozilla's constructor leaves it at its default (false).

## gfx/2d/ScaledFontDWrite.cpp: UnscaledFontDWrite::GetFontDescriptor

Hook: the guard `StealthGetSeededDescriptor` as the first statement. The comment that stood on the old block,
moved here:

STEALTH: if the path is DECLARED, use it and skip the rest.

The `!mFont` guard that follows, in `GetFontDescriptor`, is a PROXY: "it is not a system font" stands for "it has
no file", and the comment at the construction site says so explicitly ("this signals whether or not we can safely
query a descriptor"). For a font downloaded by a page this is correct, because there a file does not exist. For
our bundled faces it is false: the file exists and we know it, and keeping silent about it makes WebRender receive
the BYTES of the font instead of the path. Measured 65.9 MB in the parent process on Linux, where the same
correction was made first - known bug B154.

We do not go through `GetFontFileName` because it requires an `IDWriteLocalFontFileLoader`, and our loader lends
bytes in memory: it is not local and never will be. The byte convention is the same one it uses, null terminator
included (`mFontFileName` is its place).

## gfx/2d/UnscaledFontDWrite.h: the seeded file name

Hooks: `StealthSeedFilePath` (called by `StealthWithBundlePath`, fingerprint/fonts/font-list, on the object Mozilla
just built in `gfxDWriteFontEntry::CreateFontInstance`) and `StealthGetSeededDescriptor`, both defined in
StealthDWriteFontList.cpp, plus the `<string>` include. Until now the path was a third constructor argument and a
member `mPercorsoDichiarato`; it now goes into `mFontFileName`, which is where Mozilla keeps the file name (path plus
terminator), so the descriptor callback gets the same bytes. Mozilla's two-argument constructor is back, so
`ScaledFontDWrite.cpp` and `Moz2DImageRenderer.cpp` bind to it as in the tag. The comment that stood on the old
constructor, moved here:

STEALTH: `aFilePath` is the file this face comes from, when there is one.

It is needed because `GetFontDescriptor` cannot work it out by itself for our faces: that path goes through
`IDWriteLocalFontFileLoader`, and our loader lends bytes in memory, so it is not local. Without the path Gecko falls
back to sending the BYTES of the font to WebRender - measured 65.9 MB in the parent process on Linux, where the same
defect was corrected first. See known bug B154.

Whoever does not pass a path sees no difference: the upstream behaviour stays, which for a font downloaded by a page
is the right one because there a file does not really exist.

## Windows: the DirectWrite stream lends through FontData

Until 2026-10-30 gfxDWriteCommon.cpp and .h carried a second kind of
`gfxDWriteFontFileStream` that held lent bytes instead of a FontData (a
`Borrowed` constructor, `Bytes()` / `BytesLength()` in `GetFileSize` and
`ReadFileFragment`, and `CreateBorrowedFontFile`), and the body of
`CreateCustomFontFile` with its static stream registry had moved into a file of
ours: 36 of Mozilla's lines removed or rewritten in one file. It predates the
Borrowed constructor of FontData. Now `CreateStealthBundleFontEntry`
(StealthDWriteFontList.cpp) wraps the cache's bytes in a borrowed FontData and
calls Mozilla's `CreateCustomFontFile`, so both files are Mozilla's again; one
copy of each file still serves every face.

`gfxDWriteFontFileStream::SizeOfExcludingThis` reports 0 for every stream
(Mozilla's comment: "We don't report the size of mData, because the original
user font entry will account for that"). For a lent FontData that is also
right: the bundle cache is where those bytes belong and where they are
reported, and counting them again would double-count them in about:memory.


## gfx/thebes/gfxDWriteFontList.h: gfxDWriteFontEntry::mBundleFaceIndex and mBundleFilePath

Hook: the two members (and the `<string>` include). The comments that stood on them
in gfxDWriteFontList.h, moved here unchanged:

mBundleFaceIndex: Face index within a custom (bundle) font file; 0 for single-face files and
for system fonts. Lets a .ttc face be addressed by index in CreateFontFace.

mBundleFilePath: Bundle file path; see StealthDWriteFontList.cpp (CreateFontInstance).


## gfx/thebes/gfxFontEntry.h: gfxFontEntry::AutoHBFace conversion operator (declared exception)

Hook: `operator hb_face_t*() const&` and the deleted `operator hb_face_t*() const&&` (feature hb-face-lifetime).
It is a change of the type of a Mozilla class, not a hook, and no form expresses it (a lone `const&& = delete` next to
Mozilla's unqualified operator is ill-formed), so the two lines stay as they are, as a declared exception approved
by the owner (G35, G24). The consequence is in fingerprint/fonts/font-list: `gfxFontconfigFontEntry::GetHBFace` and
`GetFontTableInternal` cannot keep Mozilla's `hb_face_reference(gfxFontEntry::GetHBFace())` and
`hb_face_reference_table(GetHBFace(), ...)`, which bind the temporary, so two lines there are rewritten
(`StealthBaseHBFaceRef`, `StealthHBFaceTable`).

Where it comes from: commit 098cf5f777 (fingerprint/fonts/bundle, 2026-10-05) introduced it (found with `git log -S`),
after the one wrong caller of fourteen, `gfxHarfBuzzShaper::GetDesignFont`, left a dangling pointer. The comment
that stood on it, moved here unchanged:

The conversion is valid only on an LVALUE. Binding to a temporary is forbidden by the TYPE, not by a convention:

        hb_face_t* f = entry->GetHBFace();   // does not compile
        const auto f(entry->GetHBFace());    // correct

GetHBFace() returns by value, so when the first form is written the temporary is converted and destroyed at the end
of that same statement: the pointer dangles from the next line, and whoever uses it writes into freed memory.
Measured on 2026-08-10 on gfxHarfBuzzShaper::GetDesignFont(), which was the only one of the fourteen callers to get
it wrong: 6 browsing sessions out of 10 died, against 0 after the correction. The defect was silent because freshly
freed memory almost always stays readable, and the segmentation fault arrived elsewhere and much later.

It lives in the TYPE and not only in a gate because the project already knew the rule at thirteen points out of
fourteen and the fourteenth was written wrong all the same: here the compiler rejects it.

## gfx/thebes/gfxFontEntry.h: gfxFontEntry::ShouldPublishCharacterMap declaration

Hook: the declaration `bool ShouldPublishCharacterMap() const;`, defined in StealthBundleFontList.cpp (it forwards to
`StealthBundleFontList::ShouldPublishCharacterMap`, which answers `mShmemFace && StealthPublishCharacterMap(...)`, the rule
of fingerprint/fonts/font-list). The hooks of the back ends no longer call it: `ReadCMAP` calls
`StealthPublishCharacterMap(this, !IsUserFont())`, so the member is a candidate to remove in a separate decision (G24). The
comment that stood on the declaration, moved here unchanged:

Stealth: does this entry's character map belong in the shared font list? Every backend's ReadCMAP asked
`!IsUserFont() && mShmemFace`, four copies of one rule, and that rule is WRONG for a bundled face: it is constructed
from file data (so IsUserFont() is true) while being one of the list's own faces. The consequence was that no bundled
face's cmap ever reached shared memory. One predicate, four readers.

## gfx/thebes/gfxFontUtils: the face index of a .ttc

Hooks: `StealthSfntHeader` (the wrap in Mozilla's `FindTableDirEntry`) and the three members. A collection's table
lookup reads the sfnt header of the requested face; table offsets are relative to the start of the file in every face,
so the blob of `GetTableFromFontData` is made from the file start and the entry's offset. `StealthSfntHeader` returns
the header it was given for a single-face sfnt, the header of face 0 for a collection, and an empty header
(numTables 0, so nothing is found) for a collection that lists no face. The three-argument forms call
`FindSfntOffset` and then Mozilla's two-argument function on the face header. In gfxFontUtils.h we had edited
Mozilla's doc comments of the two functions; Mozilla's wording is restored there and our version is kept here:

FindTableDirEntry: find the table directory entry for a given table tag, in a (validated) buffer of font data
(single-face sfnt or .ttc collection). aFaceIndex selects the face within a .ttc (ignored for single-face fonts).
Returns null if the tag is not present.

GetTableFromFontData: return a blob that wraps a table found within a buffer of font data (single-face sfnt or .ttc
collection). aFaceIndex selects the face within a .ttc (ignored for single-face fonts). Table offsets are relative to
the beginning of the file, so the blob points into aFontData. The blob does NOT own its data; caller guarantees that
the buffer will remain valid at least as long as the blob. Returns null if the specified table is not found. This
method assumes aFontData is valid font data; before using this, caller is responsible to do any sanitization/validation
necessary.

## gfx/thebes/gfxTextRun.cpp: gfxFontGroup::FindFallbackFaceForChar

Hook: the middle operand of the three-part async-fallback condition goes through `StealthFallbackMayDefer`, which
answers `aAsyncPref && !bundleOnly`. `GlobalFontFallback` (fingerprint/fonts/font-list) asks the same predicate
(`StealthMayDeferCmapLoadingCore`), so both sites agree. The comment that stood on it:

Stealth: this is the site the bundle-only condition was missing from. The twin site in GlobalFontFallback spelled it
out by hand, this one (FindFallbackFaceForChar) did not, and under bundle-only NO family is ever fully initialized -
so every text run that needed a fallback face within a family took this early return in the content process.
`StealthFallbackMayDefer` is now the single answer for both. Measured 2026-08-07: the regional-indicator pair through
"Arial" gave 52.63 on both platforms when it was the first thing a fresh page measured and 63.53 (Windows) against 80.07
(Linux) after other families had been measured: the divergence was the load order.
