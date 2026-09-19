#!/bin/sh
# Interactive build. Python 3 is the only requirement.
set -e
cd "$(dirname "$0")"
for P in python3 python py; do
  if command -v "$P" >/dev/null 2>&1; then
    V=$("$P" -c 'import sys;print(sys.version_info[0])' 2>/dev/null || echo 0)
    [ "$V" = "3" ] && exec "$P" tweak.py "$@"
  fi
done
echo "Python 3 not found. Get it from https://www.python.org/downloads/" >&2
exit 1
