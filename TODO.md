# Windows emulator TODO

Goal: working native Windows emulator with CLI and English desktop GUI; one bundled desktop app later. Python owns the
workflow. QEMU provides ARM64 emulation. Do not confuse the minimal test process
with Apple's launchd/SpringBoard.

## 1. Windows CLI baseline

- [x] Discover QEMU automatically and allow explicit executable selection.
- [x] Use loopback TCP QMP and Windows-compatible paths.
- [x] Execute ARM64 code and verify register/memory export on real QEMU.
- [x] Download a kernel build and verify its provenance/checksums.
- [x] CLI commands: doctor, download, inspect, extract, run, status.
- [x] Download with Python, progress %, speed, ETA, automatic retry and resume.
- [x] Check firmware size and SHA-256 before marking it ready.
- [x] Keep Apple firmware, generated images and runtime data out of Git.
- [ ] Provide a distributable kernel artifact with a stable release URL.

## 2. Boot a minimal userspace process

- [x] Build a static ARM64 test PID 1 using existing LLVM and Python tools.
- [x] Include the test executable as an md0 RAM disk in the payload.
- [x] Verify the console marker `SWEET userspace: init running as PID 1`.
- [x] Observe repeated `SWEET init: still alive` messages under Windows QEMU.
- [x] Stream the QEMU PL011 kernel/guest console to the host CLI (patch 0083).

## 3. Obtain iOS firmware

- [x] Finish latest compatible iPhone X IPSW download and SHA-256 validation.
- [x] Read BuildManifest and identify OS, SystemOS, AppOS and device tree.
- [x] Extract those components with CRC verification and progress.
- [x] Decode the iPhone device-tree `/product` metadata for real iOS userland.

`latest` means latest available **for iPhone X**, the kernel/userland baseline.
It does not mean the newest iOS for newer iPhones. Newer hardware generations
require separate compatibility work, including ARM64e/PAC and kernel ABI.

## 4. Boot real iOS userland (current major work)

- [x] Probe native UDIF/APFS reading with 7-Zip 26.04 and verify extracted
      ARM64 launchd/dyld samples; this does not produce a bootable root.
- [ ] Deferred by user: build a native Windows-capable APFS/UDIF extraction pipeline that handles
      LZBITMAP and preserves permissions, ownership, symlinks, hardlinks/xattrs.
- [x] Produce an HFS+ root containing OS and both cryptexes, dyld shared-cache
      links and required initial configuration using Python and a temporary
      QEMU Linux helper. Root passed repair/check; 11.67 GiB used of 16 GiB.
- [x] Implement a polled modern virtio-mmio block driver and per-run qcow2
      overlays for disk boot. Full 16 GiB root mounted read/write in Windows QEMU.
- [x] Keep the full root on a virtual disk; only kernel-managed RAM is placed
      in guest memory (default 2048 MiB). Small test RAM roots remain supported.
- [x] Start Apple's dyld and launchd; early boot complete confirmed in serial,
      xpcproxy/SpringBoard/backboardd executed. Record remaining daemon failures.
- [x] Bring up backboardd/SpringBoard and verify a real home screen.
- [x] Add keyboard/mouse/touch-event input bridging and live display output.
- [x] Reuse guest changes in the GUI persistent overlay.
- [ ] Implement orderly iOS shutdown (current Stop is a QEMU power cut).
- [x] Supply QEMU PL031 host UTC clock; Apple logs show current date.
- [x] Adapt Aff0 MPIDRs / HVC PSCI; 2/4 CPU test userspace and SGI verified.
- [ ] Validate 2/4-core GUI responsiveness and clock across Pause/Resume.
- [x] Verify IPv6 DNS, remote TLS and actual HTTP 200/HTML arrival in Safari.
- [ ] Verify IPv4 DHCP and route with BPF-enabled kernel0090.
- [ ] Fix Safari/WebKit blank content despite successful HTML receipt.
- [ ] Integrate a guest-compatible GPU/graphics transport and Windows renderer.
- [ ] Add graphics settings: Auto, Software, Vulkan, OpenGL. Expose accelerated
      choices only once an actual backend works; host presentation alone does
      not supply the iOS Metal/IOAccelerator driver path.
- [ ] Validate rendered webpages and graphics with each supported backend.

Installing QEMU and downloading an IPSW do not complete these tasks. The CLI
must report missing prerequisites honestly, never label the test PID 1 as iOS.

## 5. Reliability

- [x] Prevent two GUI sessions from writing the same overlay.
- [ ] Broader pipeline/download concurrency (deferred).
- [x] GUI CPU/RAM/refresh settings, bounds, and English failure messages.
- [x] English icon sidebar, hover labels, no touch-area tooltip.
- [x] Cover topology/RTC, ring backpressure/wrap, coordinates and GUI labels in host tests.
- [ ] Extend regression coverage for extraction, malformed manifests and cleanup.
- [ ] Add a reproducible clean-Windows setup test.

## 6. Single-app wrapper (after CLI works with real iOS)

- [ ] Move CLI actions into reusable Python services for the wrapper.
- [ ] Define QEMU/resource discovery relative to an installed application.
- [ ] Bundle Python runtime, QEMU and required resources in one installer/app.
- [ ] Keep firmware downloaded separately; do not bundle Apple's IPSW.
- [x] Add GUI progress, display/input, start/stop and diagnostics.
- [ ] Test licenses, upgrades and code signing for the packaged application.

## Branch policy

- Development Windows: `dev/window-native`.
- Windows publish: `window-native`, promoted only as a release step.
- Stable cross-platform QEMU: `main`.
- APFS pipeline and application wrapper/bundling remain deferred.
