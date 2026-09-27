# PythoFetch Art Manager

## Purpose

`PythoFetchArtManager_1.0.0.py` maintains the editable artwork sources used by PythoFetch and compiles them into a versioned SQLite artwork database.

The manager combines two sources:

```text
ArtAssetsNeofetch
ArtAssetsPythoFetch
```

and produces:

```text
ArtAssetsDB/PythoFetchArt_<version>.db
ArtAssetsDB/PythoFetchArtDB_Manifest.json
```

The manager is a development tool. End users of packaged PythoFetch releases normally receive the compiled art database bundled inside the application.

## Current Version

```text
PythoFetch Art Manager 1.0.0
```

The manager version and the database version are separate concepts.

For example:

```text
Manager version : 1.0.0
Database version: 1.0.3
```

The same manager can produce multiple later database versions as artwork changes, provided the database schema remains compatible.

## Expected Folder Layout

```text
PythoFetchArtAssets/
├── PythoFetchArtManager/
│   └── PythoFetchArtManager_1.0.0.py
├── ArtAssetsNeofetch/
│   ├── Windows/
│   ├── Linux/
│   ├── MacOS/
│   ├── Other/
│   ├── Catalogue.json
│   ├── NeoFetch_LICENSE.md
│   └── README.txt
├── ArtAssetsPythoFetch/
│   ├── Windows/
│   ├── Linux/
│   ├── MacOS/
│   ├── Other/
│   └── Catalogue.json
└── ArtAssetsDB/
    ├── PythoFetchArt_<version>.db
    └── PythoFetchArtDB_Manifest.json
```

The logical artwork family is `macOS`, but the corresponding filesystem folder is `MacOS`.

## NeoFetch Source

The NeoFetch-derived art source is generated from the upstream NeoFetch `get_distro_ascii` function.

If the required local NeoFetch extraction source is unavailable, the manager can retrieve the ProjectHomelab NeoFetch mirror.

The mirror used by the manager is under:

```text
Resources/ThirdParty/Neofetch
```

The extracted artwork is converted into:

- individual UTF-8 text files
- family folders
- a curated `Catalogue.json`
- retained NeoFetch license material
- extraction metadata

## Normal Use

The simplest use is to run the manager directly:

```text
python PythoFetchArtManager_1.0.0.py
```

The manager displays the three working areas:

```text
NeoFetch  : ArtAssetsNeofetch
PythoFetch: ArtAssetsPythoFetch
Database  : ArtAssetsDB
```

If no database version is supplied, the manager displays the current latest version and asks for the version of the new database:

```text
Version for new database (x.x.x):
```

The version must use semantic `x.x.x` form and must be greater than all existing database versions known from disk or the manifest.

## Non-Interactive Database Version

A version can be supplied directly:

```text
python PythoFetchArtManager_1.0.0.py --version 1.0.1
```

This avoids the version prompt.

The requested version must still be newer than the current latest database version.

## Refreshing the Database Manifest

The manager can repair or normalize download URLs in the existing manifest without building a new database:

```text
python PythoFetchArtManager_1.0.0.py --refresh-manifest
```

This updates version entries to use the configured ProjectHomelab raw-download location.

It does not create a new art database version.

## Manager Workflow

A normal build follows this sequence:

```text
Start manager
      |
      v
Migrate legacy folder/manifest names
      |
      v
Validate ArtAssetsNeofetch
      |
      +-- missing/malformed --> offer rebuild
      |
      v
Ensure ArtAssetsPythoFetch scaffold exists
      |
      v
Validate PythoFetch Catalogue.json and art files
      |
      v
Merge NeoFetch + PythoFetch artwork
      |
      v
Resolve new database version
      |
      v
Build staging SQLite database
      |
      v
Validate database + integrity check
      |
      v
VACUUM database
      |
      v
Calculate SHA-256 + size
      |
      v
Promote versioned database
      |
      v
Update PythoFetchArtDB_Manifest.json
```

## NeoFetch Rebuild Behavior

If `ArtAssetsNeofetch` is missing or malformed, the manager explains the reason and asks:

```text
Rebuild ArtAssetsNeofetch now? [Y/n]:
```

Accepting the rebuild causes the manager to regenerate the NeoFetch artwork source.

Declining exits cleanly because the NeoFetch source is required for the complete merged database.

A declined rebuild is not treated as an application error.

## ArtAssetsPythoFetch Scaffold

If the native PythoFetch art source does not exist, the manager creates the required source structure.

The initial catalogue contains:

```json
{
  "format": "PythoFetchArtCatalogue",
  "format_version": 2,
  "source_project": "PythoFetch",
  "curated": true,
  "entry_count": 0,
  "family_counts": {
    "Windows": 0,
    "Linux": 0,
    "macOS": 0,
    "Other": 0
  },
  "entries": []
}
```

The corresponding folders are:

```text
Windows
Linux
MacOS
Other
```

## Catalogue Validation

Every source catalogue must use:

```text
format = PythoFetchArtCatalogue
```

The manager expects `entries` to be a JSON list.

If `entry_count` is present, it must match the actual number of entries.

Each artwork entry requires:

```text
id
name
family
variant
file
```

Optional fields include:

```text
aliases
colors
color_rule
matcher
parent_matcher
override
original_index
original_id
original_file
```

## Artwork ID Rules

Artwork IDs may contain:

```text
A-Z
a-z
0-9
.
_
+
-
```

IDs are case-insensitively unique within a source.

A duplicate ID inside the same source is rejected.

## Family Rules

The current logical families are:

```text
Windows
Linux
macOS
Other
```

Their filesystem folders are:

| Logical family | Folder |
| --- | --- |
| Windows | `Windows` |
| Linux | `Linux` |
| macOS | `MacOS` |
| Other | `Other` |

An artwork file must be stored inside the folder belonging to its declared family.

For example:

```json
{
  "family": "macOS",
  "file": "MacOS/MyMacArt.txt"
}
```

is valid.

Using:

```text
macOS/MyMacArt.txt
```

as the file path is not valid under the current folder convention.

## Artwork Files

Artwork is stored as UTF-8 text.

The manager rejects:

- missing artwork files
- empty artwork files
- paths that escape the source directory
- files stored outside the declared family folder

PythoFetch color markers use:

```text
${c1}
${c2}
...
${c8}
```

The entry's `colors` list supplies the palette used by those markers.

For example:

```json
"colors": ["2", "7"]
```

maps `${c1}` to the first palette value and `${c2}` to the second.

## Variants

The normal PythoFetch variants are:

```text
default
small
old
```

Use `default` for the primary artwork.

Use `small` for a compact version intended for narrow terminals.

`old` is used for retained historical artwork and is not automatically selected by PythoFetch 1.0.0.

## Aliases

Aliases connect detected operating-system names to an artwork entry.

Good aliases should match values the runtime may actually detect.

Examples include:

```text
Windows 11
Ubuntu
ubuntu
Arch Linux
macOS
Darwin
```

Aliases are de-duplicated case-insensitively by the manager.

The artwork name and ID are also indexed as aliases inside the compiled database.

## Merging NeoFetch and PythoFetch Artwork

The NeoFetch catalogue is loaded first.

Native PythoFetch artwork is then merged on top.

A PythoFetch artwork entry with a new ID is added normally.

If a PythoFetch entry uses an ID that already exists in NeoFetch, the manager rejects it unless the PythoFetch entry contains:

```json
"override": true
```

This makes replacements deliberate.

Example:

```json
{
  "id": "Ubuntu",
  "name": "Ubuntu",
  "family": "Linux",
  "variant": "default",
  "file": "Linux/Ubuntu.txt",
  "aliases": ["Ubuntu", "ubuntu"],
  "colors": ["1", "7"],
  "override": true
}
```

An entry marked `override: true` is also rejected if no existing artwork with that ID exists.

## Database Build

The manager first builds:

```text
PythoFetchArtNew.db
```

as a staging database.

The database contains:

- `metadata`
- `artwork`
- `aliases`

The database is checked before promotion.

Validation includes:

- expected artwork count
- non-empty artwork data
- stored database version
- SQLite `PRAGMA integrity_check`

The manager then runs `VACUUM` and validates the result again.

Only after successful validation is the database promoted to:

```text
PythoFetchArt_<version>.db
```

## Database Manifest

The database manifest is:

```text
PythoFetchArtDB_Manifest.json
```

Its top-level structure contains:

```text
schema
database
latest_version
versions
```

Each database version records information such as:

```text
file
download_url
sha256
size_bytes
created_utc
schema_version
compiler_version
artwork_count
added_pythofetch_artworks
override_count
source_counts
family_counts
```

The manifest retains older database versions rather than only describing the newest file.

## Atomic Promotion

The manager writes temporary/staging files before replacing the final database and manifest.

If promotion fails, it attempts to avoid leaving a partially published new database version.

Temporary build files are cleaned where possible.

## Legacy Name Migration

The manager contains migration handling for older development names.

The old manifest name:

```text
PythoFetchArt_Manifest.json
```

is migrated to:

```text
PythoFetchArtDB_Manifest.json
```

The old filesystem folder:

```text
macOS
```

is migrated to:

```text
MacOS
```

Catalogue file paths are updated to match the new folder spelling.

The logical family name remains `macOS`.

## Failure Behavior

Validation/build failures are treated as development errors and print the manager error block and Python traceback.

This is intentional for the art-development tool because failures should expose enough detail to diagnose malformed source artwork or catalogue metadata.

A user declining the required NeoFetch rebuild is handled separately and exits without a traceback.

## Recommended Development Process

A normal artwork change should use this workflow:

```text
1. Edit/add TXT artwork under ArtAssetsPythoFetch
2. Update ArtAssetsPythoFetch/Catalogue.json
3. Run PythoFetchArtManager
4. Build a new database version
5. Review the manager summary
6. Test PythoFetch against the new database
7. Commit the source artwork, catalogue, database, and manifest
```

Do not edit the compiled SQLite database directly.

The editable TXT files and catalogue are the source of truth for native PythoFetch artwork.
