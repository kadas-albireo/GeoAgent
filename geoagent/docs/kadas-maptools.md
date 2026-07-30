---
name: kadas-maptools
description: KADAS map tools (interactive canvas tools)
triggers: [maptool, map tool, click, digitize, measure, interactive, pick]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: KADAS map tools (interactive canvas tools)

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasMapToolDeleteItems (QgsMapToolExtent)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void activate();
void deleteItems( const QgsRectangle &filterRect );
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptooldeleteitems.sip.in`</sub>

## KadasMapToolHeightProfile (KadasShapeCaptureMapTool)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void canvasMoveEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
virtual void activate();
virtual void deactivate();
void setGeometry( const QgsAbstractGeometry &geom, const QgsCoordinateReferenceSystem &crs );
void setMarkerPos( double distance );
void pickLine();
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolheightprofile.sip.in`</sub>

## KadasMapToolHillshade (QgsMapToolExtent)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
void compute( const QgsRectangle &extent, const QgsCoordinateReferenceSystem &crs );
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolhillshade.sip.in`</sub>

## KadasMapToolMeasure (KadasShapeCaptureMapTool)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void activate();
virtual void deactivate();
virtual void canvasPressEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolmeasure.sip.in`</sub>

## KadasMapToolMinMax (KadasShapeCaptureMapTool)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
void setFilterType( FilterType filterType );
void runMinMax( const QgsGeometry &geometry, const QgsCoordinateReferenceSystem &crs );
virtual void activate();
virtual void deactivate();
virtual void canvasPressEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
```

- `runMinMax` — Runs the min/max computation against an externally-supplied geometry (e.g. picked from a feature).

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolminmax.sip.in`</sub>

## KadasMapToolPan (QgsMapTool)

A map tool for panning the map. @see :py:class:`QgsMapTool`

**Methods:**

```cpp
virtual void activate();
virtual void deactivate();
virtual void canvasPressEvent( QgsMapMouseEvent *e );
virtual void canvasMoveEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
virtual bool gestureEvent( QGestureEvent *event );
void contextMenuRequested( QPoint screenPos, QgsPointXY mapPos );
void itemPicked( const KadasFeaturePicker::PickResult &result );
void pinchTriggered( QPinchGesture *gesture );
```

- `canvasPressEvent` — Overridden mouse press event
- `canvasMoveEvent` — Overridden mouse move event
- `canvasReleaseEvent` — Overridden mouse release event
- `pinchTriggered` — Flag to indicate whether mouseRelease is a click (i.e. no moves inbetween)

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolpan.sip.in`</sub>

## KadasMapToolSelectRect (QgsMapTool)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
void setRect( const QgsRectangle &rect );
const QgsRectangle &rect() const;
void clear();
void setAllowResize( bool allowResize );
void setShowReferenceWhenMoving( bool showReference );
virtual void canvasMoveEvent( QgsMapMouseEvent *e );
virtual void canvasPressEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
virtual void deactivate();
void rectChanged( const QgsRectangle &rect );
void rectChangeComplete( const QgsRectangle &rect );
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolselectrect.sip.in`</sub>

## KadasMapToolSlope (QgsMapToolExtent)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
void compute( const QgsRectangle &extent, const QgsCoordinateReferenceSystem &crs );
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolslope.sip.in`</sub>

## KadasShapeCaptureMapTool (QgsMapTool)

Shape-capture map tool: rectangle, circle, sector, polyline, polygon. Emits `shapeCaptured` with the geometry in the canvas destination CRS. The rubber band stays visible after capture until `clear` or a new capture starts.

**Static:**

```cpp
static QgsGeometry circlePolygon( const QgsPointXY &center, double radius, int segments = 64 );
static QgsGeometry sectorPolygon( const QgsPointXY &center, double radius, double startAngle, double stopAngle, int segments = 64 );
```

- `circlePolygon` — Builds a closed polygon ring approximating a circle, in the CRS of `center`.
- `sectorPolygon` — Pie-slice polygon from `startAngle` to `stopAngle` (radians CCW from east); a sweep of 2*pi or more yields a full circle.

**Methods:**

```cpp
void setShape( Shape shape );
Shape shape() const;
void clear();
void setGeodesicPreview( bool enabled );
void setCircleRadius( double radius );
QgsPointXY circleCenter() const;
double circleRadius() const;
double sectorStartAngle() const;
double sectorStopAngle() const;
bool isCapturing() const;
void setCapturedPolyline( const QVector<QgsPointXY> &vertices );
void addPoint( const QgsPointXY &pos );
QgsGeometry previewGeometry() const;
virtual void canvasPressEvent( QgsMapMouseEvent *e );
virtual void canvasMoveEvent( QgsMapMouseEvent *e );
virtual void canvasReleaseEvent( QgsMapMouseEvent *e );
virtual void canvasDoubleClickEvent( QgsMapMouseEvent *e );
virtual void activate();
virtual void deactivate();
void shapeCaptured( const QgsGeometry &geometry, const QgsCoordinateReferenceSystem &crs );
void cleared();
void previewChanged();
```

- `clear` — Removes any rubber band and resets capture state.
- `setGeodesicPreview` — When enabled, poly previews are drawn as densified geodesic segments (display only).
- `setCircleRadius` — Replaces the displayed circle / sector preview (Circle and Sector modes). New radius is in canvas map units.
- `circleCenter` — Center of the last captured circle / sector, or last anchor point.
- `sectorStartAngle` — Start angle of the last captured sector, in radians CCW from east (Sector mode).
- `sectorStopAngle` — Stop angle of the last captured sector, in radians; stopAngle - startAngle >= 2*pi means full circle.
- `isCapturing` — True while the user is actively capturing (mid-drag for rect/circle, mid-vertex-stream for poly).
- `setCapturedPolyline` — Replaces the poly preview with `vertices` (canvas CRS); does not emit `KadasShapeCaptureMapTool.shapeCaptured`.
- `addPoint` — Adds a point as if the user had left-clicked at `pos` (canvas CRS).
- `previewGeometry` — Geometry currently shown by the rubber band, in canvas CRS (includes the floating cursor vertex while capturing).
- `previewChanged` — Emitted whenever the displayed shape preview changes (mouse move, numeric input, programmatic updates).

<sub>source: `python/kadasgui/auto_generated/maptools/kadasshapecapturemaptool.sip.in`</sub>

## KadasViewshedDialog (QDialog)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
double observerHeight() const;
double targetHeight() const;
bool observerHeightRelativeToGround() const;
bool targetHeightRelativeToGround() const;
double observerMinVertAngle() const;
double observerMaxVertAngle() const;
int accuracyFactor() const;
void radiusChanged( double radius );
```

<sub>source: `python/kadasgui/auto_generated/maptools/kadasmaptoolviewshed.sip.in`</sub>
