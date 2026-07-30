---
name: kadas-search
description: KADAS search providers and location search
triggers: [search, locate, find, place, geocode, provider]
generated_from: kadas-albireo2 SIP bindings
---

# KADAS: KADAS search providers and location search

**Generated from the SIP bindings — these are the real signatures Python can call.** Do not infer methods that are not listed here; if a class or method is absent, it is not bound and calling it raises AttributeError.

## KadasAlternateGotoLocatorFilter (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual QString prefix() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
virtual void clearPreviousResults();
```

<sub>source: `python/kadasgui/auto_generated/search/kadasalternategotolocatorfilter.sip.in`</sub>

## KadasCoordinateSearchProvider (KadasSearchProvider)

************************************************************************* This program is free software; you can redistribute it and/or modify  * it under the terms of the GNU General Public License as published by  * the Free Software Foundation; either version 2 of the License, or     * (at your option) any later version.                                   * **************************************************************************

**Methods:**

```cpp
virtual void startSearch( const QString &searchtext, const SearchRegion &searchRegion );
```

<sub>source: `python/kadasgui/auto_generated/search/kadascoordinatesearchprovider.sip.in`</sub>

## KadasLocalDataSearchFilter (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
```

<sub>source: `python/kadasgui/auto_generated/search/kadaslocaldatasearchprovider.sip.in`</sub>

## KadasLocationSearchFilter (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Static:**

```cpp
static QgsFillSymbol *createPolygonSymbol();
```

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
virtual void clearPreviousResults();
```

<sub>source: `python/kadasgui/auto_generated/search/kadaslocationsearchprovider.sip.in`</sub>

## KadasMapServerFindSearchProvider (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
virtual void clearPreviousResults();
```

<sub>source: `python/kadasgui/auto_generated/search/kadasmapserverfindsearchprovider.sip.in`</sub>

## KadasPinSearchProvider (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
```

<sub>source: `python/kadasgui/auto_generated/search/kadaspinsearchprovider.sip.in`</sub>

## KadasRemoteDataSearchProvider (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
virtual void clearPreviousResults();
```

<sub>source: `python/kadasgui/auto_generated/search/kadasremotedatasearchprovider.sip.in`</sub>

## KadasSearchProvider (QObject)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual void startSearch( const QString &searchtext, const SearchRegion &searchRegion ) = 0;
virtual void cancelSearch();
```

<sub>source: `python/kadasgui/auto_generated/kadassearchprovider.sip.in`</sub>

## KadasWorldLocationSearchProvider (QgsLocatorFilter)

************************************************************************* This program is free software; you can redistribute it and/or modify * it under the terms of the GNU General Public License as published by * the Free Software Foundation; either version 2 of the License, or * (at your option) any later version. * **************************************************************************

**Methods:**

```cpp
virtual QString name() const;
virtual QString displayName() const;
virtual Priority priority() const;
virtual void fetchResults( const QString &string, const QgsLocatorContext &context, QgsFeedback *feedback );
virtual void triggerResult( const QgsLocatorResult &result );
virtual void clearPreviousResults();
```

<sub>source: `python/kadasgui/auto_generated/search/kadasworldlocationsearchprovider.sip.in`</sub>
