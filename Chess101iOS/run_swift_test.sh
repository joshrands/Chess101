#!/usr/bin/env bash
# Wrapper for running swift test under Bazel.
# Uses --package-path so swift can locate Package.swift from the runfiles tree,
# and --build-path to write artifacts to a writable temp directory.
set -euo pipefail

# Resolve the Chess101iOS package directory from Bazel's runfiles.
if [ -n "${TEST_SRCDIR:-}" ] && [ -d "${TEST_SRCDIR}/__main__/Chess101iOS" ]; then
    PKG_DIR="${TEST_SRCDIR}/__main__/Chess101iOS"
else
    # Fallback for running outside Bazel (e.g., direct script invocation).
    PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

BUILD_DIR="$(mktemp -d /tmp/chess101_swift_build.XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

exec swift test --package-path "$PKG_DIR" --build-path "$BUILD_DIR"
