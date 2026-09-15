# Resources

## Purpose

`Resources/` is ProjectHomelab's controlled source for external files and assets that ProjectHomelab features may need.

Resources describe what is available. They are not the installed dependency state of a machine. Installed, extracted, or otherwise materialized dependencies belong under the resolved ProjectHomelab `Dependencies/` location.

A consuming feature owns the decision about which resource it requires and which versions it supports.

## Discovery

`Resources/Resources_Manifest.json` is the entry point for the Resources system.

It identifies the Resources collection, points to this documentation, and maps stable resource IDs to each resource's root manifest.

The top-level manifest must not duplicate version, platform, artifact, checksum, installation, or feature-compatibility information.

A normal discovery path is:

```text
Resources_Manifest.json
→ <Resource>_Manifest.json
→ <Resource>_<version>_Manifest.json
→ controlled artifact
```

A catalog-style resource may instead use:

```text
Resources_Manifest.json
→ <Resource>_Manifest.json
→ <Resource>_Resources_Manifest.json
→ individual controlled resource
```

## Documentation Pointers

Manifest documentation paths are repository-root-relative.

The Resources system manifest points to:

```text
Documentation/Resources/Resources.md
```

A resource root manifest may point to:

```text
Documentation/Resources/<Resource>.md
```

A resource-specific document should be created when there is meaningful ProjectHomelab-specific information to preserve. Do not create documentation solely to satisfy a folder pattern.

Documentation explains how something works, why it exists, how ProjectHomelab uses it, and anything a developer needs to know.

Manifests remain authoritative for machine-readable state.

## Canonical Naming

Canonical operating-system names are:

```text
Windows
Linux
Mac
```

Canonical architecture names are:

```text
x86_64
arm64
universal
```

`universal` is valid only when one artifact genuinely supports both canonical architectures for that operating system.

Canonical runtime target IDs are:

```text
windows-x86_64
windows-arm64
linux-x86_64
linux-arm64
mac-x86_64
mac-arm64
```

Do not introduce alternate ProjectHomelab canonical values such as `x64`, `amd64`, `aarch64`, or `macOS`.

Upstream filenames may retain upstream naming.

## Normal Versioned Resource Layout

```text
Resources/
└── <Resource>/
    ├── <Resource>_Manifest.json
    └── <version>/
        ├── <Resource>_<version>_Manifest.json
        ├── <Resource>_<version>_Checksums.txt
        ├── Windows/
        ├── Linux/
        └── Mac/
```

Only create platform and architecture folders that are actually supported by that resource version.

## Resource Root Manifest

A normal resource root manifest is stored at:

```text
Resources/<Resource>/<Resource>_Manifest.json
```

It describes the resource as a whole.

It normally contains:

- `schema_version`
- stable `resource_id`
- display `name`
- repository-root-relative `documentation` path when resource-specific documentation exists
- `latest`
- `raw_base_url`
- `versions`

Each retained version maps to its version manifest and status.

The root manifest must not duplicate target or artifact definitions stored in the version manifest.

## Version Manifest

A normal controlled version uses:

```text
Resources/<Resource>/<version>/<Resource>_<version>_Manifest.json
```

The version manifest is the authoritative machine-readable definition of that version.

It should contain only metadata required to locate, verify, install, extract, copy, or otherwise materialize that controlled version.

Depending on the resource, this may include:

- `resource_id`
- `name`
- `version`
- `documentation`
- `checksum_file`
- canonical `targets`
- operating system
- architecture
- artifact path or artifact list
- SHA-256
- artifact or archive type
- installation or extraction method
- provided executables or capabilities

Do not add fields merely because another resource uses them.

## Checksums

SHA-256 is the ProjectHomelab integrity standard.

A normal version uses:

```text
<Resource>_<version>_Checksums.txt
```

Each checksum entry uses:

```text
<sha256>  <relative/path/to/artifact>
```

Paths are relative to that version folder.

The SHA-256 stored in the checksum file and the corresponding version manifest must match.

Where possible, generate both from the same validated source data.

MD5 may be stored as additional identification metadata when another ecosystem uses it, but it is not ProjectHomelab's integrity-verification standard.

## Catalog-Style Resources

A resource that represents a collection of individually addressable files does not need a fake package version.

A catalog-style layout may use:

```text
Resources/
└── <Resource>/
    ├── <Resource>_Manifest.json
    ├── <Resource>_Resources_Manifest.json
    ├── <Resource>_Checksums.txt
    └── <catalog content>
```

The root manifest describes the catalog and points to its detailed resource manifest, checksum file, and documentation.

The detailed resource manifest describes each controlled item using canonical relative paths and the metadata needed to identify and verify it.

## Feature Compatibility

Resources describe availability.

The consuming feature describes compatibility.

A feature may define a bounded contract such as:

```json
{
  "min_version": "1.0.0",
  "max_version": "1.4.2",
  "preferred_version": "1.4.2"
}
```

Expected behavior is:

1. Reuse an already installed compatible version when possible.
2. If no compatible version exists, install the preferred version.
3. If the preferred version is unavailable, choose the newest controlled compatible version.
4. Do not assume compatibility with untested future versions.

Resource manifests must not claim feature compatibility on behalf of a consuming feature.

## Adding a New Resource

When adding a normal resource:

1. Choose a stable resource folder name and `resource_id`.
2. Create the resource root manifest.
3. Create the controlled version folder.
4. Add only the artifacts required for supported ProjectHomelab targets.
5. Calculate SHA-256 for every artifact.
6. Create the version checksum file.
7. Create the version manifest.
8. Verify every path and filename exactly matches repository casing.
9. Register the resource in `Resources/Resources_Manifest.json`.
10. Add resource-specific documentation when there is meaningful information to preserve.
11. Add the documentation path to the resource manifest when that document exists.
12. Validate the complete discovery path from the top-level manifest to the controlled artifact.

Do not add a resource solely because it may be useful in the future. It should have a known ProjectHomelab purpose or consumer.

## Adding a New Version

When adding a new version:

1. Do not overwrite an existing controlled version.
2. Create a new version folder.
3. Add the new controlled artifacts.
4. Calculate new SHA-256 values.
5. Create the new checksum file.
6. Create the new version manifest.
7. Register the version in the resource root manifest.
8. Update `latest` only when the new version is intended to become the preferred/current controlled version.
9. Preserve older versions still required by supported feature compatibility ranges.
10. Update documentation only when the new version changes information that belongs in documentation.

Adding a new version does not require changing `Resources_Manifest.json`.

## Retiring or Removing Versions

Do not remove an older controlled version merely because a newer version exists.

Before removing one, verify that no supported feature version still requires it.

If a version remains because of legacy compatibility, preserve the reason in the resource-specific documentation when that context would otherwise be lost.

## Resource-Specific Documentation

Resource-specific documentation belongs at:

```text
Documentation/Resources/<Resource>.md
```

It should document only the resource it represents.

Useful information may include:

- why ProjectHomelab uses it
- what capability it provides
- which features depend on it
- why those features depend on it
- which feature versions support which resource versions
- preferred resource versions
- ProjectHomelab-specific integration behavior
- meaningful source, provenance, or licensing information
- legacy-retention rationale

Do not reproduce the resource inventory, artifact list, hashes, or version index when manifests already provide that information.

## Templates

Reusable contributor aids for Resources live at:

```text
Documentation/Resources/Templates/
```

Templates belong to documentation, not runtime Resources.

Use them as starting structures and remove fields that do not apply to the resource being created.

## Validation

Before committing a new or modified resource, verify:

- every JSON file parses successfully
- every referenced manifest exists
- every referenced artifact exists
- path spelling and casing are exact
- canonical target IDs are used
- SHA-256 values match the actual artifacts
- checksum and manifest hashes agree
- a newly added resource is registered in `Resources_Manifest.json`
- catalog manifests and checksum files describe the same controlled items
- documentation pointers resolve to repository-root-relative paths
- feature compatibility remains owned by the consuming feature

The Resources system should remain fully traversable from `Resources_Manifest.json` without undocumented path assumptions.
