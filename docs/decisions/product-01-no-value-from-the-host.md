# product-01: no value from the host

**Rule.** No value a page can read comes from the host. Each one is either declared by the core or computed by Firefox's own code. A host dependency is removed where Firefox reads the host: at the system call, the library or the driver. The value is never read from the host and then corrected, masked or given noise; it is declared, or computed by code of ours that is the same on every machine.

**Why.** Each seed is one plausible Windows machine, consistent with itself. A value read from the host and fixed afterwards still depends on the host in every case the fix does not cover, and those cases are the leaks. Removing the read at its birth leaves none. A second path that reads the same host downstream will disagree with the first.

**Files.** The folders under `fingerprint/` (one per surface); `platform/declaration-gate` (the host's graphics probe waits for the declaration); `stillborn/` (what is turned off at birth, [stillborn-01](stillborn-01-only-what-changes-the-installed-browser.md)); the prefs the core declares ([prefs-01](prefs-01-every-spoof-through-a-pref.md)); the birth points of network requests ([port-03](port-03-births-ledger.md)).

**Don't.**
- Read a value from the host and patch it afterwards.
- Add noise to a value to hide where it came from.
- Declare a value measured on one PC: it comes from the retail reference ([product-03](product-03-windows-retail-is-the-reference.md)).
