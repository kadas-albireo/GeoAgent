#!/usr/bin/env bash
# Build the client-facing KADAS GeoAgent plugin zip.
#
# Produces ONE zip that installs on both Linux and Windows. It is self-contained:
#   kadas_geoagent/                the plugin KADAS loads
#     open_geoagent/               the shared chat/settings dock (normally a sibling)
#     bundled/GeoAgent-*.whl       the agent core, so no PyPI release is required
#
# Provider clients (anthropic, openai, ...) are still fetched from PyPI on first
# run, so the client needs internet once. Everything platform-specific (the
# Python venv) is created at that point by deps_manager, which is why a single
# zip serves both operating systems.
#
# Usage: ./build_release.sh [--output DIR] [--no-wheel]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_SRC="$REPO_ROOT/kadas_geoagent/kadas_geoagent"
SHARED_SRC="$REPO_ROOT/qgis_geoagent/open_geoagent"
OUTPUT_DIR="$REPO_ROOT/dist"
BUILD_WHEEL=true

while [[ $# -gt 0 ]]; do
  case $1 in
    --output|-o) OUTPUT_DIR="$2"; shift 2 ;;
    --no-wheel)  BUILD_WHEEL=false; shift ;;
    --help|-h)   sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
info() { printf '  ..   %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$1"; }
die()  { printf '  \033[31mfail\033[0m %s\n' "$1" >&2; exit 1; }

VERSION=$(grep '^version=' "$PLUGIN_SRC/metadata.txt" | cut -d= -f2 | tr -d '[:space:]')
[ -n "$VERSION" ] || die "could not read version from metadata.txt"

# Git state is part of the build identity, so resolve it before naming the zip.
# A dirty tree is marked in the filename too: an unreproducible build should be
# obvious from the file alone, not just from something inside it.
GIT_COMMIT=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "nogit")
GIT_DIRTY=""
DIRTY_SUFFIX=""
if ! git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null; then
  GIT_DIRTY=" (uncommitted changes)"
  DIRTY_SUFFIX="-dirty"
fi

ZIP_NAME="kadas_geoagent-${VERSION}-${GIT_COMMIT}${DIRTY_SUFFIX}.zip"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/kadas_geoagent"

echo "Building KADAS GeoAgent ${VERSION}"
echo

# 1. Plugin package -----------------------------------------------------------
info "staging plugin"
mkdir -p "$PKG"
cp -r "$PLUGIN_SRC/." "$PKG/"
rm -rf "$PKG/tests"
ok "plugin staged"

# 2. Shared dock package ------------------------------------------------------
# _shared.py looks for <plugin dir>/open_geoagent, so nesting it here makes the
# zip self-contained instead of relying on a sibling checkout.
info "bundling shared dock package"
[ -d "$SHARED_SRC" ] || die "open_geoagent not found at $SHARED_SRC"
cp -r "$SHARED_SRC" "$PKG/open_geoagent"
ok "open_geoagent bundled"

# 3. GeoAgent wheel -----------------------------------------------------------
mkdir -p "$PKG/open_geoagent/bundled"
if [ "$BUILD_WHEEL" = true ]; then
  info "building GeoAgent wheel (this takes a moment)"
  PY=""
  for c in "$HOME/.open_geoagent/venv_py3.12/bin/python" python3 python; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
    [ -x "$c" ] && { PY="$c"; break; }
  done
  [ -n "$PY" ] || die "no python found to build the wheel"
  "$PY" -m pip wheel --no-deps --wheel-dir "$PKG/open_geoagent/bundled" "$REPO_ROOT" \
    >/dev/null 2>&1 || die "wheel build failed (try: $PY -m pip install build wheel)"
  WHEEL=$(ls "$PKG/open_geoagent/bundled"/*.whl 2>/dev/null | head -1)
  [ -n "$WHEEL" ] || die "no wheel produced"
  ok "wheel: $(basename "$WHEEL")"
else
  info "skipping wheel (--no-wheel); client will install GeoAgent from PyPI"
fi

# 4. Clean ---------------------------------------------------------------------
find "$PKG" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$PKG" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete 2>/dev/null || true

# 5. Docs for the client -------------------------------------------------------
for doc in INSTALL.md LOCAL_MODEL.md; do
  [ -f "$REPO_ROOT/kadas_geoagent/$doc" ] && cp "$REPO_ROOT/kadas_geoagent/$doc" "$PKG/"
done
ok "client docs included"

# 6. Build provenance ----------------------------------------------------------
# Support's first question is always "which build are you running?". Stamping the
# commit into the zip answers it without guesswork, and the dirty flag makes an
# unreproducible build obvious rather than silent.
[ -n "$DIRTY_SUFFIX" ] && \
  warn "building from a DIRTY working tree - this build is not reproducible"
cat > "$PKG/BUILD_INFO.txt" <<EOF
KADAS GeoAgent
plugin version : ${VERSION}
git commit     : ${GIT_COMMIT}${GIT_DIRTY}
built          : $(date -u '+%Y-%m-%d %H:%M UTC')
built on       : $(uname -s) $(uname -m)

Works on KADAS Albireo 2.x and 3.x; see INSTALL.md.
Quote the git commit above when reporting a problem.
EOF
ok "provenance stamped (${GIT_COMMIT}${GIT_DIRTY})"

# 6. Zip -----------------------------------------------------------------------
mkdir -p "$OUTPUT_DIR"
OUT="$OUTPUT_DIR/$ZIP_NAME"
rm -f "$OUT"
( cd "$STAGE" && zip -qr "$OUT" kadas_geoagent )
ok "wrote $OUT ($(du -h "$OUT" | cut -f1))"

# 7. Verify --------------------------------------------------------------------
echo
echo "Verifying archive:"
for required in \
  kadas_geoagent/__init__.py \
  kadas_geoagent/metadata.txt \
  kadas_geoagent/open_geoagent/__init__.py \
  kadas_geoagent/open_geoagent/deps_manager.py
do
  unzip -l "$OUT" | grep -q "$required" \
    && printf '  \033[32mok\033[0m   %s\n' "$required" \
    || die "missing from archive: $required"
done
if [ "$BUILD_WHEEL" = true ]; then
  unzip -l "$OUT" | grep -q "open_geoagent/bundled/.*\.whl" \
    && ok "bundled GeoAgent wheel" || die "wheel missing from archive"
fi
# A stray venv or secrets file in a client deliverable would be a leak.
if unzip -l "$OUT" | grep -qiE "secrets\.yaml|\.venv/|site-packages/"; then
  die "archive contains a secrets file or a virtualenv"
fi
ok "no secrets or virtualenvs in archive"

SHA=$(sha256sum "$OUT" | cut -d' ' -f1)

echo
echo "=================================================================="
echo " Deliverable : $OUT"
echo " Size        : $(du -h "$OUT" | cut -f1)"
echo " Version     : ${VERSION}  (commit ${GIT_COMMIT}${GIT_DIRTY})"
echo " SHA-256     : $SHA"
echo "=================================================================="
echo
echo "Send this single file to the client. It installs on Linux and Windows"
echo "via Plugins -> Manage and Install Plugins -> Install from ZIP."
echo "INSTALL.md and LOCAL_MODEL.md are inside the zip as well."
