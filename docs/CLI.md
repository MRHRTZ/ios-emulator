# Windows CLI

Run from `D:\Data\Apple\IOS\ios-emulator` in PowerShell. Python standard-library
code controls the workflow. The core CLI uses the standard library; device-tree
decompression additionally uses the small optional LZFSE decoder.

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

- `download`: latest firmware for iPhone X, not latest iOS for all iPhones.
  Shows percentage, MiB/s and ETA. Interrupted `.part` downloads resume on
  rerun. Size and SHA-256 must match the catalog before the file becomes ready.
- `inspect`: reads the local IPSW's BuildManifest to identify the exact OS,
  SystemOS/AppOS cryptex and D22AP device-tree members.
- `extract`: streams these members to `data/extracted/<build>/`, showing
  progress and verifying ZIP CRC. It does not extract the APFS filesystems.
- `device-tree`: decompresses and verifies the firmware's D22AP device tree,
  including `/product`. Optional decoder setup (local to this project):
  `python -m pip install --target data/python-deps lzfse==0.4.2.post1`.
- `probe-root`: optionally uses a recent 7-Zip to decode the OS UDIF layer,
  verify APFS, and extract/validate ARM64 `launchd` and `dyld` samples. This
  still does not create an HFS+ root disk. Local 7-Zip 26.04 lives under
  `data/tools/7zip/`; the Windows system copy (21.04) cannot read this APFS.
- `run --test`: assembles the included tiny userspace program, wraps it in
  a Mach-O RAM root, builds a payload, and runs QEMU for 45 seconds. Success
  requires the PID 1 marker and a decoded screen with no visible panic.
- `run`: expects a prepared `data/root/ios-root.img`. It refuses to silently
  substitute the test program for real iOS.
- `run --root-image <path>`: tests a supplied prepared raw RAM-root image;
  IPSW/DMG inputs and roots larger than the current 1 GiB limit are rejected.
- `status`: shows download phase and the last saved run summary.

Other useful options:

```powershell
python emulator.py download --version 16.7.16
python emulator.py inspect --ipsw "D:\path\firmware.ipsw"
python emulator.py run --test --secs 60 --qemu "G:\Software\qemu\qemu-system-aarch64.exe"
```

The test root proves XNU can execute a userspace process on Windows QEMU.
It does **not** contain Apple's launchd, dyld, SpringBoard, or system apps.

## Local data layout

```text
data/firmware/             IPSW + catalog metadata + progress.json + partial download
data/extracted/20H392/     selected DMGs, IM4P, BuildManifest, manifest summary
data/test-root/            generated test executable/object
data/runs/<time>/          payload, ADT, fb.png/fb.txt, registers and result summary
data/last-run.json         last run state
xnu/out/                  local kernel build artifact
```

`data/`, `research/` and kernel artifacts are ignored by Git. Firmware remains
outside source control and outside the future application bundle.

## Current real-iOS blocker

The downloaded APFS/UDIF images are firmware components, not bootable QEMU
root disks. The existing `tools/mkiosroot.sh` uses Linux APFS/HFS+ utilities.
Native UDIF/APFS reading and extraction of two real Apple binaries have been
verified with 7-Zip 26.04. Complete extraction with metadata preservation,
HFS+ writing and a storage/memory design are still required. The current small
RAM-root layout cannot hold a 16 GiB root.
See `TODO.md` before treating firmware extraction as completed iOS support.

## Checks

```powershell
python -m unittest discover -s tests -v
python tools/check-windows-qemu.py
```

Downloader tests cover correct resume, ignored/wrong Range responses, truncated
transfers, and checksum failure without publishing a corrupt final file.
