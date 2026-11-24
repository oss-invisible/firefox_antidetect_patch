# port-03: the births ledger

**Rule.** Every place where the tree creates a network request (a channel, a socket transport, a UDP or TCP socket, a lookup, a speculative connection) is in `tools/birth-ledger.json` with a verdict that someone reviewed. `python tools/births.py --tree <dir>` scans a tree against the ledger; run it before the pull request. A new, changed or moved site is red until reviewed by hand.

Verdicts:
- `ok`: the context (proxy, resolver) is carried; `reason` names the argument.
- `hooked`: carried through a hook of ours; the `STEALTH-HOOK(<folder>)` must stay in the function, or at `hook_at`.
- `accepted`: carries no context and is either not caused by a page or the browser's own by design; `reason` says which (20+ characters).
- `dead`: never runs in the product; `proof` says why.
- `fix`: a known hole; needs `open` (since, item, owner). The scan exits 2 for it, which is red by design.

`series.yml` runs the scan on pull requests and pushes to main, after `materialize`; `engine.py port` runs it at the end. `--skeleton`, `--accept-changed` (after reading each diff) and `--prune` keep the ledger.

**Why.** A request a page causes but that is made with default attributes, the system principal or a plain socket leaves outside the proxy of its context. Each such hole was once found by hand at its call site. Closing the class means a Mozilla tag that adds a birth point, or changes the context handling around one, cannot pass unseen.

**Files.** `tools/births.py` (its docstring has the key of a site and the exit codes), `tools/birth-ledger.json`, `.github/workflows/series.yml` (job `rebuilds`).

**Don't.**
- Accept a changed site with `--accept-changed` without reading each diff.
- Mark a site `accepted` for a request a page can cause.
- Leave a `fix` open without its owner.
