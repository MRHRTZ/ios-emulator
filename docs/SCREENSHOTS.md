# Screenshots and evidence

![Native Windows emulator displaying the iOS Home screen](screenshots/windows-home.jpg)

Captured from the running application on 2026-10-21. This is the actual Qt
window and guest framebuffer, not a mockup. Kernel0094, four QEMU CPUs,
4096 MiB guest memory, 60 FPS capture target; kernel SHA-256:
`7604042b608b242b6f7cd400bb8aad6f1e68f2415987a21c510a443e944b56f6`.

This run required a manual Home swipe after its first automatic unlock attempt.
The bounded retry improvement was added afterward and needs a fresh boot test.
The black wallpaper remains a known limitation. A still screen can show 0 FPS
because unchanged guest frames are skipped; the capture target is not an
animation-speed guarantee. This image does not prove GPU acceleration, Safari
page rendering, or general application compatibility.

Kernel0093 reached Home automatically in a separate two-core run. Its roughly
107-second pause was followed by a successful RTC calendar correction; the
visible clock subsequently caught up. Exact runs are recorded in NOTES.md.

Firmware, disk images, network captures, diagnostic dumps and private guest
content remain outside Git. Documentation images show only the clean test
guest and emulator controls. Apple and iOS names remain their owners' trademarks;
this independent research project has no Apple affiliation.

## Dark emulator settings

![Actual native dark settings dialog](screenshots/windows-settings-dark.jpg)

Captured after the verified shutdown. All resource inputs are dropdowns; OK and
Cancel remain visible. The GUI exposes the current four-CPU kernel limit.
