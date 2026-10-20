# Development status

Snapshot: 2026-10-20, dev/window-native.

**Checklist completion: 41/62 (66.1%).** Counted from
top-level checkboxes in [TODO.md](../TODO.md). Every item has equal weight;
this percentage is bookkeeping, not a measure of iOS compatibility, stability
or release readiness. Deferred work remains in the denominator.

## Verified

- Native Windows QEMU execution of real Apple userspace and interactive home.
- Touch, consumer Home/Power/Volume path, on-screen keyboard.
- Unavailable Photos widget placeholders removed with guest IconState backup;
  clean Home visually verified. Settings displayed normally after launch wait.
- Host-current RTC; 2/4-core kernel smoke and four-core real home.
- Virtio root disk and persistent overlay lock.
- IPv6 DNS, remote TCP/TLS, example.com HTTP200 and decoded HTML receipt.
- Kernel0090 DHCP assigns10.0.2.15 and default route via10.0.2.2.
- Desktop regression suite: 33 tests pass, including immediate Stop clearing,
  keyboard capability guard, theme palette and topology through eight cores.

## In progress

- Kernel0091 USB HID keyboard:
  [CI39431335383](https://github.com/MRHRTZ/ios-emulator/actions/runs/39431335383)
  succeeded. Physical PC e and Return visibly reached Safari. Full held-key
  runtime cleanup and the new ASCII text-packet path still need verification.
- Revised native UI being visually checked in Light/Dark modes.
- Safari software-drawing preference experiment has backups; white webpage
  content remains unresolved. Actual HTML receipt does not prove rendering.

## Not yet working or validated

Safari webpage drawing; occasional Settings black content; default wallpaper;
guest GPU acceleration; 5–8-core runtime stability;
pause-time RTC behavior; orderly guest shutdown; IME text; general app support.
Native APFS preparation and installer/bundle are deferred.

See [architecture](ARCHITECTURE.md), [graphics plan](GRAPHICS.md) and
[engineering evidence/checkpoint](../NOTES.md) for details.

See [Safari rendering investigation](SAFARI_RENDERING.md) for evidence,
upstream reports and reversible preference experiments.
