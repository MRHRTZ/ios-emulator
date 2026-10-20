# Working on ios-sweet

- Read `NOTES.md` before starting; it contains the project goal, hardware facts,
  current blocker, local artifact locations and the next concrete action.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, CI run IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
- Commit completed changes. Use `gh` for GitHub Actions kernel builds and logs.
  Local single-file cross-compiles are useful before spending a CI run.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. The user approved (2026-10-15) using
  internal UFS for iOS and said Android may be deleted: the iOS root goes
  into the existing `userdata` partition (no GPT changes). Keep bootloaders,
  recovery, modem, persist and the backups intact, and confirm each
  destructive step with the user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.

## Branch policy (user instruction, 2026-10-20)
- Active Windows development: dev/window-native.
- Windows publish/release: window-native.
- Stable cross-platform QEMU: main.
- Develop and validate on dev/window-native. Publish/promote changes only as a separate release step; keep release/stable branches separate from development work.
- Native Windows APFS extraction pipeline is deferred by the user. Current priorities: English native-control GUI with icon sidebar/hover labels, no touch-area tooltip; guest RTC, virtio network, and QEMU SMP. Application bundling stays last.
