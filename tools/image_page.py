# SPDX-License-Identifier: MIT
                                                                                  
import json
from html import escape
from pathlib import Path
import re
import tempfile
from urllib.parse import quote


from publication import validate_manifest, verify_manifest_signature


PAGE = "site/snapshots/index.html"


def directory_page(directory, entries):
    links = []
    if directory != "/":
        parent = directory.rstrip("/").rsplit("/", 1)[0] + "/"
        links.append(f'<li><a href="{quote(parent, safe="/._-")}">../</a></li>')
    names = sorted(entries, key=lambda name: (not name.endswith("/"), name))
    if directory == "/snapshots/":
        names.reverse()                               
    for name in names:
        links.append(f'<li><a href="{quote(directory + name, safe="/._-")}">{escape(name)}</a></li>')
    return (f'<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n<html lang="en">\n'
            '<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>Index of {escape(directory)}</title>\n</head>\n<body>\n<ul>\n'
            + "\n".join(links) + '\n</ul>\n</body>\n</html>\n').encode()


def render(manifests):
    directories = {"/snapshots/": set()}
    for manifest in sorted(manifests, key=lambda m: (m["snapshot"], m["arch"]), reverse=True):
        snapshot, arch = manifest["snapshot"], manifest["arch"]
        for name in ("publication.json", "publication.json.gpg", *manifest["artifacts"], *manifest["metadata"]):
            parts = ["snapshots", snapshot, arch, *name.split("/")]
            for at in range(1, len(parts)):
                directory = "/" + "/".join(parts[:at]) + "/"
                entry = parts[at] + ("/" if at < len(parts) - 1 else "")
                directories.setdefault(directory, set()).add(entry)
    return {"site" + directory + "index.html": directory_page(directory, entries)
            for directory, entries in directories.items()}


def refresh(remote):
    written = False
    for _ in range(5):
        previous, etag = remote.version(PAGE)
        manifests = []
        with tempfile.TemporaryDirectory(prefix="beamline-image-page-") as temporary:
            release = Path(temporary)
            for key in sorted(remote.publications()):
                match = re.fullmatch(r"snapshots/(\d{8}\.\d{4})/(aarch64)/publication\.json", key)
                if not match:
                    continue
                marker, signature = remote.get(key), remote.get(key + ".gpg")
                if marker is None or signature is None:
                    raise ValueError(f"incomplete committed publication: {key}")
                (release / "publication.json").write_bytes(marker)
                (release / "publication.json.gpg").write_bytes(signature)
                verify_manifest_signature(release)
                manifests.append(validate_manifest(json.loads(marker), match[1]))
        pages = render(manifests)
                                                                               
                                                                                
                                                                                
        conflict = False
        for key in sorted(pages, key=lambda key: (-key.count("/"), key)):
            if key == PAGE:
                continue
            held, held_etag = remote.version(key)
            if held == pages[key]:
                continue
            if not remote.replace_page(key, pages[key], held_etag):
                conflict = True
                break
            written = True
        if conflict:
            continue
        if previous == pages[PAGE]:
            return {"snapshots": len(manifests), "page_written": written}
                                                                                
                                                                               
                                                                                  
        if remote.replace_page(PAGE, pages[PAGE], etag):
            return {"snapshots": len(manifests), "page_written": True}
    raise ValueError("download page changed concurrently; retry --refresh-page")
