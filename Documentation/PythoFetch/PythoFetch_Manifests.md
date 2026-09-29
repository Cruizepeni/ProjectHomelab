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

The feature resource manifest records the child manifest's integrity metadata.

## Updater Release Manifest

```text
Resources/FirstParty/PythoFetch/PythoFetchUpdater/
PythoFetchUpdater_Release_Manifest.json
```

It contains updater versions, compatibility families, platform assets, and verification data.

PythoFetch chooses the newest updater whose `X.Y` version family and declared `compatibility_family` both match the running PythoFetch `X.Y` family.

## Source Manifest

Entry point:

```text
SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
```

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

This is a direct component manifest.

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
    -> SHA-256 + byte size
```

This keeps top-level traversal simple while preserving verification at the points where bytes actually matter.
