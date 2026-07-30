#!/usr/bin/env bash
# Install KADAS GeoAgent into a KADAS Albireo 2 profile. See SETUP.md.
#
# Idempotent: safe to re-run. Never deletes anything it did not create; an
# existing non-symlink plugin directory is reported, not overwritten.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_SRC="$REPO_ROOT/kadas_geoagent/kadas_geoagent"
PROFILE_DIR="${KADAS_PROFILE_DIR:-$HOME/.local/share/Kadas/Kadas/profiles/default}"
PLUGIN_DIR="$PROFILE_DIR/python/plugins"
KADAS_SRC="${KADAS_SRC:-$HOME/OPENGIS/kadas-albireo2}"
DTM="$KADAS_SRC/share/geodata/dtm_analysis.tif"

ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$1"; }
die()  { printf '  \033[31mfail\033[0m %s\n' "$1" >&2; exit 1; }

echo "KADAS GeoAgent installer"
echo "  repo:    $REPO_ROOT"
echo "  profile: $PROFILE_DIR"
echo

# 1. Plugin symlink -----------------------------------------------------------
echo "[1/3] Plugin discovery"
[ -d "$PLUGIN_SRC" ] || die "plugin package not found at $PLUGIN_SRC"
mkdir -p "$PLUGIN_DIR"
target="$PLUGIN_DIR/kadas_geoagent"
if [ -L "$target" ]; then
  ln -sfn "$PLUGIN_SRC" "$target"
  ok "symlink refreshed -> $(readlink "$target")"
elif [ -e "$target" ]; then
  warn "$target exists and is NOT a symlink; leaving it alone."
  warn "Move it aside and re-run to link the working tree instead."
else
  ln -s "$PLUGIN_SRC" "$target"
  ok "symlinked $target"
fi

# 2. Editable geoagent for KADAS' Python 3.13 ---------------------------------
echo "[2/3] geoagent package (KADAS bundles Python 3.13)"
VENV="$HOME/.open_geoagent/venv_py3.13"
# Inspect the 3.13 site-packages directly rather than running $VENV/bin/python:
# uv leaves that symlink pointing at the *system* interpreter (often 3.10), so it
# reads lib/python3.10/site-packages and would report a false negative. KADAS never
# uses that symlink -- it runs its own bundled 3.13 and only prepends this directory.
SITE="$VENV/lib/python3.13/site-packages"
if [ -d "$SITE" ]; then
  printf '%s\n' "$REPO_ROOT" > "$SITE/_geoagent_dev.pth"
  ok "editable .pth -> $REPO_ROOT"
  if [ -d "$SITE/strands" ]; then
    ok "strands present in $SITE"
  else
    warn "strands missing; install deps from KADAS: Settings -> Dependencies"
  fi
else
  warn "$SITE missing. Start KADAS and run GeoAgent Settings -> Dependencies once,"
  warn "then re-run this script to make the install editable."
fi

# 3. DTM ----------------------------------------------------------------------
echo "[3/3] DTM heightmap"
if [ -r "$DTM" ]; then
  ok "present: $DTM -> $(readlink -f "$DTM")"
else
  warn "missing: $DTM"
  warn "The bundled 'CH (online)' template references it 4x, so KADAS will report"
  warn "'4 invalid layers' and terrain tools will fail. Fetch it with:"
  warn "  cd $KADAS_SRC && oras pull ghcr.io/kadas-albireo/kadas-albireo2/dtm_analysis:1.0 -o ."
  warn "or symlink an existing copy to that path."
fi

echo
echo "Done. Restart KADAS, then set a provider API key in GeoAgent Settings -> Model."
