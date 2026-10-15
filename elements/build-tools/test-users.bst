# SPDX-License-Identifier: MIT
kind: import
description: Locked NSS fixtures for native utility tests, build-only and never installed
config:
  target: /etc
sources:
- kind: local
  path: files/posix/test-users
