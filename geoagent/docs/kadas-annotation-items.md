---
name: kadas-annotation-items
description: KADAS annotation items: the objects you create (marker, circle, line, MilX)
triggers: [annotation, marker, pin, circle, rectangle, polygon, line, redline, draw, symbol, gpx, waypoint, picture, text, label]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: KADAS annotation items: the objects you create (marker, circle, line, MilX)

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasAnnotationItemContext

Bundles the per-call context that KadasAnnotationItemController needs for map-space ↔ item-space transforms.

**Methods:**

```cpp
QgsAnnotationLayer *layer() const;
const QgsMapSettings &mapSettings() const;
QgsCoordinateReferenceSystem itemCrs() const;
```

- `layer` — Owning annotation layer.
- `mapSettings` — Map canvas settings; `KadasAnnotationItemContext.destinationCrs` is the map CRS.
- `itemCrs` — CRS of the item, i.e. the parent annotation layer's CRS.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasannotationitemcontext.sip.in`</sub>

## KadasCircleAnnotationItem (QgsAnnotationPolygonItem)

Circle annotation item (type id "kadas:circle").

**Static:**

```cpp
static QString itemTypeId();
static KadasCircleAnnotationItem *create();
```

**Methods:**

```cpp
QgsPointXY center() const;
QgsPointXY ringPoint() const;
void setCenter( const QgsPointXY &center );
void setRingPoint( const QgsPointXY &ringPoint );
const QStringList &shadowIds() const;
void setShadowIds( const QStringList &ids );
void setCircle( const QgsPointXY &center, const QgsPointXY &ringPoint );
double radius() const;
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadascircleannotationitem.sip.in`</sub>

## KadasCoordCrossAnnotationItem (QgsAnnotationMarkerItem)

"Coordinate cross" annotation item (type id "kadas:coordcross").

**Static:**

```cpp
static QString itemTypeId();
static QgsCoordinateReferenceSystem labelCrs( const QgsCoordinateReferenceSystem &layerCrs );
static KadasCoordCrossAnnotationItem *create();
```

- `labelCrs` — Snapping/labelling CRS: layerCrs if metric, else EPSG:3857 (degrees would round to 0/0).

**Methods:**

```cpp
const QStringList &shadowIds() const;
void setShadowIds( const QStringList &ids );
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadascoordcrossannotationitem.sip.in`</sub>

## KadasGpxRouteAnnotationItem (QgsAnnotationLineItem)

Annotation item for a GPX route (type id "kadas:gpxroute").

**Static:**

```cpp
static QString itemTypeId();
static KadasGpxRouteAnnotationItem *create();
```

**Methods:**

```cpp
QString name() const;
void setName( const QString &name );
QString number() const;
void setNumber( const QString &number );
QFont labelFont() const;
void setLabelFont( const QFont &font );
QColor labelColor() const;
void setLabelColor( const QColor &color );
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasgpxrouteannotationitem.sip.in`</sub>

## KadasGpxWaypointAnnotationItem (QgsAnnotationMarkerItem)

Annotation item for a GPX waypoint (type id "kadas:gpxwaypoint").

**Static:**

```cpp
static QString itemTypeId();
static KadasGpxWaypointAnnotationItem *create();
```

**Methods:**

```cpp
QString name() const;
void setName( const QString &name );
QFont labelFont() const;
void setLabelFont( const QFont &font );
QColor labelColor() const;
void setLabelColor( const QColor &color );
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasgpxwaypointannotationitem.sip.in`</sub>

## KadasMapToolEditAnnotationItem (QgsMapTool)

Map tool to create/edit a :py:class:`QgsAnnotationItem` on a :py:class:`QgsAnnotationLayer` via a KadasAnnotationItemController.

**Methods:**

```cpp
virtual void activate();
virtual void deactivate();
virtual void canvasPressEvent( QgsMapMouseEvent *e );
virtual void canvasMoveEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
virtual void canvasDoubleClickEvent( QgsMapMouseEvent *e );
void setMultipart( bool multipart );
void setExtraTopWidget( QWidget *widget );
QgsAnnotationItem *currentItem() const;
void addPoint( const QgsPointXY &pos );
void partFinished();
void cleared();
```

- `setMultipart` — Create-mode: when true, finalized parts accumulate on the same item; default false.
- `setExtraTopWidget` — Inserts a custom widget into the bottom-bar top row; call before `KadasMapToolEditAnnotationItem.activate`, ownership transfers.
- `currentItem` — The annotation item the tool is currently driving (may be null).
- `addPoint` — Create-mode: place a vertex at `pos` as if left-clicked; no-op in edit mode.
- `partFinished` — Create-mode: emitted whenever a part is finalized.
- `cleared` — Create-mode: emitted after a fresh item replaces the previous one.

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptooleditannotationitem.sip.in`</sub>

## KadasPinAnnotationItem (QgsAnnotationMarkerItem)

"Pin" annotation item (type id "kadas:pin").

**Static:**

```cpp
static QString itemTypeId();
static KadasPinAnnotationItem *create();
static QString defaultIconPath();
```

**Methods:**

```cpp
QString name() const;
void setName( const QString &name );
QString remarks() const;
void setRemarks( const QString &remarks );
const QStringList &shadowIds() const;
void setShadowIds( const QStringList &ids );
```

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadaspinannotationitem.sip.in`</sub>

## KadasRectangleAnnotationItem (QgsAnnotationPolygonItem)

Rotated rectangle annotation item (type id "kadas:rectangle").

**Static:**

```cpp
static QString itemTypeId();
static KadasRectangleAnnotationItem *create();
```

**Methods:**

```cpp
QgsPointXY center() const;
QSizeF size() const;
double angle() const;
QgsCoordinateReferenceSystem drawCrs() const;
QgsCoordinateReferenceSystem layerCrs() const;
void setBox( const QgsPointXY &center, const QSizeF &size, double angleDegrees );
void setBox( const QgsPointXY &center, const QSizeF &size, double angleDegrees, const QgsCoordinateReferenceSystem &drawCrs, const QgsCoordinateReferenceSystem &layerCrs );
void setCenter( const QgsPointXY &center );
void setSize( const QSizeF &size );
void setAngle( double angleDegrees );
QVector<QgsPointXY> corners() const;
QgsPointXY rotationHandle() const;
const QStringList &shadowIds() const;
void setShadowIds( const QStringList &ids );
```

- `drawCrs` — CRS in which size and angle are expressed (invalid = legacy).
- `layerCrs` — Parent layer CRS, used to project corners from drawCrs (invalid = legacy).
- `setBox` — Legacy overload: axis-aligned layout in the layer CRS.
- `corners` — Corners in CCW order: BL, BR, TR, TL.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasrectangleannotationitem.sip.in`</sub>
