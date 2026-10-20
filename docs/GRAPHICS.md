# Graphics development plan

User-requested settings: Auto, Software, Vulkan, OpenGL. Work belongs on
`dev/window-native`; packaging remains a later milestone.

## Current verified path

The iOS CoreAnimation software compositor writes IOSurfaces. SweetFramebuffer
copies the final BGRA surface into guest RAM; the Python/Qt frontend exports
and presents that framebuffer. There is no guest GPU acceleration in this path.
Safari UI renders, but webpage content remained white even after real HTTP 200
and HTML arrival. A backed-up Safari preference experiment disables
`WebKitDebugAcceleratedDrawingEnabled`; its outcome still needs visual testing.

The installed Windows QEMU 11.1.0 lists `virtio-gpu-gl-device` and
`virtio-gpu-gl-pci`. Device help lists `blob`, `hostmem`, and `venus`.
These are build capabilities, not proof of a usable Windows GPU backend or
an iOS driver. Existing emulated iOS services do not expose IOAcceleratorES.

## Integration order

1. Fix and verify baseline Safari software drawing with a simple webpage.
2. Probe host OpenGL/Vulkan backend creation and GPU/driver capabilities using
   a disposable QEMU test; do not attach the persistent iOS disk for probes.
3. Implement a guest-compatible graphics service/transport and surface sharing.
   iOS Metal/CoreAnimation/IOAccelerator interfaces must be served or translated;
   adding a Linux virtio-gpu device alone does not supply that implementation.
4. Implement host OpenGL/Vulkan rendering and synchronization. A Qt GPU-backed
   presentation widget accelerates host display only; report it separately from
   guest graphics acceleration.
5. Expose English native settings with capability checks, an actual selected
   backend in diagnostics, and a clear unavailable reason. Auto must fall back
   to verified Software. Do not silently accept a renderer and ignore it.
6. Verify webpage pixels, touch, rotation, resize, pause/resume, resource cleanup,
   and useful performance before enabling each accelerated option.

Reference: https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html
The documented VirGL/Venus paths have host and guest driver requirements; the
published Linux combinations do not establish iOS-on-Windows compatibility.
