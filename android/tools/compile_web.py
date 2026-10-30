"""Compile bundled scripts for the WebView shipped with Android 7 (Chrome 51)."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

VERSION = '0.25.12'
ANDROID = Path(__file__).resolve().parents[1]


def compiler():
    system = {'Windows': 'win32', 'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()]
    architecture = {'AMD64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}[platform.machine()]
    name = system + '-' + architecture
    binary = ANDROID / '.tools' / ('esbuild-' + VERSION + '-' + name + ('.exe' if system == 'win32' else ''))
    if binary.exists():
        return binary
    with urllib.request.urlopen(f'https://registry.npmjs.org/@esbuild/{name}/{VERSION}', timeout=60) as response:
        distribution = json.load(response)['dist']
    with urllib.request.urlopen(distribution['tarball'], timeout=60) as response:
        archive = response.read()
    actual = 'sha512-' + base64.b64encode(hashlib.sha512(archive).digest()).decode()
    if actual != distribution['integrity']:
        raise RuntimeError('Compiler download integrity check failed')
    member = 'package/esbuild.exe' if system == 'win32' else 'package/bin/esbuild'
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
        data = package.extractfile(member).read()
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(data)
    if system != 'win32':
        binary.chmod(0o755)
    return binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    executable = str(compiler())
    sources = [ANDROID.parent / 'web/app.js', ANDROID / 'app/src/main/offline/offline_transport.js']
    for source in sources:
        subprocess.run([executable, str(source), '--target=chrome51', '--charset=utf8',
                        '--outfile=' + str(arguments.output / source.name)], check=True)


if __name__ == '__main__':
    main()
