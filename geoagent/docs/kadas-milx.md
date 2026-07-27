---
name: kadas-milx
description: MilX/MSS military symbology: what is and is not bound to Python
triggers: [milx, mss, military, symbol, tactical, app-6, sidc, nato, infantry, unit]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: MilX/MSS military symbology: what is and is not bound to Python

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasMilxAnnotationController (KadasAnnotationItemController)

Controller for KadasMilxAnnotationItem (type id "kadas:milx").

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
virtual bool hitTest( const QgsAnnotationItem *item, const QgsPointXY &pos, const KadasAnnotationItemContext &ctx ) const;
virtual void populateContextMenu( QgsAnnotationItem *item, QMenu *menu, const KadasEditContext &editContext, const QgsPointXY &clickPos, const KadasAnnotationItemContext &ctx );
virtual void onDoubleClick( QgsAnnotationItem *item, const KadasAnnotationItemContext &ctx );
```

- `liveRepaintOnEdit` — Re-render the layer live while dragging (the outline band is a poor stand-in for the symbol).

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasmilxannotationcontroller.sip.in`</sub>

## KadasMilxAnnotationItem (QgsAnnotationItem)

Kadas MilX (military symbology) annotation item. Holds an MSS string and a list of WGS84 points; rendering, hit-testing and editing delegate to KadasMilxClient. Type id: "kadas:milx".

**Static:**

```cpp
static QString itemTypeId();
static KadasMilxAnnotationItem *create();
static KadasMilxAnnotationItem *fromMilx( const QDomElement &itemElement, const QgsCoordinateTransform &crst, int symbolSize );
static int exportLayerToMilxly( QgsAnnotationLayer *annoLayer, QDomElement &milxLayerEl, int dpi );
static bool importLayerFromMilxly( QgsAnnotationLayer *annoLayer, const QDomElement &milxLayerEl, int dpi, const QgsCoordinateTransformContext &transformContext, QString &errorMsg );
static QRect computeScreenExtent( const QgsMapSettings &mapSettings );
```

- `fromMilx` — Construct a KadasMilxAnnotationItem from a `<MilXGraphic>` element. `crst` projects source coordinates to EPSG:4326; caller takes ownership.
- `exportLayerToMilxly` — Serialize all `kadas:milx` items in `annoLayer` into `milxLayerEl` as a `<MilXLayer>` block. Returns the number of items emitted.
- `importLayerFromMilxly` — Populate `annoLayer` with `kadas:milx` items parsed from `milxLayerEl`. Returns true on success; sets `errorMsg` on failure.
- `computeScreenExtent` — On-screen extent of `mapSettings`' visible map extent (in device pixels).

**Methods:**

```cpp
void writeMilx( QDomDocument &doc, QDomElement &itemElement, int symbolSize ) const;
QString mssString() const;
void setMssString( const QString &mssString );
QString militaryName() const;
void setMilitaryName( const QString &militaryName );
QString symbolType() const;
void setSymbolType( const QString &symbolType );
int minNumPoints() const;
void setMinNumPoints( int minNumPoints );
bool hasVariablePoints() const;
void setHasVariablePoints( bool hasVariablePoints );
QList<QgsPointXY> points() const;
void setPoints( const QList<QgsPointXY> &points );
QList<int> controlPoints() const;
void setControlPoints( const QList<int> &cp );
QPoint userOffset() const;
void setUserOffset( const QPoint &offset );
int pressedPoints() const;
void setPressedPoints( int n );
DrawStatus drawStatus() const;
void setDrawStatus( DrawStatus s );
bool isMultiPoint() const;
```

- `writeMilx` — Write this item as a `<MilXGraphic>` DOM element (legacy MilXly schema). `symbolSize` is the layer's symbol size in px (for the user-offset factor).
- `points` — Points, stored in EPSG:4326 (MilX is always WGS84).
- `controlPoints` — Indices into `KadasMilxAnnotationItem.points` that libmss reports as draggable control points.
- `userOffset` — User-applied screen-space offset (drag of the symbol graphic).
- `pressedPoints` — Number of physical clicks made during interactive draw.
- `isMultiPoint` — True when the symbol has more than one geometry point or carries a shape attribute.

<sub>source: `python/kadasgui/auto_generated/annotationitems/kadasmilxannotationitem.sip.in`</sub>

## KadasMilxLayerPropertiesPage (QgsMapLayerConfigWidget)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void apply();
```

<sub>source: `python/kadasgui/auto_generated/milx/kadasmilxlayerpropertiespage.sip.in`</sub>

## KadasMilxLayerPropertiesPageFactory (QObject, QgsMapLayerConfigWidgetFactory)

**Methods:**

```cpp
virtual QgsMapLayerConfigWidget *createWidget( QgsMapLayer *layer, QgsMapCanvas *canvas, bool dockWidget, QWidget *parent ) const;
virtual QString title() const;
virtual bool supportLayerPropertiesDialog() const;
virtual bool supportsLayer( QgsMapLayer *layer ) const;
```

<sub>source: `python/kadasgui/auto_generated/milx/kadasmilxlayerpropertiespage.sip.in`</sub>

## KadasMilxLibrary (QFrame)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
void focusFilter();
void symbolSelected( const KadasMilxSymbolDesc &symbolDesc );
void visibilityChanged( bool visible );
void showEvent( QShowEvent * );
void hideEvent( QHideEvent * );
```

<sub>source: `python/kadasgui/auto_generated/milx/kadasmilxlibrary.sip.in`</sub>

## NOT available from Python

### KadasMilxClient

Lives in kadas/gui/milx/kadasmilxclient.h and owns the symbol lookup (getSymbolMetadata, getMilitaryName, validateSymbolXml, init). It is NOT in any .sip.in, so **Python cannot call it**. This is why a symbol cannot be resolved from a name/ID in Python: the item can be built, but the MSS string it needs cannot be looked up. Binding this class would unblock a real MilX tool.
