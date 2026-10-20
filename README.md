# ios-emulator

An experimental educational and research project running real iOS userland on a patched open-source XNU kernel under QEMU. Native Windows development is on **dev/window-native**; this main branch retains the cross-platform QEMU and original phone-port baseline.

This independent project is not affiliated with, endorsed by, sponsored by, or developed in cooperation with Apple Inc. Apple, iPhone and iOS are trademarks of Apple Inc. Apple firmware and filesystem images are downloaded separately and are not included in this repository. Third-party components retain their own licenses.

## Windows development

Use the [dev/window-native branch](https://github.com/MRHRTZ/ios-emulator/tree/dev/window-native) for the Python CLI and desktop GUI. Follow its [Windows setup](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/docs/WINDOWS.md) and [README](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/README.md), including installation from requirements.txt.

Real iOS 16.7.16 / iPhone X SpringBoard, touch input, host UTC, multicore boot and network traffic have been observed under Windows QEMU. Safari can receive HTML but page content remains blank. GPU acceleration, application compatibility, responsiveness, native APFS preparation and bundling remain unfinished. A high display refresh target does not guarantee a high guest frame rate.

See the [development checklist](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/TODO.md) and [verified status](https://github.com/MRHRTZ/ios-emulator/blob/dev/window-native/docs/STATUS.md) for evidence and pending validation.

Branch policy: **dev/window-native** for active Windows development; **window-native** for a separate Windows release promotion; **main** for the stable cross-platform baseline. Availability of development features does not imply they have been released on main.

## Original phone port

The [original Redmi Note 10 Pro port documentation](docs/PHONE_PORT_REFERENCE.md) is preserved as historical hardware-specific reference. Its phone installation instructions and performance figures do not describe the Windows emulator.
