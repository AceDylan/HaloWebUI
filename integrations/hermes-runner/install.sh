#!/usr/bin/env bash
# install.sh — install this checkout's runner notification scripts onto the host.
#
# The host scripts in /root/.hermes/scripts/ are what actually run; this directory only
# carries a maintainable copy.  A checkout can therefore be OLDER than the host, and
# copying it over would silently reinstate a fixed bug — that is exactly what happened
# between 2026-09-11 and 2026-09-15, when this copy still had the pre-fix origin lookup.
#
# So the install refuses to go backwards: it compares reclaude-notify.py's SCRIPT_VERSION
# (an increasing YYYY-MM-DD[.N] string) with the installed one and stops unless --force is
# given.  A copy with no SCRIPT_VERSION counts as older than any versioned one.
#
# Usage:
#   ./install.sh [--target-dir DIR] [--force] [--dry-run]
# Defaults to /root/.hermes/scripts.  Existing files are backed up next to the target as
# <name>.bak-<timestamp> before being replaced.  Nothing else on the host is touched: no
# service is restarted, no config or token is read or written, no notification is sent.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR=/root/.hermes/scripts
FORCE=0
DRY_RUN=0
SCRIPTS=(reclaude-notify.py reclaude-notify-backfill.py)

while [ $# -gt 0 ]; do
  case "$1" in
    --target-dir) TARGET_DIR="$2"; shift 2;;
    --force) FORCE=1; shift;;
    --dry-run|-n) DRY_RUN=1; shift;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0;;
    *) echo "install.sh: unknown option: $1" >&2; exit 2;;
  esac
done

# version FILE — SCRIPT_VERSION of a notifier copy, or 0 when it has none.
version() {
  [ -f "$1" ] || { echo 0; return; }
  python3 - "$1" <<'PY'
import re, sys
try:
    text = open(sys.argv[1], encoding="utf-8").read()
except OSError:
    print(0); raise SystemExit
match = re.search(r'^SCRIPT_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
print(match.group(1) if match else 0)
PY
}

src_version="$(version "$SOURCE_DIR/reclaude-notify.py")"
dst_version="$(version "$TARGET_DIR/reclaude-notify.py")"
echo "source:    $SOURCE_DIR/reclaude-notify.py (version $src_version)"
echo "installed: $TARGET_DIR/reclaude-notify.py (version $dst_version)"

if [ -f "$TARGET_DIR/reclaude-notify.py" ] && cmp -s "$SOURCE_DIR/reclaude-notify.py" "$TARGET_DIR/reclaude-notify.py"; then
  echo "already identical; nothing to do"
  exit 0
fi

# Lexicographic order is the version order for YYYY-MM-DD[.N]; "0" loses to everything.
newest="$(printf '%s\n%s\n' "$src_version" "$dst_version" | sort -V | tail -n1)"
if [ "$src_version" != "$newest" ] && [ "$FORCE" != 1 ]; then
  cat >&2 <<MSG
install.sh: refusing to install an older copy.
  this checkout: $src_version
  installed:     $dst_version
Installing it would undo fixes the host already has (the 2026-09-15 origin recording and
config layering, for example).  Update this checkout first, or pass --force if you really
mean to downgrade.
MSG
  exit 1
fi

stamp="$(date +%Y%m%d-%H%M%S)"
for name in "${SCRIPTS[@]}"; do
  src="$SOURCE_DIR/$name"
  dst="$TARGET_DIR/$name"
  [ -f "$src" ] || { echo "install.sh: missing $src" >&2; exit 1; }
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would install $src -> $dst (backup: $dst.bak-$stamp)"
    continue
  fi
  [ -f "$dst" ] && cp -p "$dst" "$dst.bak-$stamp" && echo "backed up $dst -> $dst.bak-$stamp"
  install -m 700 "$src" "$dst"
  echo "installed $dst"
done

[ "$DRY_RUN" = 1 ] && exit 0
echo "now installed: $(version "$TARGET_DIR/reclaude-notify.py")"
echo "the next run of either runner picks it up; no service restart is needed."
