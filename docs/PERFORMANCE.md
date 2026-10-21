# UI performance investigation — 2026-10-21

Host means the Windows computer. Guest means the iOS operating system running inside QEMU.

## Why the UI is still slow

The current command runs ARM64 Cortex-A76 code with `-accel tcg` on an Intel i5-14400F Windows 11 computer. TCG translates CPU instructions in software. iOS CoreAnimation uses a software compositor; the RTX 5070 is not connected to an implemented iOS Metal/IOAccelerator driver. The framebuffer is 1080 x 2400 x 4 bytes (9.89 MiB).

The kernel's `sweetfb_hz=30` requests panel copies at about 30 Hz at best. The 60 Hz vsync timer rearms after its work, so software execution/copy overhead can reduce the actual rate further. The desktop capture target of 60 is a separate sampling limit and cannot create missing iOS animation frames. A Settings navigation sample recorded iOS panel presentation windows up to 5.42/s, with many idle intervals. This mixed navigation/idle trace is not a sustained animation benchmark.

There were also avoidable host costs. The earlier implementation exported a full frame through QMP `pmemsave` to a temporary file; actual iOS-run exports observed roughly 29–41 ms, with earlier samples reaching 54 ms. Input handling and capture use the same worker, so a long export also delays queued input. Rendering, software CPU execution and host transfer are separate costs; reducing one does not guarantee a smooth UI.

## Changes and measurements

The Windows frontend now resolves the fixed framebuffer mapping through QEMU's `gpa2hva`, validates both ends are contiguous, and reads only that frame with a read-only handle to its own child QEMU. If unavailable or a read fails, it closes the handle and falls back to QMP export. Kernel video sequence checks reject frames modified during the read. No guest GPU acceleration is claimed.

A disposable 128 MiB QEMU, with no iOS disk attached, loaded a known 10,368,000-byte pattern. All 30 QMP and 30 direct reads matched every byte:

| Transport | Median | 95th percentile |
| --- | ---: | ---: |
| QMP export plus file read | 34.47 ms | 39.28 ms |
| Windows direct framebuffer read | 4.12 ms | 4.97 ms |

The real iOS boot then selected direct reads and recorded a 3.68 ms export. This is transfer latency, **not 30/60 FPS animation evidence**. A separate shared-RAM-file probe was unavailable in this installed Windows QEMU (`memory-backend-file` object absent).

The status bar now reports **Visual**, counting distinct images actually painted over the trailing two seconds. Identical captured pixels and repaints of the same image do not inflate it; an idle screen decays to zero. Help → System Information separately reports visual changes, changed captures, iOS panel presentations (which can repeat pixels), target and transfer time. These are whole-frame changes, not per-element animation analysis or input-to-photon latency. Frames not captured cannot be counted.

CPU/memory changes require stopping iOS. The capture target can now change live in iOSEmu Settings, allowing comparison without restarting the guest.

## Remaining work

A native drag at target60 produced a long Settings scroll. Over the following ~8 seconds, the trailing-window visual counter peaked at2fps and iOS presentations at2.5/s; exported frames were3.51–5.46ms. This includes the end of the gesture and subsequent idle time, so it is a responsiveness sample, not a sustained-frame-rate average. A target15 attempt opened Calendar instead of scrolling and is invalid as a like-for-like scroll comparison. It exposed a fast-drag issue: a release inside the mouse-move throttle interval could omit the final down-position. The frontend now sends that position before releasing, with a regression test.

An8-second QEMU process-time observation while Settings/native preferences were open consumed about3.76 host CPU cores. This is high utilization, but does not distinguish compositor work, service restarts, scheduler work or emulated idle loops. Do not attribute all of it to graphics without more profiling.

Patch0095 adds optional QEMU-only counters outside the HID ring: submitted swaps, vsync callbacks, callback execution time and the panel-copy divisor. The frontend capability-detects them. Comparing these rates with panel presentations will distinguish low upstream submission from slow kernel timer/panel work. Local SweetFramebuffer.cpp cross-compile and kernel CI39539338092 passed. The0095 four-core boot reached Home; idle vsync measured~53–54.5Hz with~0.01ms callback work. Controlled motion profiling is still pending at the user-requested stop.

Record controlled repeated scrolling at several capture targets after the drag fix, separating idle time from motion. Check visual rate and input response with the direct path; profile iOS compositor/TCG time before attempting kernel-side graphics changes. A usable iOS graphics driver/translation backend remains substantial unfinished work. Safari testing stays deferred by the user.

References: [QEMU execution and accelerators](https://www.qemu.org/docs/master/system/introduction.html), [QEMU monitor and gpa2hva](https://www.qemu.org/docs/master/system/monitor).


## OpenGL host presentation

Auto/Software/OpenGL host presentation is implemented; native OpenGL reports NVIDIA RTX5070. Deterministic red/blue GPU framebuffer readback and a Software/OpenGL roundtrip passed. Vulkan presentation is unavailable. This changes how Windows displays the framebuffer, not the software iOS compositor. No iOS GPU translator has been implemented.61 host tests and Windows CI39541003669 passed.
