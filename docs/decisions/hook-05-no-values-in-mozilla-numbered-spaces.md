# hook-05: no values in Mozilla's numbered spaces

**Rule.** Our constants never take a value in a numbered space that Mozilla owns: flag bits, enums, IDL constants. They live in our own files, on values Mozilla leaves free, with a test that checks the value is still free. The contract tool flags a value of ours in an IDL constant or enum as rule C11.

**Why.** Mozilla assigns the next number of a space in a later release, and the merge does not report it: both sides add a line, in different places. In Firefox 159 bit 25 of `nsIWebBrowserChrome`, which was our flag, became Mozilla's `CHROME_MEDIA_PIP`, and the merge raised nothing. The test `explicit_size_flag_is_free.test.mjs` now fails when Mozilla takes the bit our flag uses.

**Files.** `automation/juggler/src/juggler/tests/explicit_size_flag_is_free.test.mjs` (named by the hooks of `automation/window-size` and `fingerprint/screen-window/popup-position`), `tools/hook_contract.py` (C11), the constants in our `Stealth*` files.

**Don't.**
- Add a constant to a Mozilla `.idl`, enum or flag list.
- Pick "the next free number" without a test that fails when it stops being free.
