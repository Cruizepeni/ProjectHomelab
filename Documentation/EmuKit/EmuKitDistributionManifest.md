# EmuKit Module Distribution Manifest

## Purpose

The platform module manifest is the machine-readable catalogue of emulator modules available to an EmuKit build for one operating system.

It describes distribution.

It does not describe installed local state and it does not contain emulator-specific installation behavior.

## Location

Development:

```text
backend/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Manifest.json
```

Release:

```text
Releases/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Manifest.json
```

Canonical `<OS>` values are:

```text
Windows
Linux
Mac
```

## Schema Version 1

Minimal document:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {}
}
```

Populated example:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {
    "example": {
      "Name": "Example Emulator",
      "Aliases": [
        "Example"
      ],
      "Version": "1.0.0",
      "Package": "Example/1.0.0/Example_1.0.0.zip",
      "SHA256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  }
}
```

## Fields

### SchemaVersion

Required integer.

For this contract:

```json
"SchemaVersion": 1
```

### Platform

Required canonical operating-system name.

The value must match the platform directory and manifest filename.

### Modules

Required object.

Keys are stable module IDs.

A module entry contains:

`Name`

- human-readable name

`Aliases`

- optional list of alternate names used for lookup before the module is locally installed

`Version`

- module package version
- corresponds to local Info `ModuleVersion`

`Package`

- relative package path below the current platform's `EmulatorModules/<OS>/` directory

`SHA256`

- lowercase SHA-256 of the exact package bytes
- required before Core installs or updates the package

## Package URL Resolution

Given:

```json
"Package": "DuckStation/1.0.0/DuckStation_1.0.0.zip"
```

Windows development resolves to conceptually:

```text
backend/EmuKit/EmulatorModules/Windows/DuckStation/1.0.0/DuckStation_1.0.0.zip
```

Windows release resolves to:

```text
Releases/EmuKit/EmulatorModules/Windows/DuckStation/1.0.0/DuckStation_1.0.0.zip
```

The manifest should not need separate hard-coded absolute URLs for development and release.

## Package Format

Schema version 1 module packages use ZIP archives.

The archive must resolve to exactly one valid EmuKit module root.

A recommended package is:

```text
DuckStation_1.0.0.zip
└── DuckStation/
    ├── EmuKitDuckStationInfo.json
    ├── DuckStationManager.py
    └── ...
```

Core may also accept package contents whose valid module root is the archive root, but a single top-level module folder is preferred for clarity.

## Integrity

Core calculates SHA-256 over the downloaded package before extraction.

The calculated value must exactly match `SHA256`.

A mismatch aborts installation and the package is discarded.

## Identity Validation

After extraction, Core validates the module Info file.

The extracted module's stable `Id` must equal the module ID key used in the platform manifest.

For example:

```text
Manifest key: duckstation
Info Id:      duckstation
```

A mismatch is rejected.

## Development Promotion

Recommended promotion flow:

```text
build package
→ calculate SHA-256
→ register package in backend/EmuKit manifest
→ remove local dev copy
→ install through EmuKit development channel
→ test module and emulator
→ copy exact package into Releases/EmuKit
→ copy equivalent manifest entry into release manifest
```

The release artifact should be byte-identical to the package tested through the development feed.

## Updating an Entry

When publishing a new module version:

1. do not overwrite a previously published package when that package remains referenced
2. create the new version package path
3. calculate SHA-256
4. update `Version`
5. update `Package`
6. update `SHA256`
7. test through the development channel
8. promote the exact tested package

## Validation Checklist

Before committing a platform manifest:

- JSON parses
- `SchemaVersion` is supported
- `Platform` matches its directory
- every module ID is machine-safe
- every module entry has a name
- aliases are strings
- every version is present
- every package path is repository-relative within the platform feed
- every package exists
- every SHA-256 is 64 lowercase hexadecimal characters
- every SHA-256 matches its package
- package extraction produces exactly one valid module
- extracted module `Id` matches manifest key
- extracted module `ModuleVersion` matches manifest `Version`
