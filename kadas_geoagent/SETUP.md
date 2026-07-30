# KADAS GeoAgent — setup from scratch

What actually has to be true for the agent to work inside a fresh KADAS Albireo 2:

| # | Requirement | Where it lives |
|---|---|---|
| 1 | The plugin package is on KADAS' plugin search path | `<KADAS profile>/python/plugins/kadas_geoagent` |
| 2 | The `geoagent` pip package is importable from KADAS' Python | `~/.open_geoagent/venv_py3.13/` |
| 3 | The `open_geoagent` dock package is importable | sibling checkout, found by `_shared.py` |
| 4 | A provider API key is set | KADAS → GeoAgent Settings → Model |
| 5 | The DTM exists (terrain tools + the CH template) | `<kadas src>/share/geodata/dtm_analysis.tif` |

Steps 1, 2 and 5 are what `install_kadas_geoagent.sh` automates.

---

## The one-liner

```bash
./kadas_geoagent/install_kadas_geoagent.sh
```

Then start KADAS and set an API key in **GeoAgent Settings → Model**.

---

## What it does, and why

### 1. Plugin discovery — a symlink, not a copy

KADAS derives its profile directory from `QApplication::setOrganizationName("Kadas")`
plus the release name (`kadas/app/main.cpp:98`), which on Linux resolves to:

```
~/.local/share/Kadas/Kadas/profiles/default/python/plugins/
```

The installer symlinks the working tree in:

```
.../plugins/kadas_geoagent -> <repo>/kadas_geoagent/kadas_geoagent
```

A symlink (not a copy) means edits are live — no reinstall per change. `_shared.py`
deliberately resolves through `realpath`, so the symlink still lets it find the
sibling `open_geoagent` package.

### 2. The Python dependency — an editable venv

`geoagent` is a **pip dependency**, not part of the plugin. KADAS bundles Python 3.13,
so `deps_manager.py` provisions `~/.open_geoagent/venv_py3.13/` and prepends its
`site-packages` to KADAS' `sys.path`. It is made editable with a `.pth` file
containing the repo root:

```
~/.open_geoagent/venv_py3.13/lib/python3.13/site-packages/_geoagent_dev.pth
```

So working-tree edits reach KADAS directly. **Restart KADAS to pick up edits** —
Python caches modules; there is no hot reload.

> Only `venv_py3.12` has `strands` + the test deps. Always run pytest with
> `~/.open_geoagent/venv_py3.12/bin/python -m pytest tests/ -q`.

### 3. The DTM — not in git, and load-bearing

`share/geodata/dtm_analysis.tif` (1.2 GB) is **deliberately not in git**. It is
load-bearing for more than terrain analysis: the bundled **CH (online)** project
template references `../geodata/dtm_analysis.tif` **four times**, so a missing DTM is
exactly the *"4 invalid layers"* warning at startup.

Get it either way:

```bash
# canonical
oras pull ghcr.io/kadas-albireo/kadas-albireo2/dtm_analysis:1.0 -o .
# or link an existing copy
ln -s /path/to/dtm_analysis.tif <kadas src>/share/geodata/dtm_analysis.tif
```

A dev build resolves `share/` from the **source tree** (`build-*/output/bin/kadassourcedir.txt`
records it), so the file belongs in the source checkout, not an install prefix.

Once present, point the agent at it:

> "Set the DTM CH 10m layer as the heightmap, then compute a hillshade."

Every KADAS terrain tool reads one project entry —
`QgsProject.readEntry("Heightmap", "layer")` — which `set_heightmap_layer` writes.

### 4. The API key

The plugin must always bill **the user's own provider key**. Set it in
GeoAgent Settings → Model, or export `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` before
launching KADAS.

---

## Verifying the install

```bash
# plugin is discoverable
ls -l ~/.local/share/Kadas/Kadas/profiles/default/python/plugins/kadas_geoagent
# the editable pointer and the deps are in the 3.13 tree
cat ~/.open_geoagent/venv_py3.13/lib/python3.13/site-packages/_geoagent_dev.pth
ls -d ~/.open_geoagent/venv_py3.13/lib/python3.13/site-packages/strands
# the DTM reads
gdalinfo <kadas src>/share/geodata/dtm_analysis.tif | head -3
```

> **Do not verify with `venv_py3.13/bin/python`.** uv leaves that symlink pointing at
> the *system* interpreter (3.10 here), so it reads `lib/python3.10/site-packages` and
> reports a spurious `ModuleNotFoundError: strands`. KADAS never uses that symlink — it
> runs its own bundled 3.13 and only prepends the `site-packages` directory. Inspect the
> directory, don't run the interpreter.

In KADAS: the **GeoAgent** ribbon entry appears, and the dock opens with
`Model: <provider>` rather than `(loading…)`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "4 invalid layers" at startup | Missing `dtm_analysis.tif` (see §3) |
| Plugin absent from the ribbon | Symlink missing, or KADAS not restarted |
| `ModuleNotFoundError: geoagent` | `venv_py3.13` not provisioned — open Settings → Dependencies |
| Terrain tools say "No heightmap is set" | Load the DTM, then `set_heightmap_layer` |
| Edits have no effect | Python caches modules — restart KADAS |
