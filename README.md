# ios-emulator

Experimental PC emulation of the XNU/iOS environment derived from `ios-sweet`.
The initial host target is **native Windows x64 with QEMU ARM64 emulation**.

The project runs **XNU plus a minimal test PID 1** on native Windows. Apple iOS userspace and an interactive desktop are still pending.
The source was originally built for a Redmi Note 10 Pro; hardware-specific
drivers and historical claims about phone boot do not establish PC support.

## Start on Windows

```powershell
python emulator.py doctor
python emulator.py download
python emulator.py inspect
python emulator.py extract
python emulator.py device-tree
python emulator.py probe-root
python emulator.py run --test
python emulator.py status
```

See [CLI commands](docs/CLI.md), [TODO list](TODO.md), and [Windows setup and boot commands](docs/WINDOWS.md) for dependencies,
kernel provenance, generated artifacts, limitations, and next steps.

The Windows runner supports automatic QEMU discovery, loopback TCP QMP,
Windows paths, TCG, and cleanup of the emulator after failures.

## What is included

- `tools/`: Python payload/ADT builders and the QEMU test runner.
- `xnu/patches/`: patches for Apple's open-source XNU kernel.
- `.github/workflows/xnu.yml`: macOS kernel build workflow.
- `shim/`: historical phone boot shim, not required by the host QEMU runner.
- `NOTES.md`: observations, handoff, and historical engineering notes.

Neither the kernel build artifact nor the iOS filesystem is tracked in Git.
iOS userland comes from Apple's iPhone X IPSW and requires extraction and
image preparation. Kernel smoke tests do not require that full firmware.

The original project's phone-specific README is preserved as
[historical reference](docs/PHONE_PORT_REFERENCE.md).
