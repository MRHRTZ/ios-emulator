"""IPSW catalog and resumable Apple CDN download; Python standard library only."""
import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEVICE = 'iPhone10,3'
CATALOG = 'https://api.ipsw.me/v4/device/iPhone10,3?type=ipsw'
USER_AGENT = 'ios-emulator-cli/0.1'
CHUNK = 1024 * 1024


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def select_firmware(version='latest'):
    with urlopen(Request(CATALOG, headers={'User-Agent': USER_AGENT}), timeout=30) as response:
        entries = json.load(response)['firmwares']
    candidates = [entry for entry in entries if version == 'latest' or entry['version'] == version]
    if not candidates:
        raise ValueError(f'No firmware {version!r} for {DEVICE}')
    entry = max(candidates, key=lambda item: item['releasedate'])
    if urlparse(entry['url']).hostname != 'updates.cdn-apple.com':
        raise ValueError('Catalog URL is not on the expected Apple CDN')
    if not entry.get('sha256sum'):
        raise ValueError('Catalog does not supply a SHA-256 checksum')
    return entry


def verify(path, expected, progress=None):
    digest = hashlib.sha256()
    size = Path(path).stat().st_size
    done = 0
    last = 0
    with open(path, 'rb') as source:
        while block := source.read(4 * CHUNK):
            digest.update(block)
            done += len(block)
            if progress and time.monotonic() - last >= 1:
                progress('verifying', done, size)
                last = time.monotonic()
    if digest.hexdigest().lower() != expected.lower():
        raise ValueError('SHA-256 mismatch; file retained for diagnosis, not marked ready')
    return digest.hexdigest()


def receive(url, partial, total, report):
    """Append a validated HTTP range, or restart if the server ignores Range."""
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > total:
        raise ValueError('Partial download exceeds expected file size')
    if offset == total:
        return
    headers = {'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    with urlopen(Request(url, headers=headers), timeout=45) as response:
        if urlparse(response.url).hostname != 'updates.cdn-apple.com':
            raise ValueError('Download redirected outside the expected Apple CDN')
        if response.status == 206:
            import re
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if not match or int(match[1]) != offset or int(match[3]) != total or int(match[2]) != total - 1:
                raise ValueError('Server returned an unexpected Content-Range')
        elif response.status == 200:
            offset = 0  # Never append a complete response to an existing partial file.
        else:
            raise ValueError(f'Unexpected HTTP status {response.status}')
        length = response.headers.get('Content-Length')
        if length and int(length) != total - offset:
            raise ValueError('HTTP Content-Length differs from catalog size')
        with partial.open('ab' if offset else 'wb') as output:
            while block := response.read(CHUNK):
                if offset + len(block) > total:
                    raise ValueError('Download is larger than the catalog size')
                output.write(block)
                offset += len(block)
                report('downloading', offset, total)
    if offset != total:
        raise OSError(f'Incomplete transfer: {offset}/{total} bytes; run again to resume')


def download(directory, version='latest'):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    entry = select_firmware(version)
    filename = urlparse(entry['url']).path.rsplit('/', 1)[1]
    target = directory / filename
    partial = target.with_suffix(target.suffix + '.part')
    metadata = directory / (filename + '.json')
    state_path = directory / 'progress.json'
    total = entry['filesize']
    started = time.monotonic()
    initial = partial.stat().st_size if partial.exists() else 0
    last = 0

    def report(phase, done, size, force=False):
        nonlocal last
        now = time.monotonic()
        if not force and now - last < 1:
            return
        last = now
        rate = max(0, done - initial) / max(now - started, 0.001) if phase == 'downloading' else 0
        eta = (size - done) / rate if rate else None
        state = dict(phase=phase, version=entry['version'], build=entry['buildid'],
                     device=DEVICE, file=str(target), bytes=done, total=size,
                     percent=round(done * 100 / size, 2), bytes_per_second=round(rate),
                     eta_seconds=round(eta) if eta is not None else None,
                     updated_at=time.time())
        write_json(state_path, state)
        suffix = f' {rate / CHUNK:.1f} MiB/s ETA {int(eta)}s' if eta is not None else ''
        print(f'\r{phase}: {done * 100 / size:6.2f}% {done / CHUNK:.0f}/{size / CHUNK:.0f} MiB{suffix}    ', end='', flush=True)

    print(f"{DEVICE}: iOS {entry['version']} ({entry['buildid']}) | {total / 1024**3:.2f} GiB", flush=True)
    if metadata.exists():
        old = json.loads(metadata.read_text(encoding='utf-8'))
        if old.get('url') != entry['url'] or old.get('sha256sum') != entry['sha256sum']:
            raise ValueError('Existing download metadata does not match catalog')
    elif partial.exists():
        raise ValueError('Partial file has no provenance metadata; move it aside before retrying')
    write_json(metadata, entry)
    try:
        if not target.exists():
            if shutil.disk_usage(directory).free < total - initial + 64 * CHUNK:
                raise OSError('Not enough free space for IPSW download')
            for attempt in range(3):
                try:
                    receive(entry['url'], partial, total, report)
                    break
                except (OSError, TimeoutError) as error:
                    print(f'\nTransfer interrupted ({type(error).__name__}); retry {attempt + 1}/3', flush=True)
                    if attempt == 2:
                        raise
                    time.sleep(2)
            if partial.stat().st_size != total:
                raise ValueError('Downloaded file size differs from catalog')
            verify(partial, entry['sha256sum'], report)
            partial.replace(target)
        else:
            if target.stat().st_size != total:
                raise ValueError('Existing IPSW has an unexpected size')
            verify(target, entry['sha256sum'], report)
        report('ready', total, total, force=True)
        print(f'\nSHA-256 OK\n{target}', flush=True)
        return target
    except BaseException as error:
        write_json(state_path, dict(phase='interrupted' if isinstance(error, KeyboardInterrupt) else 'error',
                                   file=str(target), error=str(error), resumable=partial.exists(),
                                   bytes=partial.stat().st_size if partial.exists() else 0,
                                   total=total, updated_at=time.time()))
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--version', default='latest')
    args = parser.parse_args()
    download(args.directory, args.version)
