# stillborn-01: only what changes the installed browser

**Rule.** `stillborn/` holds what the engine turns off at birth: updates, telemetry, API keys, the security state sync. It turns off only what would change the installed browser or the host (an installed update, a scheduled task, a download, a request that leaves by the host's road). The requests a real Firefox makes stay, as retail sends them: same timer, same URL, same headers. What the engine refuses is what follows the answer, or what the core declares instead.

**Why.** A retail Firefox makes those requests, so removing one is a difference from retail ([product-03](product-03-windows-retail-is-the-reference.md)). A build that deleted the update programs never sent the startup check that retail sends. The present folder builds the updater as retail does, lets the check go out unchanged, and refuses the download, the offer and the Windows background task. The same line is drawn in the others: the telemetry ping at exit leaves by the session's road and never the host's; the three API keys are not engraved and come as prefs from the core; the intermediate certificates, CRLite filters and OneCRL revocations are not synced from the network but declared by the core and turned into cert_storage's files once.

**Files.** `stillborn/updater`, `stillborn/telemetry`, `stillborn/api-keys`, `stillborn/security-state` (each with `FEATURE.md`, `hooks.patch`, `HOOKS.json`, `src/`); the layer is listed in [STRUCTURE.md](../STRUCTURE.md).

**Don't.**
- Remove a request that retail makes only because the profile does not need the answer.
- Leave a path by which the answer changes the installed browser or the host.
- Add a folder here for something that is not turned off at birth: a changed value goes under `fingerprint/`, `network/` or `platform/`.
