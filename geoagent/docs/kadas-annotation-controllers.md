---
name: kadas-annotation-controllers
description: KADAS annotation controllers: interactive click-to-draw editing
triggers: [controller, interactive, click to draw, edit annotation, digitize]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: KADAS annotation controllers: interactive click-to-draw editing

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasAnnotationControllerRegistry

Process-wide registry mapping :py:class:`QgsAnnotationItem` type ids to their Kadas controller.

**Static:**

```cpp
static KadasAnnotationControllerRegistry *instance();
```

- `instance` — Returns the process-wide registry instance.

**Methods:**

```cpp
void addController( KadasAnnotationItemController *controller );
KadasAnnotationItemController *controllerFor( const QString &typeId ) const;
QStringList registeredTypes() const;
```

- `addController` — Registers `controller` under its `KadasAnnotationControllerRegistry.itemType`; takes ownership and replaces any existing.
- `controllerFor` — Returns the controller for type id `typeId`, or None.
- `registeredTypes` — Registered type ids, in registration order.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationcontrollerregistry.sip.in`</sub>

## KadasAnnotationItemController

Per-type controller for :py:class:`QgsAnnotationItem` instances managed by Kadas.

**Static:**

```cpp
static QgsPointXY toMapPos( const QgsPointXY &itemPos, const KadasAnnotationItemContext &ctx );
static QgsPointXY toItemPos( const QgsPointXY &mapPos, const KadasAnnotationItemContext &ctx );
static QgsRectangle toItemRect( const QgsRectangle &mapRect, const KadasAnnotationItemContext &ctx );
static QgsRectangle toMapRect( const QgsRectangle &itemRect, const KadasAnnotationItemContext &ctx );
static double pickTolSqr( const KadasAnnotationItemContext &ctx );
```

**Methods:**

```cpp
virtual QString itemType() const = 0;
virtual QString itemName() const = 0;
virtual QgsAnnotationItem *createItem() const = 0;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const = 0;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx ) = 0;
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) = 0;
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx ) = 0;
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) = 0;
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) = 0;
virtual void endPart( QgsAnnotationItem *item ) = 0;
virtual KadasAttribDefs drawAttribs() const = 0;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const = 0;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const = 0;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const = 0;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx ) = 0;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) = 0;
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const = 0;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const = 0;
virtual void populateContextMenu( QgsAnnotationItem *item, QMenu *menu, const KadasEditContext &editContext, const QgsPointXY &clickPos, const KadasAnnotationItemContext &ctx );
virtual void onDoubleClick( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual QgsGeometry representativeGeometry( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool liveRepaintOnEdit() const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const = 0;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos ) = 0;
virtual void translate( QgsAnnotationItem *item, double dx, double dy ) = 0;
virtual bool hitTest( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual bool intersects( const QgsAnnotationItem *item, const QgsRectangle &mapRect, const KadasAnnotationItemContext &ctx, bool contains = false ) const;
virtual void applyPersistedStyle( QgsAnnotationItem *item ) const;
virtual void persistStyle( const QgsAnnotationItem *item ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
virtual QList<QgsAnnotationItem *> generateShadows( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual QStringList shadowIds( const QgsAnnotationItem *item ) const;
virtual void setShadowIds( QgsAnnotationItem *item, const QStringList &ids ) const;
```

- `itemType` — :py:class:`QgsAnnotationItem` type id this controller handles (e.g. "marker", "kadas:circle").
- `itemName` — Human-readable name for the item kind (used by UI; tr-able).
- `createItem` — Creates a fresh annotation item. Caller takes ownership.
- `startPart` — Begins a new part at `firstPoint`. Returns true if the item is ready to receive subsequent points.
- `representativeGeometry` — Geometry (item CRS) for the edit tool's rubber-band preview. Mirrors `QgsAnnotationItemEditOperationTransientResults.representativeGeometry()`.
- `liveRepaintOnEdit` — When `True`, the edit tool re-renders the layer on every drag step (e.g. pictures) rather than only on release.
- `applyPersistedStyle` — Applies persisted style defaults to `item` on creation.
- `persistStyle` — Stores `item`'s current style as the new persisted defaults.
- `createStyleEditor` — Returns a style editor widget for this item type, or None if none. Caller takes ownership.
- `generateShadows` — Returns freshly allocated shadow items for QGIS compatibility; caller takes ownership.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationitemcontroller.sip.in`</sub>

## KadasCircleAnnotationController (KadasAnnotationItemController)

Controller for KadasCircleAnnotationItem (type id "kadas:circle").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
virtual QList<QgsAnnotationItem *> generateShadows( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual QStringList shadowIds( const QgsAnnotationItem *item ) const;
virtual void setShadowIds( QgsAnnotationItem *item, const QStringList &ids ) const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadascircleannotationcontroller.sip.in`</sub>

## KadasCoordCrossAnnotationController (KadasMarkerAnnotationController)

Controller for KadasCoordCrossAnnotationItem (type id "kadas:coordcross").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual QList<QgsAnnotationItem *> generateShadows( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual QStringList shadowIds( const QgsAnnotationItem *item ) const;
virtual void setShadowIds( QgsAnnotationItem *item, const QStringList &ids ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
virtual void applyPersistedStyle( QgsAnnotationItem * ) const;
virtual void persistStyle( const QgsAnnotationItem * ) const;
```

- `createStyleEditor` — Fixed visual drawn in `KadasCoordCrossAnnotationController.render`; no style editor.
- `applyPersistedStyle` — The cross is drawn in `KadasCoordCrossAnnotationController.render` over a hidden symbol; never adopt or write the shared point style.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadascoordcrossannotationcontroller.sip.in`</sub>

## KadasGpxRouteAnnotationController (KadasLineAnnotationController)

Controller for KadasGpxRouteAnnotationItem (type id "kadas:gpxroute").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasgpxrouteannotationcontroller.sip.in`</sub>

## KadasGpxWaypointAnnotationController (KadasMarkerAnnotationController)

Controller for KadasGpxWaypointAnnotationItem (type id "kadas:gpxwaypoint").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasgpxwaypointannotationcontroller.sip.in`</sub>

## KadasLineAnnotationController (KadasAnnotationItemController)

Controller for stock :py:class:`QgsAnnotationLineItem` (type id "linestring").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual void applyPersistedStyle( QgsAnnotationItem *item ) const;
virtual void persistStyle( const QgsAnnotationItem *item ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadaslineannotationcontroller.sip.in`</sub>

## KadasMarkerAnnotationController (KadasAnnotationItemController)

Controller for stock :py:class:`QgsAnnotationMarkerItem` (type id "marker").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual bool liveRepaintOnEdit() const;
virtual void applyPersistedStyle( QgsAnnotationItem *item ) const;
virtual void persistStyle( const QgsAnnotationItem *item ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
```

- `liveRepaintOnEdit` — Re-render the layer live while dragging (the outline band is a poor stand-in for the symbol).

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasmarkerannotationcontroller.sip.in`</sub>

## KadasPictureAnnotationController (KadasAnnotationItemController)

Controller for stock :py:class:`QgsAnnotationPictureItem` (type id "picture").

**Static:**

```cpp
static void setPath( QgsAnnotationPictureItem *item, const QString &path );
static void ensureBalloon( QgsAnnotationPictureItem *pic );
static int nextPictureZIndex( const QgsAnnotationLayer *layer );
static bool isCalloutVisible( const QgsAnnotationPictureItem *pic );
static void setCalloutVisible( QgsAnnotationPictureItem *pic, bool visible );
static bool lockAspectRatio();
static void setLockAspectRatio( bool on );
```

- `ensureBalloon` — Idempotently installs a balloon callout on `pic` (white fill, 1px black stroke, 4px margins, 6px wedge); a no-op if already present.
- `nextPictureZIndex` — Next zIndex so a freshly created picture stacks above existing pictures in `layer`.
- `isCalloutVisible` — Returns whether the picture's balloon callout is visible. Hidden is encoded as transparent fill+stroke and zero wedge width.
- `setCalloutVisible` — Shows or hides the balloon callout; hiding re-centers the picture on its former anchor.
- `lockAspectRatio` — Session-wide preference: should corner-resize preserve the picture's aspect ratio?

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual QgsGeometry representativeGeometry( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool liveRepaintOnEdit() const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
virtual void populateContextMenu( QgsAnnotationItem *item, QMenu *menu, const KadasEditContext &editContext, const QgsPointXY &clickPos, const KadasAnnotationItemContext &ctx );
```

- `liveRepaintOnEdit` — Re-render the layer live while dragging (the outline band is a poor stand-in for the image).

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadaspictureannotationcontroller.sip.in`</sub>

## KadasPinAnnotationController (KadasMarkerAnnotationController)

Controller for KadasPinAnnotationItem (type id "kadas:pin").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
virtual QList<QgsAnnotationItem *> generateShadows( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual QStringList shadowIds( const QgsAnnotationItem *item ) const;
virtual void setShadowIds( QgsAnnotationItem *item, const QStringList &ids ) const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadaspinannotationcontroller.sip.in`</sub>

## KadasPointTextAnnotationController (KadasAnnotationItemController)

Controller for stock :py:class:`QgsAnnotationPointTextItem` (type id "pointtext").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual void populateContextMenu( QgsAnnotationItem *item, QMenu *menu, const KadasEditContext &editContext, const QgsPointXY &clickPos, const KadasAnnotationItemContext &ctx );
virtual bool liveRepaintOnEdit() const;
virtual void applyPersistedStyle( QgsAnnotationItem *item ) const;
virtual void persistStyle( const QgsAnnotationItem *item ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
```

- `liveRepaintOnEdit` — Re-render the layer live while dragging (the outline band is a poor stand-in for the text).

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadaspointtextannotationcontroller.sip.in`</sub>

## KadasPolygonAnnotationController (KadasAnnotationItemController)

Controller for stock :py:class:`QgsAnnotationPolygonItem` (type id "polygon").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual void applyPersistedStyle( QgsAnnotationItem *item ) const;
virtual void persistStyle( const QgsAnnotationItem *item ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadaspolygonannotationcontroller.sip.in`</sub>

## KadasRectangleAnnotationController (KadasAnnotationItemController)

Controller for KadasRectangleAnnotationItem (type id "kadas:rectangle").

**Methods:**

```cpp
virtual QString itemType() const;
virtual QString itemName() const;
virtual QgsAnnotationItem *createItem() const;
virtual QList<KadasNode> nodes( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual bool startPart( QgsAnnotationItem *item, const QgsPointXY &firstPoint, const KadasAnnotationItemContext &ctx );
virtual bool startPart( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual void setCurrentPoint( QgsAnnotationItem *item, const QgsPointXY &p, const KadasAnnotationItemContext &ctx );
virtual void setCurrentAttributes( QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual bool continuePart( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
virtual void endPart( QgsAnnotationItem *item );
virtual KadasAttribDefs drawAttribs() const;
virtual KadasAttribValues drawAttribsFromPosition( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromDrawAttribs( const QgsAnnotationItem *item, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual KadasEditContext getEditContext( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &newPoint, const KadasAnnotationItemContext &ctx );
virtual void edit( QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx );
virtual KadasAttribValues editAttribsFromPosition( const QgsAnnotationItem *item, const KadasEditContext &editContext, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY positionFromEditAttribs( const QgsAnnotationItem *item, const KadasEditContext &editContext, const KadasAttribValues &values, const KadasAnnotationItemContext &ctx ) const;
virtual QgsPointXY position( const QgsAnnotationItem *item ) const;
virtual void setPosition( QgsAnnotationItem *item, const QgsPointXY &pos );
virtual void translate( QgsAnnotationItem *item, double dx, double dy );
virtual void applyPersistedStyle( QgsAnnotationItem *item ) const;
virtual void persistStyle( const QgsAnnotationItem *item ) const;
virtual KadasAnnotationStyleEditor *createStyleEditor( QWidget *parent = 0 ) const;
virtual QList<QgsAnnotationItem *> generateShadows( const QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx ) const;
virtual QStringList shadowIds( const QgsAnnotationItem *item ) const;
virtual void setShadowIds( QgsAnnotationItem *item, const QStringList &ids ) const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasrectangleannotationcontroller.sip.in`</sub>
