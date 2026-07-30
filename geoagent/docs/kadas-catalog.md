---
name: kadas-catalog
description: KADAS layer catalog browser
triggers: [catalog, browser, layer tree, add layer]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: KADAS layer catalog browser

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasArcGisPortalCatalogProvider (KadasCatalogProvider)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void load();
```

<sub>source: `python/kadasgui/auto_generated/catalog/kadasarcgisportalcatalogprovider.sip.in`</sub>

## KadasArcGisRestCatalogProvider (KadasCatalogProvider)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void load();
```

<sub>source: `python/kadasgui/auto_generated/catalog/kadasarcgisrestcatalogprovider.sip.in`</sub>

## KadasCatalogBrowser (QWidget)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
void addProvider( KadasCatalogProvider *provider );
QStandardItem *addItem( QStandardItem *parent, QString text, int sortIndex, bool isLeaf = false, QMimeData *mimeData = 0 );
void reload();
void layerSelected( const QgsMimeDataUtils::Uri &uri, const QString &metadataUrl, const QVariantList &sublayers );
```

<sub>source: `python/kadasgui/auto_generated/kadascatalogbrowser.sip.in`</sub>

## KadasCatalogProvider (QObject)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void load() = 0;
void finished();
QList<QDomNode> childrenByTagName( const QDomElement &element, const QString &tagName ) const;
QMap<QString, QString> parseWMTSTileMatrixSets( const QDomDocument &doc ) const;
QStringList parseWMSFormats( const QDomDocument &doc ) const;
QString parseWMSNestedLayer( const QDomNode &layerItem ) const;
QStandardItem *getCategoryItem( const QStringList &titles, const QStringList &sortIndices );
```

<sub>source: `python/kadasgui/auto_generated/kadascatalogprovider.sip.in`</sub>

## KadasGeoAdminRestCatalogProvider (KadasCatalogProvider)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void load();
```

<sub>source: `python/kadasgui/auto_generated/catalog/kadasgeoadminrestcatalogprovider.sip.in`</sub>

## KadasVBSCatalogProvider (KadasCatalogProvider)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void load();
```

<sub>source: `python/kadasgui/auto_generated/catalog/kadasvbscatalogprovider.sip.in`</sub>
