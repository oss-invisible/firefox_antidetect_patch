# product-02: same seed, same bytes

**Rule.** The same seed gives the same bytes on every machine, on Windows x86_64 and on Linux x86_64: text, canvas, WebGL, audio and media. Different seeds are different machines that cannot be linked to each other; a value is the same across seeds only when it is the same across real users.

**Why.** A seed is an identity. If the host (a font library, a graphics driver, an audio stack, a codec) decides part of the bytes, the same identity looks different on two hosts, and the difference is a fingerprint of the host. The only way to make the output a function of the seed alone is to compute it in code of ours, or in Firefox's own code with the host's choices removed ([product-01](product-01-no-value-from-the-host.md)).

**Files.** `fingerprint/fonts/*` (text), `fingerprint/canvas/*`, `fingerprint/webgl/*`, `fingerprint/audio/*`, `fingerprint/media/*` and their tests (gtests under each folder's `src/`); the wrapper's host gate ([product-03](product-03-windows-retail-is-the-reference.md)).

**Don't.**
- Let an OS library (a shaper, a rasterizer, a codec, a driver) produce bytes that reach a page on one host and not on the other.
- Seed a value from the time, the process or the machine.
- Give two seeds the same value unless real users share it.
