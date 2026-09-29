# PythoFetch Art Database Build Tool

## Purpose

`Build_PythoFetchArtDB_1.0.0.py` maintains the editable artwork sources and compiles them into versioned SQLite databases.

The tool merges:

```text
PythoFetchArtAssets/ArtAssetsNeofetch
PythoFetchArtAssets/ArtAssetsPythoFetch
```

and produces:

```text
PythoFetchArtAssets/ArtAssetsDB/PythoFetchArt_<version>.db
PythoFetchArtAssets/ArtAssetsDB/PythoFetchArtDB_Manifest.json
```

## Current Fixed Values

```text
Build Tool version: 1.0.0
Database schema:    1
Manifest schema:    1
```

These are separate values and are not automatically bumped.

## Location and Execution

The canonical tool lives at:

```text
SourceCode/PythoFetch/PythoFetchBuildTools/
Build_PythoFetchArtDB_1.0.0.py
```

Unlike the platform and manifest Build Tools, this one runs directly from `PythoFetchBuildTools`.

It is not copied into a version folder.

## Artwork Families

Logical families:

```text
Windows
Linux
macOS
Other
```

Filesystem folders:

```text
Windows -> Windows
Linux   -> Linux
macOS   -> MacOS
Other   -> Other
```

## NeoFetch Source

NeoFetch-derived artwork can be rebuilt from the ProjectHomelab NeoFetch mirror under:

```text
Resources/ThirdParty/Neofetch
```

The generated editable source retains NeoFetch licensing material.

## PythoFetch Native Artwork

Native ProjectHomelab artwork lives under:

```text
PythoFetchArtAssets/ArtAssetsPythoFetch/
```

Its `Catalogue.json` describes entries and their metadata.

Normal variants include:

```text
default
small
old
```

`old` is retained for historical/reference use and is not selected automatically by PythoFetch 1.0.0.

## Database Build

The tool validates both artwork sources, merges them, builds a staging SQLite database, checks database integrity, vacuums it, validates it again, and promotes the final:

```text
PythoFetchArt_<version>.db
```

The database contains artwork, aliases, and metadata required by PythoFetch.

## Database Manifest

```text
PythoFetchArtDB_Manifest.json
```

records database versions and verification metadata.

A database entry can contain:

```text
file
download_url
sha256
size_bytes
created_utc
schema_version
compiler_version
artwork_count
source_counts
family_counts
```

## Python-Source Recovery

When Python-source PythoFetch cannot find a valid local database, it directly downloads:

```text
PythoFetchArtDB_Manifest.json
```

It selects the newest entry whose:

```text
schema_version
```

matches:

```text
ART_DATABASE_SCHEMA_VERSION
```

The database itself is downloaded and checked against:

```text
sha256
size_bytes
```

before SQLite validation.

This recovery path does not use `PythoFetch_Source_Manifest.json`.

## Recommended Artwork Workflow

```text
1. Add/edit artwork under ArtAssetsPythoFetch.
2. Update ArtAssetsPythoFetch/Catalogue.json.
3. Run Build_PythoFetchArtDB_1.0.0.py from PythoFetchBuildTools.
4. Choose the intended database version.
5. Test the generated database.
6. Run Build_PythoFetchManifests_1.0.0.py from SourceCode/PythoFetch.
7. Remove the copied manifest Build Tool.
8. Commit the source assets, DB, and rebuilt manifests.
```

Do not hand-edit the compiled SQLite database as the normal artwork-editing workflow.
