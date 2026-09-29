# PythoFetch Documentation Set

This documentation set describes the current PythoFetch 1.0.0 architecture.

The canonical feature has three top-level manifest entry points:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json
Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json
SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
```

Those three manifests belong to three different repository environments. They are not a chain that PythoFetch walks through.

The packaged runtime uses the Release and Resources entry points directly.

The SourceCode entry point exists primarily for development and repository navigation. When a Python-source run needs to recover a missing artwork database, it directly uses `PythoFetchArtDB_Manifest.json` because the required component is already known.

Generic ProjectHomelab routers such as `Resources_Manifest.json` and `FirstParty_Resources_Manifest.json` exist for repository discovery by people, tools, and AI systems. PythoFetch itself does not use them to find its own resources.

Documentation:

- `PythoFetch.md` — application/runtime behavior
- `PythoFetch_Build_Tools.md` — all six Build Tools and build workflow
- `PythoFetch_Manifests.md` — manifest architecture and generation
- `PythoFetch_Updater.md` — update lifecycle
- `PythoFetch_Art_Manager.md` — artwork and Art DB workflow
- `Examples/Example_Artwork_Addition.md` — worked artwork example

Current fixed values:

```text
PythoFetch version: 1.0.0
PythoFetchUpdater version: 1.0.0
Build Tool version: 1.0.0
Manifest schema: 1
Artwork database schema: 1
```

Versions and schema numbers are not automatically bumped.
