# Current Python environment

From the repository root in PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
$env:PYTHONPATH = "tools"
$env:QT_QPA_PLATFORM = "offscreen"
.\venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:QT_QPA_PLATFORM
.\venv\Scripts\python.exe emulator.py doctor
.\venv\Scripts\python.exe emulator.py gui
```

The pinned requirements include the desktop GUI, LZFSE decoder and root-helper
ISO writer. The CLI's basic download/inspect commands use Python's standard
library. QEMU and LLVM remain separate native dependencies. The ignored venv
is local and is never uploaded.

The **Windows host tests** GitHub Actions workflow repeats dependency installation,
`pip check`, Qt/host regressions and entry-point compilation on a clean Windows
runner without Apple firmware. This tests Python setup and host behavior; it does
not establish successful guest boot or replace QEMU/runtime testing.

The sections below preserve the earlier kernel bring-up baseline. Use
[STATUS.md](STATUS.md) and [TODO.md](../TODO.md) for current guest evidence.

---

For the current Python CLI and the newer PID 1/firmware milestones, see [CLI.md](CLI.md) and [../TODO.md](../TODO.md). The commands and first-boot observations below are the earlier bring-up baseline.

# Windows native setup

This fork targets PC emulation. The first milestone is ARM64 XNU bring-up on
QEMU `virt`, not a complete iPhone simulator.

## Dependencies

- Windows x64, Python 3.12, and QEMU with `qemu-system-aarch64.exe`.
- LLVM `llvm-nm` for matching kernel font extraction and framebuffer decoding.
- No Python packages are required by the runner.
- QEMU installer: https://qemu.weilnetz.de/w64/

The tested local QEMU is 11.1.0 at `G:\Software\qemu`. The runner discovers
the installer location through the Windows uninstall registry, checks PATH,
and supports `QEMU_AARCH64` or explicit `--qemu` selection.

ARM64 guests on this x64 host use software TCG. WSL, Docker, and Hyper-V are
not needed for this test. Full kernel builds still use the existing macOS CI.

## Check the installation

Run these from the repository root in PowerShell:

```powershell
python tools/qemu-sweet.py --check-env
python tools/check-windows-qemu.py
```

The second command runs a tiny ARM64 program (sets x0 to 42), checks the
register via loopback QMP, and verifies a memory export. Its temporary paths
include spaces and a comma. It does not boot XNU or iOS.

If automatic discovery fails:

```powershell
python tools/qemu-sweet.py --check-env --qemu "G:\Software\qemu\qemu-system-aarch64.exe"
```

## Kernel smoke boot

Place the unstripped `kernel.development.sweet` and its checksum file in
`xnu/out/`. A kernel is not included in Git. The local baseline downloaded on
2026-10-20 came from:

- Repository: `dipa-studio/ios-sweet`
- GitHub Actions artifact: `xnu-kernel`, ID `12147422947`
- Artifact created: `2026-10-18T19:25:42Z`
- Actions run: `39158169212`, source commit `fdad0de8dc0e75c5ea84762adc03f7232dc91f19`
- SHA-256: `d9cb893bd2baf841e94cd2001f0ec70c0fea42f045f87f14ae807e4ebc50e1e5`

The downloaded kernel matches the artifact's `SHA256SUMS`. Artifact downloads
require GitHub authentication and artifacts can expire; this is a development
baseline, not a permanent release. The fork also has `.github/workflows/xnu.yml`
to build a replacement on a macOS runner.

```powershell
New-Item -ItemType Directory -Force research/windows-smoke | Out-Null
python tools/mkadt.py research/windows-smoke/qemu.adt --qemu
python tools/mkpayload.py xnu/out/kernel.development.sweet research/windows-smoke/qemu.adt research/windows-smoke/payload.bin --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0"
python tools/qemu-sweet.py research/windows-smoke/payload.bin research/windows-smoke/run --secs 45 --kernel xnu/out/kernel.development.sweet --fail-on-panic
```

The generated ADT warns about missing `research/ipsw-x/d22ap.adt`. Early
kernel tests can proceed without its iPhone `/product` metadata; real iOS
userland will need it. `rd=md0` does not create a root disk. Without a root
image this command only exercises early kernel initialization.

Outputs include `fb.png`, `fb.txt`, `regs.txt`, `qemu.log`, and `result.json`.
The framebuffer is a static snapshot, not a live interactive iOS window.
A nonblank screen or `no_panic_observed` does not prove successful OS boot.
`--fail-on-panic` returns 2 for visible panic, 3 for incomplete/blank decoding,
and 1 if QEMU exits early. The image and logs must be inspected as well.

## Observed result on 2026-10-20

- Dependency check and the real ARM64/QMP/memory-export probe passed.
- The first 20-second kernel snapshot reached IOKit/framebuffer initialization,
  but decoding was incomplete (62 unknown glyphs).
- The 45-second run with `-noprogress` decoded with zero unknown glyphs.
  It reached BSD initialization and the root-device lookup, then panicked:
  `IOFindBSDRoot: specified root memory device, md0, has not been configured`.
- The runner correctly classified that snapshot as `panic`. This is an early
  kernel boot with a known missing-root blocker, not an iOS userspace boot.
- Local output: `research/windows-smoke/run-noprogress/` (ignored by Git).

## Work still required

1. Obtain/build a test RAM-disk root and pass it to `mkpayload.py --ramdisk`,
   with `rd=md0` in the command line, to test userspace.
2. Extract the iPhone X 16.7.16 (20H392) userland from the Apple IPSW when
   moving to real iOS. The IPSW is not directly bootable by QEMU.
3. Design a persistent virtual storage path. QEMU `virt` does not emulate
   the Redmi Qualcomm UFS controller; attaching a disk alone is insufficient.
4. Implement/bridge PC keyboard and mouse input and a live display frontend.
   The existing drivers target phone hardware and the current runner only
   saves framebuffer snapshots.

Original hardware-port instructions are archived in `PHONE_PORT_REFERENCE.md`.
Do not use its phone flashing procedure for this PC emulator.
