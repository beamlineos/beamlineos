# SPDX-License-Identifier: MIT
                                                                                   

import ast
from functools import lru_cache
import io
import json
from pathlib import PurePosixPath
import re
import tokenize

VERSION = 1
NOTICE = re.compile(rb"SPDX-|copyright|\xc2\xa9|\bauthors?:|\bcontributors?:|@license|@preserve|licensed under|redistribution and use|permission is hereby granted", re.I)
DIRECTIVE = re.compile(rb"^#!|coding[:=]|shellcheck\b|(?:type:|#?\s*noqa\b)|(?:clang-format|fmt:|rustfmt|clippy|eslint|prettier|istanbul|doctest:)|sourceMappingURL=|sourceURL=|^# CONFIG_[A-Z0-9_]+ is not set\s*$")
GRAMMARS = {".c": "c", ".h": "c", ".rs": "rust", ".js": "javascript", ".mjs": "javascript",
            ".json": "json", ".jsonc": "json", ".toml": "toml", ".lock": "toml",
            ".html": "html", ".xml": "xml"}
HASH_SUFFIXES = {".conf", ".config", ".service", ".target", ".timer", ".socket", ".mount", ".network",
                 ".preset", ".transfer", ".pam", ".pol", ".txt", ".script", ".override", ".in", ".varlink"}


def blank(data):
    return bytes(byte if byte in (9, 10, 13, 32) else 32 for byte in data)


def keep(comment):
    return bool(NOTICE.search(comment) or DIRECTIVE.search(comment))


def edit(data, replacements):
    cursor, result = 0, []
    for start, end, replacement in sorted(replacements):
        if start < cursor:
            raise ValueError("overlapping source normalization spans")
        result.extend((data[cursor:start], replacement))
        cursor = end
    result.append(data[cursor:])
    return b"".join(result)


def python_source(data):
    text = data.decode("utf-8")
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode()))
    replacements = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT and not keep(token.string.encode()):
            start = offsets[token.start[0] - 1] + len(lines[token.start[0] - 1][:token.start[1]].encode())
            end = offsets[token.end[0] - 1] + len(lines[token.end[0] - 1][:token.end[1]].encode())
            replacements.append((start, end, blank(data[start:end])))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__doc__":
            raise ValueError("move runtime __doc__ use to explicit help data before normalizing")
        if isinstance(node, ast.Attribute) and node.attr == "__doc__":
            raise ValueError("runtime docstring introspection needs an explicit source decision")
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)):
            continue
        if ">>>" in first.value.value or NOTICE.search(first.value.value.encode()):
            continue
        start, end = offsets[first.lineno - 1] + first.col_offset, offsets[first.end_lineno - 1] + first.end_col_offset
                                                                                      
        replacement = blank(data[start:end])
        if len(node.body) == 1 and not isinstance(node, ast.Module):
            first_line = replacement.find(b"\n")
            replacement = b"pass" + replacement[min(4, first_line) if first_line >= 0 else 4:]
        elif data[end:end + 1] == b";":
            end += 1
            replacement += b" "
        replacements.append((start, end, replacement))
    return edit(data, replacements)


@lru_cache(maxsize=None)
def parser(language):
    from tree_sitter_language_pack import get_parser
    return get_parser(language)


def nodes(root):
    yield root
    for child in root.children:
        yield from nodes(child)


def parsed_source(data, language, context):
                                                                                    
                                                                              
    parsed = re.sub(rb"%\{[^}\n]+\}", lambda m: b"X" * len(m[0]), data) if language == "bash" else data
    tree = parser(language).parse(parsed)
    if tree.root_node.has_error:
        bad = next(n for n in nodes(tree.root_node) if n.type == "ERROR" or n.is_missing)
        raise ValueError(f"unsupported {language} syntax in {context}:{bad.start_point[0] + 1}")
    replacements = []
    all_nodes = list(nodes(tree.root_node))
    comments = [n for n in all_nodes if n.type in ("comment", "line_comment", "block_comment")]
                                                                                    
    doctests = set()
    if language == "rust":
        group = []
        for node in comments + [None]:
            if node is not None and data[node.start_byte:node.start_byte + 3] in (b"///", b"//!"):
                if group and data[group[-1].end_byte:node.start_byte].strip():
                    group = []
                group.append(node)
                if any(b"```" in data[n.start_byte:n.end_byte] for n in group):
                    doctests.update(n.start_byte for n in group)
                continue
            if any(b"```" in data[n.start_byte:n.end_byte] for n in group):
                doctests.update(n.start_byte for n in group)
            group = []
    for node in comments:
        comment = data[node.start_byte:node.end_byte]
        if not keep(comment) and node.start_byte not in doctests:
            line_start = data.rfind(b"\n", 0, node.start_byte) + 1
            line_end = data.find(b"\n", node.end_byte)
            line_end = len(data) if line_end < 0 else line_end
            standalone = not data[line_start:node.start_byte].strip() and not data[node.end_byte:line_end].strip()
                                                                                
                                                                                 
            replacement = re.sub(rb"[^\r\n]", b"", comment) if standalone else blank(comment)
            replacements.append((node.start_byte, node.end_byte, replacement))
    if language == "bash":
        for node in all_nodes:
            if node.type == "heredoc_body":
                start, end = node.start_byte, node.end_byte
                header_end = start - 1 if data[start:start + 1] != b"\n" else start
                header_start = data.rfind(b"\n", 0, header_end) + 1
                header = data[header_start:header_end]
                if re.match(rb"\s*python3?\s", header):
                                                                    
                    if data[start:start + 1] == b"\n":
                        start += 1
                    replacements.append((start, end, python_source(data[start:end])))
            elif node.type == "command":
                children = node.named_children
                if children and data[children[0].start_byte:children[0].end_byte] in (b"python", b"python3"):
                    for at, child in enumerate(children[:-1]):
                        following = children[at + 1]
                        if data[child.start_byte:child.end_byte] == b"-c" and following.type == "raw_string":
                            start, end = following.start_byte + 1, following.end_byte - 1
                            replacements.append((start, end, python_source(data[start:end])))
    return edit(data, replacements)


def yaml_source(data, context):
    from ruamel.yaml import YAML
    from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode
                                                                                  
    data = parsed_source(data, "yaml", context)
    text = data.decode()
    replacements = []

    def command_scalar(command):
        start, end = command.start_mark.index, command.end_mark.index
        original = text[start:end]
        if command.style == "|":
            header, body = original.split("\n", 1)
            lines = body.splitlines(keepends=True)
            indentation = min((len(line) - len(line.lstrip(" ")) for line in lines if line.strip()), default=0)
            raw = "".join(line[indentation:] if line.strip() else line for line in lines).encode()
            clean = parsed_source(raw, "bash", context).decode().splitlines(keepends=True)
            if len(clean) != len(lines):
                raise ValueError(f"embedded normalization changed line count in {context}")
            replacement = header + "\n" + "".join(
                line[:indentation] + cleaned if line.strip() else cleaned for line, cleaned in zip(lines, clean))
        else:
            clean = parsed_source(command.value.encode(), "bash", context).decode()
            if clean == command.value:
                return
            replacement = json.dumps(clean, ensure_ascii=False) + "\n" * original.count("\n")
        replacements.append((len(text[:start].encode()), len(text[:end].encode()), replacement.encode()))

    def commands(node, shell=False):
        if isinstance(node, MappingNode):
            for key, value in node.value:
                declared = isinstance(key, ScalarNode) and (key.value == "commands" or key.value.endswith("-commands"))
                commands(value, shell or declared)
        elif isinstance(node, SequenceNode):
            for child in node.value:
                commands(child, shell)
        elif shell and isinstance(node, ScalarNode):
            command_scalar(node)

    if context.endswith((".bst", ".yml", ".yaml")) and context.startswith(("elements/", "include/")):
        commands(YAML(typ="safe").compose(text))
    return edit(data, replacements)


def line_source(data, marker=b"#"):
    replacements, offset = [], 0
    for line in data.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(marker) and not keep(stripped):
            ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
            replacements.append((offset, offset + len(line), ending))
        offset += len(line)
    return edit(data, replacements)


def cil_source(data):
    quoted, escaped, start = False, False, None
    replacements = []
    for at, byte in enumerate(data + b"\n"):
        if start is not None:
            if byte == 10:
                comment = data[start:at]
                if not keep(comment):
                    replacements.append((start, at, blank(comment)))
                start = None
            continue
        if escaped:
            escaped = False
        elif byte == 92 and quoted:
            escaped = True
        elif byte == 34:
            quoted = not quoted
        elif byte == 59 and not quoted:
            start = at
    if quoted:
        raise ValueError("unterminated CIL string")
    return edit(data, replacements)


def normalize(path, data):
    name = PurePosixPath(path)
    suffix = name.suffix
                                                                                
    if (path.startswith("files/keys/") or suffix in (".patch", ".pgp", ".pem", ".crt", ".key", ".asc", ".png", ".wasm")
            or name.name.startswith(("LICENSE", "COPYING", "NOTICE")) or suffix == ".md"):
        return data
    if b"\0" in data:
        raise ValueError(f"unclassified binary export: {path}")
    if suffix == ".py":
        return python_source(data)
    if data.startswith((b"#!/bin/sh", b"#!/usr/bin/sh", b"#!/bin/bash")) or suffix == ".sh":
        return parsed_source(data, "bash", path)
    if suffix in (".bst", ".yml", ".yaml", ".refs") or path == "project.conf":
        return yaml_source(data, path)
    if suffix == ".cil":
        return cil_source(data)
    if suffix == ".rules":
        if "/udev/" in path:
            return line_source(data)
        return parsed_source(data, "javascript", path)
    if suffix in GRAMMARS:
        return parsed_source(data, GRAMMARS[suffix], path)
    if name.name == "meson.build":
        return parsed_source(data, "meson", path)
    if suffix == ".policy" or path.endswith("/dbus_contexts"):
        return parsed_source(data, "xml", path)
    if (suffix in HASH_SUFFIXES or path == ".gitignore" or path.startswith("files/selinux/")
            or path.startswith("files/base/etc/") or "/pam.d/" in path or path in ("files/image/permissions", "files/posix/test-users/group", "files/posix/test-users/passwd")):
        return line_source(data)
    raise ValueError(f"declare the source language or opaque format before exporting: {path}")
