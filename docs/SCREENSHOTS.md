# Screenshots and evidence

All images below are actual native Windows application captures from 2026-10-21, with the transparent phone/orbit application icon. They show the development branch, not features promoted to main. No firmware, disk images or private account data are included.

## Home screen

![Native emulator Home with current icon](screenshots/windows-home.jpg)

Latest Home capture:kernel0095, four QEMU CPUs,4096 MiB iOS memory,15 capture target, NVIDIA OpenGL host presentation. Run20261021-105027-498100 reached Home without agent Home/Power input. The wallpaper trial still displays black. The Visual counter counts distinct images painted; idle0fps is expected and the target does not establish animation speed.

## Actual iOS identity

![Actual iOS About](screenshots/windows-ios-about.jpg)

![Actual iOS version and build](screenshots/windows-ios-version.jpg)

Settings → General → About identifies iPhone X, iOS16.7.16. Its version detail reports16.7.16(20H392). Captured from0094 run20261021-095720-287600. Model/serial numbers are N/A in this test system. This is userspace identity, not a claim of original iPhone hardware or full device compatibility.

## Host and emulated-system information

![Live system information](screenshots/windows-system-info.jpg)

Help → System Information shows Windows11 build26200, Intel i5-14400F,16 logical CPUs,31.8GiB visible RAM; iOS is allocated4 emulated ARM64 CPUs and4096MiB. It distinguishes visual changes, captured changes, iOS panel presentations, target and export latency. The capture selected Windows direct framebuffer reads. The idle/near-idle values in this screenshot are not a motion benchmark. See [performance evidence](PERFORMANCE.md).

## Dark emulator settings

![Current native dark settings](screenshots/windows-settings-dark.jpg)

Current icon, dropdown resource inputs, Auto/Software/OpenGL/Vulkan host renderer choices and readable OK/Cancel. The latest settings capture reports active NVIDIA RTX5070 OpenGL; Vulkan is unavailable until a presenter exists. CPU/memory can change while stopped; while running those controls are disabled and the capture target can change live.

These captures do not demonstrate iOS GPU acceleration, Safari webpage drawing or general application compatibility. Earlier two/four-core RTC pause/resume and clean shutdown evidence is recorded in NOTES.md. Firmware, network captures, full diagnostics and private iOS content stay outside Git. Apple and iOS names belong to their owners; this independent research project has no Apple affiliation.
