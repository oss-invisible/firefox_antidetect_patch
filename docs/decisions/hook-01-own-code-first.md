# hook-01: own code first

**Rule.** The logic lives in our own files, named `Stealth*` (`.cpp`, `.h`, `.mjs`, `.rs`) and registered in `layout.OWN_FILES`. A Mozilla file carries only hooks. Take the first rung of the ladder that gives the same result:
1. no Mozilla file: a pref Firefox already reads, a value declared by the core, a build option;
2. our own code, with one registration line;
3. a guard or a notice at the top of a function;
4. a wrap of a function or of an expression;
5. an anchor inside a function, only for a value Mozilla computes halfway.

Mozilla's logic is never copied into our files. Where a hook wraps or extends a Mozilla expression, the conflict at a port is the signal that Mozilla changed what we alter, and it is to be looked at.

**Why.** Every line in a Mozilla file can conflict at the next tag. A call into our own file is the smallest surface, and a copy of Mozilla's logic stops following Mozilla. Long comments belong in our file and in `FEATURE.md`; the hook line carries only the marker.

**Files.** `tools/layout.py` (`OWN_FILES`, `FEATURES`), `tools/inventory.json`, `<folder>/src/`; the rung table in [STRUCTURE.md](../STRUCTURE.md); the shape of a hook: [hook-02](hook-02-shape-and-contract.md).

**Don't.**
- Put logic, a comment or a constant in a Mozilla file.
- Copy a Mozilla function into a `Stealth*` file to change it.
- Take rung 5 when a guard or a wrap gives the same result.
