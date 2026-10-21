# Development status

Snapshot: 2026-10-21, dev/window-native.

**Checklist completion: 58/76 (76.3%).** Counted from the top-level checkboxes
in [TODO.md](TODO.md). Items have equal weight; this is bookkeeping, not a
compatibility score or release-readiness measure. Deferred work remains counted.

## Verified

- Real iOS 16.7.16 SpringBoard and interactive Home on native Windows QEMU.
- Touch/drag scroll, side buttons, on-screen keyboard, physical PC typing and
  Backspace. Host ASCII clipboard paste produced `Ab9!`; the following physical
  E produced lowercase e, confirming modifier release for that paste.
- Dark spinner/buttons, resource dropdowns, compact status bar and native theme
  controls. Current GUI cap is four CPUs: the PC kernel rejects higher counts.
- Kernel0092 presentation metadata skips unchanged/in-flight frame exports.
  The status bar now counts distinct images actually painted. Identical images and
  repeated repaints do not inflate Visual FPS; idle screens show zero. System
  Information distinguishes visual/capture/presentation/target rates.
- Two-core kernel0093 boot reached Home without manual Home/Power. After a
  roughly 107-second pause, UTC lag fell from107 seconds to about1 second on
  resume; the visible clock subsequently caught up and Settings remained usable.
- Four-core real Home; unavailable Photos widget placeholders removed. Settings
  rendered complete pages and actual mouse drags scrolled them after launch wait.
- Four-core RTC resume also reduced about83 seconds of lag to under1 second;
  Settings responded and its clock caught up. Kernel0094 orderly shutdown stopped
  launchd, synced/unmounted HFS and powered QEMU off with exit0. A separate
  read-only helper found a clean HFS flag and fsck exit0 without repairs.
- Host UTC RTC, virtio disk/persistent-overlay lock, IPv6 DNS/TLS/HTTP receipt,
  and kernel0090 IPv4 DHCP/default route (10.0.2.15 via10.0.2.2).
- Transparent custom application icon and refreshed documentation captures.
- Windows direct capture passed byte-exact patterned-frame tests: median4.12ms
  versus34.47ms for QMP export. Real iOS exports around3.5–5.5ms; animation is
  still slow. See [performance measurements](PERFORMANCE.md).
- Four-core0094 fresh boot20261021-102412-800300 reached Home without manual
  Home/Power. The default-wallpaper trial still resulted in black wallpaper.
- Pinned Python dependencies;61 local host tests pass. Windows CI39541003669
  passed61 tests at0ef09ba. Native OpenGL presentation on RTX5070 passed pixel
  readback and Software/OpenGL roundtrip tests; iOS graphics remain software.
- [Actual Windows/Home screenshot and its limitations](SCREENSHOTS.md).

## In progress

- Default wallpaper through the actual guest PosterBoard path; no host overlay.
  A backed-up static-image default-asset trial is installed locally; fresh0094
  boot showed black wallpaper, so this is not complete.
- Low iOS motion rate: target60 scroll showed trailing visual up to2fps and
  panel presentations2.5/s. Target15 comparison was invalid (fast drag became
  tap); endpoint correction has a regression test and awaits runtime testing.
- Kernel0095 adds optional swap/vsync/work counters; local compile and
  CI39539338092 passed. Four-core Home boot and idle counters verified;
  controlled motion profiling remains pending. Translator work is planned separately.

## Still missing or deferred

Safari page drawing is unresolved and testing is deferred by the user. Some
Settings launches are delayed or initially black. Default wallpaper, guest GPU
acceleration, non-ASCII IME, held-key focus-loss runtime testing and general app
compatibility remain incomplete. More than four QEMU CPUs are not exposed by
this GUI. Native APFS preparation and application packaging remain deferred.

See [architecture](ARCHITECTURE.md), [graphics plan](GRAPHICS.md),
[Safari investigation](SAFARI_RENDERING.md) and [engineering handoff](NOTES.md)
for evidence and open work.
