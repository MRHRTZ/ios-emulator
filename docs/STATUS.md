# Development status

Snapshot: 2026-10-21, dev/window-native.

**Checklist completion: 50/70 (71.4%).** Counted from the top-level checkboxes
in [TODO.md](../TODO.md). Items have equal weight; this is bookkeeping, not a
compatibility score or release-readiness measure. Deferred work remains counted.

## Verified

- Real iOS 16.7.16 SpringBoard and interactive Home on native Windows QEMU.
- Touch/drag scroll, side buttons, on-screen keyboard, physical PC typing and
  Backspace. Host ASCII clipboard paste produced `Ab9!`; the following physical
  E produced lowercase e, confirming modifier release for that paste.
- Dark spinner/buttons, resource dropdowns, compact status bar and native theme
  controls. Current GUI cap is four CPUs: the PC kernel rejects higher counts.
- Kernel0092 presentation metadata skips unchanged/in-flight frame exports.
  Host capture and guest presentation diagnostics are separate. A static screen
  can show 0 capture FPS. This is not GPU acceleration or a guaranteed motion gain.
- Two-core kernel0093 boot reached Home without manual Home/Power. After a
  roughly 107-second pause, UTC lag fell from107 seconds to about1 second on
  resume; the visible clock subsequently caught up and Settings remained usable.
- Four-core real Home; unavailable Photos widget placeholders removed. Settings
  rendered complete pages and actual mouse drags scrolled them after launch wait.
- Host UTC RTC, virtio disk/persistent-overlay lock, IPv6 DNS/TLS/HTTP receipt,
  and kernel0090 IPv4 DHCP/default route (10.0.2.15 via10.0.2.2).
- Pinned requirements installed in a local Python3.12 venv; pip check and50 host
  tests pass. Clean Windows CI39505871568 passed48 tests at7f4e079; newer source
  includes additional resource-limit and unlock-retry tests.
- [Actual Windows/Home screenshot and its limitations](SCREENSHOTS.md).

## In progress

- Bounded automatic-unlock retry on four-core fresh boot. The first0094 run
  still needed manual Home; the new retry source needs runtime validation.
- Four-core pause/RTC validation and kernel0094 orderly shutdown, followed by
  a read-only filesystem check. Successful compilation alone is not completion.
- Default wallpaper through the actual guest PosterBoard path; no host overlay.
- Motion latency under different capture targets and host/guest workload.

## Still missing or deferred

Safari page drawing is unresolved and testing is deferred by the user. Some
Settings launches are delayed or initially black. Default wallpaper, guest GPU
acceleration, non-ASCII IME, held-key focus-loss runtime testing and general app
compatibility remain incomplete. More than four QEMU CPUs are not exposed by
this GUI. Native APFS preparation and application packaging remain deferred.

See [architecture](ARCHITECTURE.md), [graphics plan](GRAPHICS.md),
[Safari investigation](SAFARI_RENDERING.md) and [engineering handoff](../NOTES.md)
for evidence and open work.
