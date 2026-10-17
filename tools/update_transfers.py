# SPDX-License-Identifier: MIT
                                                                                       

import argparse
from pathlib import Path
import re
from urllib.parse import urlsplit


def channel_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("channel URL must be HTTP(S) without credentials, query, fragment or whitespace")
    return value.rstrip("/") + "/"


def render(source, url, predecessor=None):
    lines = []
    for path in sorted(source.iterdir()):
        if predecessor is not None:
            match = re.fullmatch(r"\d+-(.+)-(sysext|confext)\.transfer", path.name)
            if match and not any(predecessor.glob(f"{match[1]}_*.{match[2]}.raw")):
                continue
        body = "".join(f"Path={url}\n" if line.startswith("Path=https://") else line
                       for line in path.read_text().splitlines(keepends=True) if not line.startswith("#"))
        body = body.replace("\\", "\\\\").replace("\n", "\\n").replace("%", "%%")
        lines.append(f"f+ /run/sysupdate.d/{path.name} 0644 - - - {body}\n")
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Validate update inputs or render test transfer credentials.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("snapshots").add_argument("values", nargs="*")
    commands.add_parser("url").add_argument("value")
    rendering = commands.add_parser("render")
    rendering.add_argument("source", type=Path)
    rendering.add_argument("url")
    rendering.add_argument("--predecessor", type=Path)
    rendering.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "snapshots":
            if any(value and not re.fullmatch(r"\d{8}\.\d{4}", value) for value in args.values):
                raise ValueError("explicit snapshots must be YYYYMMDD.HHMM")
        elif args.command == "url":
            print(channel_url(args.value))
        else:
            url = channel_url(args.url)
            if args.candidate:
                args.candidate.write_text(render(args.source, url))
            print(render(args.source, url, args.predecessor), end="")
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
