#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare a verified deployment bundle for stock desync services and Caddy.

Runs once on the publishing/editing host. The serving VM needs no Python,
source checkout, store credentials, or project-specific runtime supervisor.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse

from publish import public_get, safe_path, validate_manifest, verify_manifest_signature, checks, KEYRING, ROOT

SERVER_ROOT = Path("/srv/beamline-images")
MOUNT_ROOT = SERVER_ROOT / "mounts"


def keep_file(path, data):
    """An existing signed release's local metadata is immutable too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and path.read_bytes() != data):
        raise ValueError(f"local immutable metadata conflict: {path.name}")
    if not path.exists():
        path.write_bytes(data)


def fetch_release(base, snapshot, destination):
    prefix = f"snapshots/{snapshot}/aarch64/"
    # Authenticate the manifest before accepting any paths or index hashes from it.
    with tempfile.TemporaryDirectory(prefix="beamline-images-metadata-") as temporary:
        package = Path(temporary)
        for name in ("publication.json", "publication.json.gpg"):
            (package / name).write_bytes(public_get(base, prefix + name))
        verify_manifest_signature(package)
        manifest = validate_manifest(json.loads((package / "publication.json").read_bytes()), snapshot)
        names = dict(manifest["metadata"])
        names.update({a["index"]: a["index_sha256"] for a in manifest["artifacts"].values()})
        for name, digest in names.items():
            data = public_get(base, prefix + safe_path(name))
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"public metadata digest mismatch: {name}")
            target = package / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
        checks.verify_signature(package / "update", KEYRING)
        selected = checks.checksums(package / "update/SHA256SUMS")
        declared = {name.removeprefix("update/"): a["sha256"] for name, a in manifest["artifacts"].items()
                    if name.startswith("update/")}
        if selected != declared or any(snapshot not in name for name in selected):
            raise ValueError("publication disagrees with its signed channel")
        for name in [*names, "publication.json.gpg", "publication.json"]:
            keep_file(destination / name, (package / name).read_bytes())
    return manifest


def caddy_config(site, paths):
    """Set strong ETags before file_server handles conditional/range requests."""
    lines = ["# SPDX-License-Identifier: MIT", "header Cache-Control no-store", "respond /healthz 200"]
    for name, digest in sorted(paths.items()):
        lines.extend([f"    route {json.dumps('/' + name)} {{",
                      "        header ETag " + json.dumps('"sha256-' + digest + '"'),
                      # Separate header handlers: only deletion is deferred. Defer the ETag
                      # itself and Go's If-Range check would see a different validator.
                      "        header -Last-Modified",
                      "        request_header -If-Modified-Since",
                      "        request_header -If-Unmodified-Since",
                      "        header {", '            Cache-Control "public, max-age=31536000, immutable"',
                      "            match status 200 206 304", "        }",
                      f"        root * {json.dumps(str(site))}", "        file_server", "    }"])
    lines.extend(["respond 404", "handle_errors {", "    header -ETag", "    header Cache-Control no-store",
                  "    respond {err.status_code}", "}"])
    return "\n".join(lines) + "\n"


def build_bundle(base, snapshots, bundle):
    data = bundle / "data"
    site = data / "site"
    site.mkdir(parents=True)
    blobs, paths = set(), {}
    for snapshot in snapshots:
        relative = Path("snapshots") / snapshot / "aarch64"
        package = data / "metadata" / snapshot / "aarch64"
        manifest = fetch_release(base, snapshot, package)
        for name, artifact in manifest["artifacts"].items():
            if not re.fullmatch(r"(?:update/)?[A-Za-z0-9._-]+", name):
                raise ValueError("artifact name cannot be used as an exact Caddy path")
            digest = artifact["sha256"]
            keep_file(data / "indexes" / (digest + ".caibx"), (package / artifact["index"]).read_bytes())
            keep_file(data / "images" / (digest + ".env"), f"IMAGE_SIZE={artifact['size']}\n".encode())
            blobs.add(digest)
            target = site / relative / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(MOUNT_ROOT / digest / digest)
            paths[str(relative / name)] = digest
        for name in (*manifest["metadata"], "publication.json", "publication.json.gpg"):
            content = (package / name).read_bytes()
            keep_file(site / relative / name, content)
            paths[str(relative / name)] = hashlib.sha256(content).hexdigest()
    (data / "Caddyfile").write_text(caddy_config(SERVER_ROOT / "site", paths))
    (data / "desync.json").write_text("{}\n")
    (data / "store.env").write_text(f"STORE_URL={base.rstrip('/')}/store/\n")
    systemd = bundle / "systemd"
    systemd.mkdir()
    for name in ("beamline-image@.service", "beamline-images.target"):
        shutil.copyfile(ROOT / "infra/images" / name, systemd / name)
    dropin = systemd / "beamline-images.target.d/snapshots.conf"
    dropin.parent.mkdir()
    units = " ".join(f"beamline-image@{digest}.service" for digest in sorted(blobs))
    dropin.write_text(f"# SPDX-License-Identifier: MIT\n[Unit]\nRequires={units}\nAfter={units}\n")
    dropin = systemd / "caddy.service.d/beamline-images.conf"
    dropin.parent.mkdir()
    dropin.write_text("# SPDX-License-Identifier: MIT\n[Unit]\nWants=beamline-images.target\nAfter=beamline-images.target\n")
    executable = bundle / "libexec/beamline-image-ready"
    executable.parent.mkdir()
    shutil.copyfile(ROOT / "ci/image-mount-ready", executable)
    executable.chmod(0o755)
    return len(blobs)


def prepare(base, snapshots, output):
    """Publish a complete local bundle only after every selected release verifies."""
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists; prepare a fresh bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".beamline-images-", dir=output.parent) as temporary:
        staged = Path(temporary) / "bundle"
        staged.mkdir()
        count = build_bundle(base, snapshots, staged)
        # This bundle contains public data. A private host umask must not make
        # the installed indexes or Caddy document root unreadable to its user.
        staged.chmod(0o755)
        for path in staged.rglob("*"):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() else 0o644)
        (staged / "libexec/beamline-image-ready").chmod(0o755)
        staged.rename(output)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots", nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-url", default="https://store.beamlineos.org")
    args = parser.parse_args()
    try:
        if any(not re.fullmatch(r"\d{8}\.\d{4}", name) for name in args.snapshots):
            raise ValueError("snapshot must be YYYYMMDD.HHMM")
        parsed = urllib.parse.urlsplit(args.public_url)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(c.isspace() for c in args.public_url)):
            raise ValueError("public store URL must be HTTPS without credentials, query or fragment")
        count = prepare(args.public_url, args.snapshots, args.output)
        print(json.dumps({"output": str(args.output.absolute()), "snapshots": args.snapshots,
                          "unique_mounts": count}, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"prepare-images: {exc}\n")


if __name__ == "__main__":
    main()
