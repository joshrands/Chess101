#!/usr/bin/env bash
# Wrapper for running JS test files under Bazel.
# Usage: run_js_test.sh <test_file.js>
set -euo pipefail
exec node "$@"
