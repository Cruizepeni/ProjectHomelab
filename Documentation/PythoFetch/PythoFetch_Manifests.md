# PythoFetch Manifest Architecture

## Fixed Schema

All current PythoFetch manifests use:

```json
"schema": 1
```

Schema values are not automatically bumped.

## Three Canonical Feature Entry Points

There are three top-level PythoFetch entry manifests:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json

Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json

SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
```

They represent three separate repository environments.

They are not a single traversal chain.

## Generic Router Manifests

Generic routers exist to make the repository easy to navigate when the caller does not already know a feature-specific path.

Examples:

```text
Resources/Resources_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
```

Their job is:

```text
Where do I go next?
```

A generic router manifest reference contains:

```text
file
path
download_url
```

It deliberately does not contain:

```text
sha256
size_bytes
purpose
folder
```

PythoFetch runtime does not use these generic routers to locate its own resources.

These generic ProjectHomelab routers retain the repository-wide router contract and are not converted to the feature-relative PythoFetch contract described below.

## PythoFetch Record Semantics

Within a PythoFetch feature manifest, `path` is relative to the corresponding PythoFetch environment root:

```text
SourceCode root: SourceCode/PythoFetch/
Resources root:  Resources/FirstParty/PythoFetch/
Releases root:   Releases/PythoFetch/
```

Examples:

```text
PythoFetch/PythoFetch_Manifest.json
PythoFetchUpdater/PythoFetchUpdater_Release_Manifest.json
PythoFetch_1.0.0_Linux_arm64.zip
```

PythoFetch-specific records use URL fields according to purpose:

```text
url          Human/browser GitHub link.
raw_url      Raw machine-readable URL for a referenced manifest.
download_url Raw URL for a payload that software actually downloads.
```

`download_url` remains correct for application ZIPs, updater ZIPs, source files, and artwork databases because those bytes are genuinely downloaded.

`PythoFetch_Resources_Manifest.json` is a compatibility exception: its `PythoFetchUpdater_Release_Manifest.json` reference exposes `raw_url` as the preferred machine-manifest field and retains `download_url` as a legacy alias for already-built PythoFetch 1.0.0 clients. New source accepts `raw_url` first and falls back to `download_url`.

## Feature/Component Manifests

A feature or component manifest describes actual inventory.

When a referenced manifest or file is something the program should verify, records can include:

```text
sha256
size_bytes
```

Raw release/package records additionally contain the metadata required to validate the actual payload.

## Release Manifest

Entry point:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json
```

Top-level role:

```text
current PythoFetch release catalogue
```

It contains:

```text
schema
application
latest_version
releases
```

Each platform asset includes:

```text
file
path
url
download_url
sha256
size_bytes
executable
executable_sha256
executable_size_bytes
```

PythoFetch checks this manifest directly.

PythoFetchUpdater also checks this manifest directly when installing the selected application release.

## Resources Manifest

Entry point:

```text
Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json
```

It is PythoFetch's direct runtime resource entry point.

It currently routes to:

```text
PythoFetchUpdater_Release_Manifest.json
```

The feature resource manifest records the child manifest's integrity metadata. Its child-manifest reference contains the feature-relative `path`, human `url`, preferred machine `raw_url`, SHA-256, and byte size. It also retains a legacy `download_url` alias for PythoFetch 1.0.0 compatibility.

## Updater Release Manifest

```text
Resources/FirstParty/PythoFetch/PythoFetchUpdater/
PythoFetchUpdater_Release_Manifest.json
```

It contains updater versions, compatibility families, platform assets, and verification data for Windows x86_64, Linux x86_64, and Linux arm64 when those packages are present. Updater package records use `path`, `url`, and `download_url` because the ZIP is an actual downloadable payload.

PythoFetch chooses the newest updater whose `X.Y` version family and declared `compatibility_family` both match the running PythoFetch `X.Y` family.

## Source Manifest

Entry point:

```text
SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
```

Its child manifest records use paths relative to `SourceCode/PythoFetch/` and use `url` for normal GitHub navigation.

It routes development/repository navigation to:

```text
PythoFetch/PythoFetch_Manifest.json
PythoFetchUpdater/PythoFetchUpdater_Manifest.json
PythoFetchArtAssets/PythoFetchArtAssets_Manifest.json
PythoFetchBuildTools/PythoFetchBuildTools_Manifest.json
```

It is not required by the packaged runtime.

## Art Database Manifest

```text
SourceCode/PythoFetch/PythoFetchArtAssets/ArtAssetsDB/
PythoFetchArtDB_Manifest.json
```

This is a direct component manifest. Database entries use `path`, `url`, and `download_url`; the database is a genuine downloadable payload.

Python-source PythoFetch can use it directly when no valid local art database is available.

This direct component lookup is intentional; the runtime already knows exactly what component it requires, so traversing `PythoFetch_Source_Manifest.json` first would add no value.

## Manifest Build Tool

The canonical generator is:

```text
Build_PythoFetchManifests_1.0.0.py
```

It is temporarily copied into one of:

```text
SourceCode/PythoFetch
Releases/PythoFetch
Resources/FirstParty/PythoFetch
```

and removed after use.

### SourceCode Output

```text
PythoFetch_Source_Manifest.json
PythoFetch/PythoFetch_Manifest.json
PythoFetchUpdater/PythoFetchUpdater_Manifest.json
PythoFetchArtAssets/PythoFetchArtAssets_Manifest.json
PythoFetchArtAssets/ArtAssetsDB/PythoFetchArtDB_Manifest.json
PythoFetchBuildTools/PythoFetchBuildTools_Manifest.json
```

### Releases Output

```text
PythoFetch_Release_Manifest.json
```

### Resources Output

```text
PythoFetch_Resources_Manifest.json
PythoFetchUpdater/PythoFetchUpdater_Release_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
Resources/Resources_Manifest.json
```

Resources mode rebuilds the two generic parent routers from manifests actually present in their child directories.

## Integrity Boundary

The current convention is:

```text
generic navigation router
    -> navigation data only

feature/component manifest
    -> inventory and verification where applicable

actual downloadable file/package
    -> path + url + download_url + SHA-256 + byte size

verified child manifest used by PythoFetch runtime
    -> path + url + raw_url + SHA-256 + byte size
    -> legacy download_url alias retained where required for 1.0.0 compatibility
```

This keeps top-level traversal simple while preserving verification at the points where bytes actually matter.
