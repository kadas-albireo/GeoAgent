---
name: kadas-annotation-layers
description: KADAS annotation layers: registry, helpers, project integration, styling
triggers: [annotation layer, layer registry, style editor, project integration, layer helpers]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: KADAS annotation layers: registry, helpers, project integration, styling

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasAnnotationLayerHelpers

Static helpers for attaching Kadas-specific per-item metadata to a stock :py:class:`QgsAnnotationLayer`.

**Static:**

```cpp
static bool isParametricLayer( const QgsAnnotationLayer *layer );
static QString tooltip( const QgsAnnotationLayer *layer, const QString &itemId );
static void setTooltip( QgsAnnotationLayer *layer, const QString &itemId, const QString &tooltip );
static QgsAnnotationLayer *createLayer( const QString &name, const QgsCoordinateReferenceSystem &preferredCrs = QgsCoordinateReferenceSystem() );
static void prepareLayerForSave( QgsAnnotationLayer *layer );
static void stripShadowsFromLayer( QgsAnnotationLayer *layer );
static void reconstructOrphanCrosses( QgsAnnotationLayer *layer );
```

- `isParametricLayer` — `True` if `layer` is a parametric Kadas annotation layer (carries the kadas/annotation-type customProperty).
- `tooltip` — Tooltip stored for `itemId` on `layer`, or empty.
- `setTooltip` — Sets `tooltip` for `itemId`; empty removes it.
- `createLayer` — Creates a :py:class:`QgsAnnotationLayer` named `name` (using `preferredCrs`, else project CRS, else EPSG:3857). Not added to the project.
- `prepareLayerForSave` — Generates and inserts QGIS-compat shadow items for every master item. Call before `QgsProject.write()`. Idempotent.
- `stripShadowsFromLayer` — Removes shadow items and clears master shadow id lists. Call after `QgsProject.write()` and after `KadasAnnotationLayerHelpers.read`.
- `reconstructOrphanCrosses` — Rebuilds coordinate-cross items orphaned by a vanilla-QGIS round trip (unknown master type dropped, stock shadows kept), recovering position from the shadow marker. Consumes the orphan side-channel. Call after `KadasAnnotationLayerHelpers.read`.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationlayerhelpers.sip.in`</sub>

## KadasAnnotationLayerRegistry (QObject)

Process-wide registry of the well-known singleton Kadas :py:class:`QgsAnnotationLayer` instances inside the current :py:class:`QgsProject`.

**Static:**

```cpp
static QgsAnnotationLayer *getOrCreateAnnotationLayer( StandardLayer layer );
static void init();
```

- `getOrCreateAnnotationLayer` — Returns the standard annotation layer for `layer`, creating it on first use.
- `init` — Connects to project signals; must be called once at app startup.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationlayerregistry.sip.in`</sub>

## KadasAnnotationProjectIntegration (QObject)

Wires the save-time shadow mechanism into the active :py:class:`QgsProject`.

**Methods:**

```cpp
void prepareForSave();
void stripAfterSave();
```

- `prepareForSave` — Calls `KadasAnnotationProjectIntegration.prepareLayerForSave` on every annotation layer in the project.
- `stripAfterSave` — Calls `KadasAnnotationProjectIntegration.stripShadowsFromLayer` on every annotation layer in the project.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationprojectintegration.sip.in`</sub>

## KadasAnnotationStyleEditor (QWidget)

Per-type style editor widget for a stock :py:class:`QgsAnnotationItem`.

**Methods:**

```cpp
virtual void loadFromItem( const QgsAnnotationItem *item ) = 0;
virtual void applyToItem( QgsAnnotationItem *item ) const = 0;
void previewChanged();
void committed();
```

- `loadFromItem` — Populates the widgets from `item`'s current state.
- `applyToItem` — Writes the widgets' state back into `item`.
- `previewChanged` — Emitted continuously while the user is interacting (live preview).
- `committed` — Emitted when a discrete edit is finalized (push history + persist).

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationstyleeditor.sip.in`</sub>
