# SPDX-License-Identifier: MIT
                                                                            

import hashlib
import os
from pathlib import Path
import platform
import tarfile
import urllib.request


VERSION = "1.1.4"
SOURCE_COMMIT = "ad89f62cc216376f1747dae60f74a890f0a53940"
ARCHIVES = {
    ("Darwin", "arm64"): ("darwin_arm64", "860f8ca3fc5b3be542a036e7ea894e0e423caef0c9698439580c28548c0739a5"),
    ("Darwin", "x86_64"): ("darwin_amd64", "c9f33c4e4d56b98f796ebd871da23fa15cdcfa2f7fb9836e05afec80e93fb10b"),
    ("Linux", "aarch64"): ("linux_arm64", "888a17892c31fb91fbf980ef46a8934398da1f061eb1c20d967abf887faf0b34"),
    ("Linux", "x86_64"): ("linux_amd64", "5f9153351383907b513f3dbb0cf21c86b85d4cda267be9898aed25f799ae9706"),
}


def install(cache):
    try:
        target, expected = ARCHIVES[(platform.system(), platform.machine())]
    except KeyError as exc:
        raise ValueError("desync publication supports macOS/Linux arm64 and amd64") from exc
    directory = cache / "tools" / ("desync-" + VERSION) / target
    directory.mkdir(parents=True, exist_ok=True)
    name = f"desync_{VERSION}_{target}.tar.gz"
    archive = directory / name
    if not archive.exists():
        request = urllib.request.Request(f"https://github.com/folbricht/desync/releases/download/v{VERSION}/{name}",
                                         headers={"User-Agent": "beamline-publish/1"})
        temporary = archive.with_suffix(".download")
        try:
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as dest:
                while block := response.read(1 << 20):
                    dest.write(block)
            os.replace(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("desync release archive checksum differs from the pin")
    with tarfile.open(archive) as tar:
        member = tar.getmember("desync")
        if not member.isfile() or member.size > 128 << 20:
            raise ValueError("desync archive has an invalid executable")
        data = tar.extractfile(member).read()
    binary = directory / "desync"
    if not binary.is_file() or binary.is_symlink() or binary.read_bytes() != data:
        temporary = binary.with_suffix(".new")
        temporary.write_bytes(data)
        temporary.chmod(0o755)
        os.replace(temporary, binary)
    binary.chmod(0o755)
    return binary.resolve()
