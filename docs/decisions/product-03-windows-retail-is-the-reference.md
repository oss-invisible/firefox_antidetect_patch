# product-03: Windows retail is the reference

**Rule.** The reference is retail Firefox on Windows. On Windows the series stays on the retail path, made fixed. Linux converges to Windows, never the reverse. Making the hosts uniform with something that no Windows produces (for example FreeType or llvmpipe on Windows) is forbidden.

The wrapper's host gate measures this rule together with [product-01](product-01-no-value-from-the-host.md) and [product-02](product-02-same-seed-same-bytes.md): every difference between hosts is a leak, and so is every difference from retail. The only exceptions are noise, network inputs and known defects, each with the work that closes it.

**Why.** The aim is to be indistinguishable from any retail Firefox on any plausible Windows, installed on any possible machine. A value that no Windows produces is distinguishable from every real user, even if it is the same on all our hosts: uniformity through a third implementation trades a difference between hosts for a difference from the retail.

**Files.** The folders under `fingerprint/` and `platform/`; values pinned to the retail are measured again at each port ([port-02](port-02-stable-retail-of-the-target.md)).

**Don't.**
- Bring a Linux library to Windows to make the two agree.
- Take a value from the Windows host of one development machine as if it were the reference.
- Accept a difference from retail as "noise" without the work that closes it.
