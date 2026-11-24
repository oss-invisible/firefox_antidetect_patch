# repo-02: no names of studied systems

**Rule.** No name of a detection system, fingerprinting service, test site or competing browser appears anywhere in the repository: not in code, comments, commit messages, pull request text, docs, test names or fixtures. Describe the check instead: what it reads, what it compares, which value it expects.

**Why.** The repository is public. A name ties the engine to one particular adversary and tells that adversary which of its checks we study; the description of the check is what an engineer needs to reproduce it and to write the test, and it stays true when the system changes its name or its code.

**Files.** Every file of the repository, the text of every commit and pull request. The same applies to the files that `export` copies from the source repository, so the source is the place to fix it ([series-01](series-01-export-is-the-only-writer.md)).

**Don't.**
- Name the system, service, site or browser, even in a comment or a test name, even as "similar to".
- Link to a page of such a system.
- Keep a fixture, a capture or a URL taken from one.
