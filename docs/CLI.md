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
python emulator.py prepare-root
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
- `prepare-root`: builds a sparse 16 GiB case-sensitive HFS+ root using a
  temporary Ubuntu x86_64 QEMU helper. Windows uses WHPX, which must already
  be available. No Docker/WSL is used. All three firmware source disks are
  read-only; the helper writes only its new output and private Linux overlay.
  Installs Linux APFS/HFS+ tools inside that helper. Local Python dependency:
  `python -m pip install --target data/python-deps pycdlib==1.22.0`.
  Emits preparation stages; progress is saved in `data/root-helper/progress.json`.
  A completed filesystem check and clean volume header are required before
  publishing `data/root/ios-root.img`; interrupted construction stays separate.
  Use `prepare-root --check-only` to recheck a completed staging disk without
  recopying firmware. A long-path bug in hfsprogs is avoided by resolving the
  validated disk serial link to the short guest device path.
- `run --test`: assembles the included tiny userspace program, wraps it in
  a Mach-O RAM root, builds a payload, and runs QEMU for 45 seconds. Success
  requires the PID 1 marker and a decoded screen with no visible panic.
- `run`: expects prepared `data/root/ios-root.img` and a kernel with patch 0082.
  Boots through virtio block storage with a new qcow2 overlay on every run.
  The base image is preserved. Serial console streams to the CLI.
  Default kernel-managed RAM is 2048 MiB; use `--memory-mib` (256..4096) to change it.
  The CLI never substitutes the test program for real iOS. The default run
  lasts 300 seconds; choose `--secs` for longer runs. Each run ends with a
  framebuffer snapshot and serial log in its run directory.
- `run --cpus 2` / `--cpus 4`: select matching QEMU/ADT/kernel CPU topology; requires kernel0087+.
- `run --network`: enable outbound user-mode NAT; requires kernel0088+.
- `gui`: live desktop display and input, described in [GUI.md](GUI.md).
- `run --disk-image <path>`: selects another prepared raw HFS+ disk.
  Changes remain in the run directory overlay; reuse/promotion is not yet exposed.
- `run --root-image <path>`: tests a supplied prepared raw RAM-root image;
  IPSW/DMG inputs and roots larger than the current 1 GiB limit are rejected.
- `status`: shows download phase and the last saved run summary.
  `apple_userland_started` requires the Apple launchd early-boot log;
  `springboard_exec_observed` records execution separately. Neither flag
  claims that the home screen or input works. Serial panic and root mount
  errors remain failures even if an earlier boot milestone was reached. `springboard_display_observed` records serial display evidence; `full_ios_boot_verified` remains false without independent visual/input verification.

Other useful options:

```powershell
python emulator.py download --version 16.7.16
python emulator.py inspect --ipsw "D:\path\firmware.ipsw"
python emulator.py run --kernel xnu/out-0083/kernel.development.sweet --secs 300
python emulator.py run --test --secs 60 --qemu "G:\Software\qemu\qemu-system-aarch64.exe"
```

The test root proves XNU can execute a userspace process on Windows QEMU.
It does **not** contain Apple's launchd, dyld, SpringBoard, or system apps.

## Local data layout

```text
data/firmware/             IPSW + catalog metadata + progress.json + partial download
data/extracted/20H392/     selected DMGs, IM4P, BuildManifest, manifest summary
data/root-helper/          temporary Linux helper, serial log and progress
data/root/                 staging root, prepared root and ready.json
data/test-root/            generated test executable/object
data/runs/<time>/          payload, ADT, fb.png/fb.txt, registers and result summary
data/last-run.json         last run state
xnu/out/                  local kernel build artifact
```

`data/`, `research/` and kernel artifacts are ignored by Git. Firmware remains
outside source control and outside the future application bundle.

## Current real-iOS status

Kernel patches 0082/0083 were built successfully in CI run 39371527018.
Windows QEMU executes the minimal test PID 1 with the new kernel and streams
the serial console. Apple firmware has been downloaded and extracted; the
16 GiB HFSX root passed filesystem repair/check with 11.67 GiB used; ownership, permissions, symlinks
and hardlinks were preserved by rsync. Extended attribute/ACL parity is not yet
verified. The virtual disk avoids loading the whole root into guest RAM.
Apple launchd completed early boot in Windows QEMU; xpcproxy, SpringBoard
and backboardd executed and framebuffer swaps were observed. This confirms
real Apple userspace. Later GUI runs visually verified the home screen and touch input; CLI serial markers alone still do not prove a usable home screen. driverkitd
was killed by the per-process memory limit (Jetsam namespace 1/code 7),
confirmed from this kernel source; it has not been fixed yet.
These binaries are downloaded from Apple's IPSW, not committed to this repo.
Kernel0087 also passed 2/4-core PID1 tests and a four-core real-iOS boot through launchd/SpringBoard with current-date timestamps. See TODO.md for network verification and application packaging work.

## Checks

```powershell
python -m unittest discover -s tests -v
python tools/check-windows-qemu.py
```

Downloader tests cover correct resume, ignored/wrong Range responses, truncated
transfers, and checksum failure without publishing a corrupt final file.
