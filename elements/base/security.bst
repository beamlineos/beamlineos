# SPDX-License-Identifier: MIT

kind: stack
description: |
  Authentication and trust infrastructure: PAM with its base configuration, the CA bundle,
  the SELinux policy (docs/security.md §16) and the certificate extension images must be
  signed with (docs/decisions.md D50), and polkit, which decides who may use run0 and the
  systemd administration interfaces (docs/spec.md §19, docs/decisions.md D55); pkexec is
  removed from the root by policy.

depends:
- junctions/freedesktop-sdk.bst:components/linux-pam.bst
- junctions/freedesktop-sdk.bst:components/ca-certificates.bst
- security/policy.bst
- base/verity-trust.bst
- base/polkit.bst
