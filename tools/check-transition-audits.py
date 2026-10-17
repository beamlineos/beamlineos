#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                               
import re, sys
lines = open(sys.argv[1], errors='replace').read().splitlines()
for source in ('user_t', 'admin_t'):
    pattern = (r'avc:\s+denied\s+\{\s*transition\s*\}.*'
               r'function="mac_selinux_transient_transition".*'
               rf'scontext=[^ ]*:{source}:.*tcontext=[^ ]*:init_t:.*tclass=process')
    if not any(re.search(pattern, line) for line in lines):
        sys.exit(f'security: missing {source} -> init_t transition refusal audit')
print('security: both explicit init_t refusals came from the SELinux transition check')
