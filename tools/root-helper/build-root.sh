#!/bin/bash
set -Eeuo pipefail
exec > >(tee -a /var/log/ios-root-build.log /dev/ttyS0) 2>&1
trap 'rc=$?; if [ "$rc" != 0 ]; then echo "ROOT_BUILD_FAILED exit=$rc line=$LINENO"; fi' EXIT
export DEBIAN_FRONTEND=noninteractive
echo ROOT_STAGE=dependencies
apt-get update
apt-get install -y --no-install-recommends git g++ cmake make libfuse3-dev libbz2-dev zlib1g-dev libattr1-dev hfsprogs rsync python3 ca-certificates
echo ROOT_STAGE=apfs-reader
if [ ! -x /opt/apfs-fuse/build/apfs-fuse ]; then
    if [ ! -d /opt/apfs-fuse/.git ]; then
        git clone --recursive https://github.com/sgan81/apfs-fuse.git /opt/apfs-fuse
    fi
    git -C /opt/apfs-fuse checkout 66b86bd525e8cb90f9012543be89b1f092b75cf3
    git -C /opt/apfs-fuse submodule update --init --recursive
    echo ROOT_APFS_COMMIT=$(git -C /opt/apfs-fuse rev-parse HEAD)
    cmake -S /opt/apfs-fuse -B /opt/apfs-fuse/build -DCMAKE_CXX_FLAGS=-include\ cstdint
    cmake --build /opt/apfs-fuse/build --clean-first -j2
fi
disk=$(readlink -f /dev/disk/by-id/virtio-ios-root-output)
test -b "$disk"
test "$(blockdev --getsize64 "$disk")" = 17179869184
for id in ios-os-source ios-system-source ios-app-source; do
    test -b "/dev/disk/by-id/virtio-$id"
    test "$(blockdev --getro "/dev/disk/by-id/virtio-$id")" = 1
done
if ! modprobe hfsplus; then
    apt-get install -y --no-install-recommends "linux-modules-extra-$(uname -r)"
    modprobe hfsplus
fi
mkdir -p /mnt/{os,system,app,root}
echo ROOT_STAGE=mount-sources
/opt/apfs-fuse/build/apfs-fuse /dev/disk/by-id/virtio-ios-os-source /mnt/os
/opt/apfs-fuse/build/apfs-fuse /dev/disk/by-id/virtio-ios-system-source /mnt/system
/opt/apfs-fuse/build/apfs-fuse /dev/disk/by-id/virtio-ios-app-source /mnt/app
test -f /mnt/os/root/sbin/launchd
test -f /mnt/os/root/usr/lib/dyld
echo ROOT_STAGE=format-hfs
if [ "$(blkid -s TYPE -o value "$disk" || true)" != hfsplus ]; then
    mkfs.hfsplus -s -J -v iOSRoot "$disk"
else
    fsck.hfsplus -fy "$disk" || true
fi
mount -t hfsplus -o force "$disk" /mnt/root
echo ROOT_STAGE=copy-os
rsync -aH --numeric-ids --info=progress2 /mnt/os/root/ /mnt/root/
echo ROOT_STAGE=copy-system
mkdir -p /mnt/root/private/preboot/Cryptexes/{OS,App}
rsync -aH --numeric-ids --info=progress2 /mnt/system/root/ /mnt/root/private/preboot/Cryptexes/OS/
echo ROOT_STAGE=copy-app
rsync -aH --numeric-ids /mnt/app/root/ /mnt/root/private/preboot/Cryptexes/App/
echo ROOT_STAGE=link-cryptexes
cache=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
mkdir -p /mnt/root/System/Library/Caches/com.apple.dyld
for file in /mnt/root/"$cache"/*; do
    target=/mnt/root/System/Library/Caches/com.apple.dyld/"${file##*/}"
    [ -e "$target" ] || ln "$file" "$target"
done
for cryptex in OS App; do
    cd /mnt/root/private/preboot/Cryptexes/"$cryptex"
    find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*' -print0 |
    while IFS= read -r -d '' rel; do
        rel=${rel#./}
        target=/mnt/root/"$rel"
        if [ ! -e "$target" ] && [ ! -L "$target" ]; then
            mkdir -p "$(dirname "$target")"
            if [ -L "$rel" ]; then cp -P "$rel" "$target"; else ln "$rel" "$target"; fi
        fi
    done
done
cd /root
db=/mnt/root/private/var/db
install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for dir in diagnostics uuidtext diagnostics/timesync; do
    install -o 272 -g 272 -m 0644 /dev/null "$db/$dir/.migrated"
done
install -d -m 0700 -o 0 -g 0 /mnt/root/private/var/keybags
python3 - <<'PY'
import plistlib, pathlib
p=pathlib.Path('/mnt/root/private/var/keybags/systembag.kb')
p.write_bytes(plistlib.dumps({'KeyBagKeys':b'SWEET'}));p.chmod(0o600)
PY
echo ROOT_STAGE=tweaks
python3 /root/sweet-root-tweaks.py /mnt/root
test -f /mnt/root/sbin/launchd
test -f /mnt/root/usr/lib/dyld
test -f /mnt/root/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64
stat -c '%u %g %a %s %n' /mnt/root/sbin/launchd /mnt/root/usr/lib/dyld
df -h /mnt/root
sync
umount /mnt/root
echo ROOT_STAGE=check-hfs
fsck.hfsplus -fy "$disk" || true
fsck.hfsplus -fn "$disk"
echo ROOT_BUILD_OK
