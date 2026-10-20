# ios-emulator

An **experimental, educational and research project** exploring real iOS
userspace on a patched open-source XNU kernel under QEMU. Native Windows x64
is the current development target. This is an incomplete emulator with known
compatibility and performance limits.

This independent project is **not affiliated with, endorsed by, sponsored by,
or developed in cooperation with Apple Inc.** Apple, iPhone, iOS and related
names are trademarks of their respective owners. Apple firmware and filesystem
images are downloaded separately and are not included in this repository.
Third-party components retain their own licenses.

## Observed status

- Real iOS 16.7.16 / iPhone X SpringBoard home screen, touch, side buttons and
  on-screen keyboard have been observed on native Windows QEMU.
- Host UTC clock, 2/4-core boot, virtio block storage, IPv6 DNS/TLS/HTTP, and
  IPv4 DHCP/default route have been verified in recorded tests.
- Safari can receive real HTML while displaying a **white content area**.
  Settings, wallpaper and widgets also have rendering/service gaps.
- PC keyboard support is in development; GPU acceleration, reliable app
  compatibility, native APFS preparation and application bundling are unfinished.

See [development status and checklist progress](docs/STATUS.md) for evidence
and pending checks. A booting kernel or a successful download is not a complete
iPhone implementation.

## Start on Windows

```powershell
python emulator.py doctor
python emulator.py download
python emulator.py inspect
python emulator.py extract
python emulator.py device-tree
python emulator.py probe-root
python emulator.py run --test
# Once a matching kernel and prepared root exist:
python -m pip install PySide6
python emulator.py gui
```

`run --test` runs a minimal custom PID 1, not Apple's userspace.
Root preparation and kernel requirements are explained in the setup guides.

## Documentation

- [Windows setup](docs/WINDOWS.md) and [CLI reference](docs/CLI.md)
- [Desktop UI, controls and settings](docs/GUI.md)
- [How the port works and integrated systems](docs/ARCHITECTURE.md)
- [Verified status, known issues and checklist percentage](docs/STATUS.md)
- [Full TODO list](TODO.md)
- [GPU / Vulkan / OpenGL integration plan](docs/GRAPHICS.md)
- [Screenshots and evidence requirements](docs/SCREENSHOTS.md)
- [Engineering checkpoint and history](NOTES.md)
- [Original phone-port reference](docs/PHONE_PORT_REFERENCE.md)

Development: **dev/window-native**. Windows releases: **window-native**.
Stable cross-platform QEMU: **main**. Development is not automatically promoted
to release/stable. Wrapper/installer comes after emulator validation.

- [Safari white-page investigation](docs/SAFARI_RENDERING.md)
