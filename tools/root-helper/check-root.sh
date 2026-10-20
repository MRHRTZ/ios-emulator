#!/bin/bash
set -Eeuo pipefail
trap 'rc=$?; if [ "$rc" != 0 ]; then echo "ROOT_BUILD_FAILED exit=$rc"; fi' EXIT
# Resolve the serial-validated device to its short name. Old hfsprogs fsck
# overflows an internal buffer when passed a long /dev/disk/by-id path.
disk=$(readlink -f /dev/disk/by-id/virtio-ios-root-output)
test -b "$disk"
test "$(blockdev --getsize64 "$disk")" = 17179869184
test "$(blkid -s TYPE -o value "$disk")" = hfsplus
echo ROOT_STAGE=check-hfs
fsck.hfsplus -fy "$disk" || true
fsck.hfsplus -fn "$disk"
modprobe hfsplus
mkdir -p /mnt/root
mount -t hfsplus -o ro "$disk" /mnt/root
test -f /mnt/root/sbin/launchd
test -f /mnt/root/usr/lib/dyld
test -f /mnt/root/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64
stat -c '%u %g %a %s %n' /mnt/root/sbin/launchd /mnt/root/usr/lib/dyld
umount /mnt/root
echo ROOT_BUILD_OK
