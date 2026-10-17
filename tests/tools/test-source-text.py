#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                             

import ast
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from source_text import normalize


class SourceText(unittest.TestCase):
    def normalized(self, path, data):
        result = normalize(path, data)
        self.assertEqual(normalize(path, result), result)
        self.assertEqual(result.count(b"\n"), data.count(b"\n"))
        return result

    def test_python_strings_help_empty_suites_and_directives(self):
        source = b'''#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""prose module documentation"""
# removed prose
HELP = "usage: tool # literal"
value = "# this is data"
def answer():
    """prose function documentation"""
    return value, HELP  # removed tail
class Empty:
    """empty suite prose"""
number = 1  # type: ignore
'''
        clean = self.normalized("tools/example.py", source)
        self.assertIn(b"#!/usr/bin/env python3", clean)
        self.assertIn(b"SPDX-License-Identifier", clean)
        self.assertIn(b"type: ignore", clean)
        self.assertNotIn(b"removed prose", clean)
        self.assertNotIn(b"prose function", clean)
        self.assertIn(b"pass", clean)
        before, after = {}, {}
        exec(compile(source, "before", "exec"), before)
        exec(compile(clean, "after", "exec"), after)
        self.assertEqual(before["answer"](), after["answer"]())
        unicode_source = b'# \xc2\xa9 2026 Example\n# Author: Example\nvalue = "\xc3\xa9 # data"  # prose \xc3\xa9\n'
        unicode_clean = self.normalized("tools/example.py", unicode_source)
        self.assertIn(b'\xc2\xa9 2026 Example', unicode_clean)
        self.assertIn(b'Author: Example', unicode_clean)
        self.assertIn(b'"\xc3\xa9 # data"', unicode_clean)
        self.assertNotIn(b'prose', unicode_clean)

    def test_python_docstring_introspection_fails_and_doctests_remain_executable(self):
        with self.assertRaisesRegex(ValueError, "help data"):
            normalize("tools/example.py", b'"""help"""\nprint(__doc__)\n')
        source = b'def example():\n    """Example.\n    >>> 1 + 1\n    2\n    """\n    return 2\n'
        self.assertEqual(self.normalized("tools/example.py", source), source)
        ast.parse(self.normalized("tools/example.py", b'"doc"; answer = 1\n'))
        ast.parse(self.normalized("tools/example.py", b'class Empty:\n    """\n    prose\n    """\n'))

    def test_c_rust_and_javascript_strings_token_boundaries_and_notices(self):
        cases = {
            "files/example.c": b'/* Copyright 2026 Example. All rights reserved. */\nint/**/value = 1; // prose\nchar *s = "/* data */";\n',
            "files/example.rs": b'// SPDX-License-Identifier: MIT\n/* prose /* nested */ prose */\nfn main() { let s = "// data"; }\n',
            "infra/example.mjs": b'// prose\nconst re = /a\\/\\/b/; const s = `/* data */ ${1 /* prose */}`;\n',
        }
        for path, source in cases.items():
            with self.subTest(path=path):
                clean = self.normalized(path, source)
                self.assertNotIn(b"prose", clean)
                self.assertIn(b"data", clean)
        clean = normalize("files/example.c", cases["files/example.c"])
        self.assertIn(b"Copyright", clean)
        self.assertIn(b"int    value", clean)

    def test_rust_doctest_blocks_remain(self):
        source = b'/// Example.\n/// ```\n/// assert_eq!(1, 1);\n/// ```\nfn example() {}\n'
        self.assertEqual(self.normalized("files/example.rs", source), source)

    def test_configuration_and_markup_comment_delimiters_inside_data_remain(self):
        cases = {
            "policy/example.toml": b'# prose\nvalue = "# data"\n',
            "infra/example.jsonc": b'{/* prose */ "value": "/* data */"}\n',
            "infra/example.html": b'<!-- prose -->\n<p title="<!-- data -->">data</p>\n',
            "files/example.xml": b'<?xml version="1.0"?><!-- prose --><root><![CDATA[<!-- data -->]]></root>\n',
            "files/gdm/meson.build": b"# prose\nvalue = '# data'\n",
        }
        for path, source in cases.items():
            with self.subTest(path=path):
                clean = self.normalized(path, source)
                self.assertNotIn(b"prose", clean)
                self.assertIn(b"data", clean)

    def test_shell_python_heredoc_and_opaque_heredoc_data(self):
        source = b'''#!/bin/sh
# shellcheck disable=SC2086
# prose
printf '%s\\n' '# literal'
cat <<'DATA'
# opaque data
DATA
python3 - <<'PY'
# embedded prose
value = "# literal"
PY
'''
        clean = self.normalized("ci/example", source)
        self.assertNotIn(b"embedded prose", clean)
        self.assertNotIn(b"# prose", clean)
        self.assertIn(b"# opaque data", clean)
        self.assertIn(b"# literal", clean)
        self.assertIn(b"shellcheck disable=SC2086", clean)

    def test_buildstream_commands_are_declared_shell_while_other_scalars_are_data(self):
        source = b'''# prose YAML
description: "# data"
config:
  build-commands:
  - |
    # prose shell
    echo '# data'
    python3 - <<'PY'
    # prose Python
    value = "# data"
    PY
other: |
  # opaque text
'''
        clean = self.normalized("elements/example.bst", source)
        self.assertNotIn(b"prose", clean)
        self.assertIn(b"# opaque text", clean)
        self.assertIn(b"description: \"# data\"", clean)
        composed = b'config:\n  commands:\n    (<):\n    - |\n      # prose command\n      echo "# data"\n'
        self.assertNotIn(b"prose command", self.normalized("elements/example.bst", composed))

    def test_cil_quoted_semicolons_kernel_unset_and_opaque_bytes(self):
        source = b'; SPDX-License-Identifier: MIT\n; prose\n(filecon "/x;y" file (u r t (s0))) ; prose tail\n'
        clean = self.normalized("files/selinux/policy/test.cil", source)
        self.assertNotIn(b"prose", clean)
        self.assertIn(b'"/x;y"', clean)
        kernel = self.normalized("files/kernel/config/example.config", b'# prose\n# CONFIG_UNUSED is not set\nCONFIG_TEST=y\n')
        self.assertIn(b"# CONFIG_UNUSED is not set", kernel)
        for path in ("files/keys/dev/example.key", "files/patches/example.patch", "LICENSE.example"):
            opaque = b"# legal or opaque data\n\x00\xff\n"
            self.assertEqual(self.normalized(path, opaque), opaque)

    def test_unknown_formats_and_malformed_known_source_fail_closed(self):
        for path, source in (("files/new.go", b"// prose\npackage main\n"),
                             ("files/example.c", b"int { malformed"),
                             ("files/example.py", b"def broken("),
                             ("files/example.cil", b'(filecon "unterminated')):
            with self.subTest(path=path), self.assertRaises((ValueError, SyntaxError)):
                normalize(path, source)


if __name__ == "__main__":
    unittest.main()
