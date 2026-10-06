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
path
url
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

## Database Version Selection and Rebuilds

The requested database version must use `X.Y.Z` format.

If the requested version already exists on disk or in `PythoFetchArtDB_Manifest.json`, the Build Tool treats the operation as an intentional rebuild of that version. This allows corrections to an in-progress release such as `1.0.0` without forcing an artificial version bump.

If the requested version does not already exist, it must be greater than the current latest database version. This prevents creation of a new historical version underneath the current latest.

When an existing version is rebuilt, the Build Tool promotes the replacement transactionally:

```text
1. Build and verify PythoFetchArtNew.db.
2. Prepare the replacement manifest entry.
3. Move the existing target DB to a temporary .previous backup.
4. Promote the verified staging DB to PythoFetchArt_<version>.db.
5. Replace the manifest.
6. Remove the backup after the DB and manifest commit successfully.
```

If promotion fails before the manifest commit completes, the newly promoted target is removed and the previous database is restored from the backup.

Rebuilding an older existing version replaces only that version's record; `latest_version` remains the numerically newest version present.

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
4. Choose an existing database version to rebuild, or a new version greater than the current latest.
5. Test the generated database.
6. Run Build_PythoFetchManifests_1.0.0.py from SourceCode/PythoFetch.
7. Remove the copied manifest Build Tool.
8. Commit the source assets, DB, and rebuilt manifests.
```

Do not hand-edit the compiled SQLite database as the normal artwork-editing workflow.
