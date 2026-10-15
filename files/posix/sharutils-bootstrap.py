#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Keep sharutils' bootstrap offline and deterministic, without changing its utility code."""
from pathlib import Path
import re

p = Path('bootstrap')
s = p.read_text()
s, count = re.subn(r'    sharutils_version=\$\(.*?sharutils\.ver\)',
                   '    sharutils_version=4.15.2+git', s, count=1, flags=re.S)
assert count == 1, 'sharutils version bootstrap changed'
s, count = re.subn(r'    declare last_pull=.*?    # Isolate all the \.po files',
                   '    # Isolate all the .po files', s, count=1, flags=re.S)
assert count == 1, 'sharutils translation bootstrap changed'
s = s.replace('git config user.name', 'printf Beamline').replace('git config user.email', 'printf build@beamline.invalid')
s = s.replace('date "+%Y', 'date -u -d "@${SOURCE_DATE_EPOCH}" "+%Y')
s = s.replace("date '+%B", "date -u -d \"@${SOURCE_DATE_EPOCH}\" '+%B")
s = s.replace("date +'%d", "date -u -d \"@${SOURCE_DATE_EPOCH}\" +'%d")
p.write_text(s)

# Gettext 1.0 removed the bundled-intl mode. Use the SDK's external gettext
# interface (the recipe disables translations); no utility implementation changes.
p = Path('configure.ac.git')
s = p.read_text()
assert 'AM_GNU_GETTEXT([no-libtool])' in s, 'sharutils gettext bootstrap changed'
assert '  intl/Makefile\n' in s, 'sharutils intl bootstrap changed'
p.write_text(s.replace('AM_GNU_GETTEXT([no-libtool])', 'AM_GNU_GETTEXT([external])')
             .replace('  intl/Makefile\n', ''))
p = Path('Makefile.am')
s = p.read_text()
assert 'SUBDIRS         = intl lib ' in s, 'sharutils intl build changed'
p.write_text(s.replace('SUBDIRS         = intl lib ', 'SUBDIRS         = lib '))

# The old bundled-intl header supplied these declarations implicitly. Declare
# the libc interface before gnulib's translation macros with external gettext.
p = Path('lib/system.h')
s = p.read_text()
assert '#include "config.h"\n' in s, 'sharutils shared header changed'
p.write_text(s.replace('#include "config.h"\n',
                       '#include "config.h"\n#include <libintl.h>\n', 1))

# The export goes into every generated header; the include already defines the
# symbol in each utility's one options source. Modern GCC defaults to -fno-common.
p = Path('src/shar-std.def')
s = p.read_text()
assert s.count('char const * const program_name;') == 1, 'sharutils name export changed'
p.write_text(s.replace('char const * const program_name;',
                       'extern char const * const program_name;'))
