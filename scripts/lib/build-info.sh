#!/usr/bin/env bash
# Prints the build the page names under its title, as KEY=value lines: APP_VERSION,
# MAJOR.MINOR.COMMITS from the release tag the checkout descends from (vMAJOR.MINOR) and the
# number of commits since it, and APP_COMMIT_DATE, the date of the last commit as DD/MM/YYYY. It
# is the one reader of these from git, run on the host: the image build's context leaves out
# .git, so that build receives the two values as build arguments. A checkout without a release
# tag stops here, so no build ships a version that names no release.
#
#   ./scripts/lib/build-info.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

release="$(git -C "$ROOT" describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null)" \
  || { echo "no release tag (vMAJOR.MINOR) reachable from HEAD; fetch them: git fetch --tags" >&2
       exit 1; }
echo "APP_VERSION=${release#v}.$(git -C "$ROOT" rev-list --count "$release..HEAD")"
echo "APP_COMMIT_DATE=$(git -C "$ROOT" log -1 --format=%cd --date=format:%d/%m/%Y)"
