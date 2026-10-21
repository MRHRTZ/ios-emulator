# ios-emulator

<img src="assets/app-icon.png" width="96" alt="Virtual device orbit project icon">

An experimental educational and research project running real iOS userland on a patched open-source XNU kernel under QEMU. Native Windows development is on **dev/window-native**; this main branch retains the cross-platform QEMU and original phone-port baseline.

This independent project is not affiliated with, endorsed by, sponsored by, or developed in cooperation with Apple Inc. Apple, iPhone and iOS are trademarks of Apple Inc. Apple firmware and filesystem images are downloaded separately and are not included in this repository. Third-party components retain their own licenses.

## Windows development

Use the [dev/window-native branch](https://github.com/MRHRTZ/ios-emulator/tree/dev/window-native) for the Python CLI and desktop GUI. Follow its [Windows setup](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/docs/WINDOWS.md) and [README](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/README.md), including installation from requirements.txt.

Real iOS 16.7.16 / iPhone X SpringBoard, touch input, host UTC, multicore boot and network traffic have been observed under Windows QEMU. Safari can receive HTML but page content remains blank. GPU acceleration, application compatibility, responsiveness, native APFS preparation and bundling remain unfinished. A high display refresh target does not guarantee a high guest frame rate.

See the [development checklist](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/docs/TODO.md) and [verified status](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/docs/STATUS.md) for evidence and pending validation.

Branch policy: **dev/window-native** for active Windows development; **window-native** for a separate Windows release promotion; **main** for the stable cross-platform baseline. Availability of development features does not imply they have been released on main.

## Windows development screenshots

Actual captures from **dev/window-native**; these development features are not released on main.

<img src="docs/screenshots/windows-home.jpg" width="270" alt="Latest native emulator Home screen with transparent orbit icon">
<img src="docs/screenshots/windows-ios-about.jpg" width="270" alt="Actual iOS About screen identifying iPhone X and iOS 16.7.16">
<img src="docs/screenshots/windows-ios-version.jpg" width="270" alt="Actual iOS version and build 16.7.16 20H392">

<img src="docs/screenshots/windows-system-info.jpg" width="600" alt="Windows host and emulated iOS system information with separate display measurements">

<img src="docs/screenshots/windows-settings-dark.jpg" width="330" alt="Updated native dark settings with readable dropdowns and buttons">

The host is Windows 11 on an Intel i5-14400F with 31.8 GiB visible RAM. This test allocates four emulated ARM64 CPUs and 4096 MiB to iOS. Real iOS Settings reports **iPhone X, iOS 16.7.16 (20H392)**. A capture target is not an animation frame rate: the UI still has substantial performance limits. See [capture conditions](docs/SCREENSHOTS.md) and [performance evidence](docs/PERFORMANCE.md).

## Original phone port

The [original Redmi Note 10 Pro port documentation](docs/PHONE_PORT_REFERENCE.md) is preserved as historical hardware-specific reference. Its phone installation instructions and performance figures do not describe the Windows emulator.
