# EmuKit Module Contract

## Purpose

An EmuKit emulator module is the adapter between generic EmuKit Core behavior and one emulator's specific behavior.

Core must not need emulator-specific knowledge.

A compliant module tells Core:

- who the module is
- which emulator version it manages
- which systems it supports
- where the managed emulator lives
- how games are launched
- how the emulator itself is launched
- how to check installation state
- how to install
- how to uninstall
- how to repair
- how to update

## Local Module Layout

Installed modules live under the Core runtime's `EmuKitModules` directory.

```text
<EmuKit runtime>/
└── EmuKitModules/
    └── ExampleEmu_1.0.0/
        ├── EmuKitExampleEmuInfo.json
        ├── ExampleEmuManager.py
        └── module-owned supporting files
```

The directory name is packaging/versioning convention.

The stable `Id` inside the Info JSON is the actual module identity.

Each local module directory must contain exactly one file matching:

```text
EmuKit*Info.json
```

Templates and examples outside `EmuKitModules` are not runtime modules.

## Module Info Schema

`Version` is the module-info schema version, not the module package version.

For schema version `1`, a normal registration is:

```json
{
  "Version": 1,
  "Id": "exampleemu",
  "Name": "ExampleEmu",
  "Aliases": [
    "Example Emulator"
  ],
  "ModuleVersion": "1.0.0",
  "EmulatorVersion": "4.2.0",
  "Manager": "ExampleEmuManager.py",
  "DependencyPath": "Emulators/ExampleEmu",
  "LaunchPath": "Emulators/ExampleEmu/exampleemu.exe",
  "WorkingDirectory": "Emulators/ExampleEmu",
  "EmulatorLaunchArguments": [],
  "DefaultInstalled": false,
  "Systems": {
    "example-console": {
      "Name": "Example Console",
      "Aliases": [
        "EC"
      ],
      "Brand": {
        "Id": "example-company",
        "Name": "Example Company",
        "Aliases": []
      },
      "Platform": {
        "Id": "console",
        "Name": "Console",
        "Aliases": []
      },
      "LaunchArguments": [
        "{game}"
      ],
      "FullscreenArgument": null,
      "Default": true
    }
  }
}
```

## Identity Fields

`Id`

- stable lowercase machine-safe module ID
- may contain lowercase letters, numbers, `.`, `_`, and `-`
- must not change merely for display preference

`Name`

- human-readable module/emulator name

`Aliases`

- optional alternative lookup names

## Version Fields

`Version`

- Info-schema version
- currently `1`

`ModuleVersion`

- version of the EmuKit module package and module logic

`EmulatorVersion`

- emulator version the module is written and tested to manage

Module version and emulator version are independent.

## Manager Entry Point

`Manager` identifies the lifecycle entry point relative to the module directory.

Python managers are supported. Development/source packages may therefore use a manager such as `ExampleEmuManager.py`.

Core also supports executable managers. Release packages may use a compiled manager such as `ExampleEmuManager.exe`. For executable managers Core invokes the manager as `<manager> <operation> --json`, runs it from the module directory, and expects stdout to contain one valid JSON result.

The lifecycle contract is defined by operations and structured results rather than by one programming language.

## DependencyPath

`DependencyPath` is the root-relative directory containing the emulator installation managed by the module.

Core 1.0.0 requires it to:

- be relative, not absolute
- resolve inside `ROOT/Emulators`
- identify a child directory below `ROOT/Emulators`

Correct:

```json
"DependencyPath": "Emulators/ExampleEmu"
```

Incorrect:

```json
"DependencyPath": "dependencies/EmuKit/ExampleEmu"
```

The module package and the emulator installation are separate things.

Module code lives under `EmuKitModules`.

Emulator binaries live under `ROOT/Emulators`.

## LaunchPath

`LaunchPath` is the default emulator executable or app entry path.

It normally resolves from `ROOT`.

A system registration may override it when required.

## WorkingDirectory

`WorkingDirectory` is optional.

When present, Core uses it as the emulator process working directory.

When absent, Core may use the launch executable's parent directory.

## EmulatorLaunchArguments

`EmulatorLaunchArguments` is optional.

It contains arguments used when launching the emulator without a game.

This is separate from per-system game launch arguments.

## DefaultInstalled

`DefaultInstalled` is optional and defaults to `false`.

When Core first creates settings for a newly discovered module, this value seeds the module's enabled/managed state.

It is not the module package version and it is not a statement that the emulator binaries already exist.

## Systems

`Systems` must contain at least one system.

Each system ID must be lowercase and machine-safe.

A system registration must provide:

- `Name`
- optional `Aliases`
- `Brand`
- `Platform`
- `LaunchArguments`

It may also provide:

- system-specific `LaunchPath`
- system-specific `WorkingDirectory`
- `FullscreenArgument`
- `Default`

`FullscreenArgument` may be a string, a list of strings, or `null`.

## Brand and Platform Identity

`Brand` and `Platform` each contain:

```json
{
  "Id": "example-company",
  "Name": "Example Company",
  "Aliases": []
}
```

The same stable ID must describe the same identity across every module.

Conflicting names or conflicting system identity metadata are registry errors.

## Default System Module

A system registration may set:

```json
"Default": true
```

Core uses these declarations when building the normalized system catalogue.

For one system, no more than one discovered module should claim to be the default.

Multiple default modules for the same system are treated as a catalogue error.

## Launch Arguments

Supported placeholders include:

```text
{game}
{system}
{fullscreen}
```

`{game}` becomes the selected game path.

`{system}` becomes the stable system ID.

`{fullscreen}` expands from the current EmuKit fullscreen setting and the system's `FullscreenArgument`.

Core launches with an argument array, so placeholders should not be wrapped in extra shell quoting merely to handle spaces.

## Required Lifecycle Operations

Every manager must provide:

```text
check
install
uninstall
repair
update
```

Python lifecycle handlers may optionally accept:

```python
progress=None
```

Core detects whether the handler accepts the progress callback.

### check()

`check()` inspects emulator state.

It must not install or perform destructive repair as a side effect.

Normal successful states include:

```text
missing
installed
broken
```

### install()

`install()` creates the module's known-good managed emulator installation.

The module owns:

- emulator source selection
- emulator version pinning
- emulator checksum validation
- extraction or installation
- emulator-specific runtime requirements
- emulator-specific BIOS, firmware, or resource requirements
- emulator-specific initial configuration

Core does not implement those details.

### uninstall()

`uninstall()` removes the managed emulator according to that module's documented data policy.

It must not remove the EmuKit module package itself.

### repair()

`repair()` returns a broken managed emulator installation to the module's known-good state.

A module may repair individual files/configuration or perform a deterministic reinstall.

Its behavior must match the module's documented data policy.

### update()

`update()` updates the emulator itself according to the module's emulator-update policy.

This is not a module-package update.

Core owns module-package updates through `Update Module <Module>`.

## Progress Callback

Long operations should report progress.

Example:

```python
if progress:
    progress(percent=25, stage="Downloading", message="Downloading emulator package.")
```

Supported callback keywords are:

- `percent`
- `stage`
- `message`

Percent should remain within `0..100`.

## Structured Results

Lifecycle handlers return structured dictionaries.

Successful example:

```json
{
  "success": true,
  "operation": "install",
  "state": "installed",
  "message": "ExampleEmu installed successfully.",
  "details": {
    "version": "4.2.0"
  }
}
```

Failure example:

```json
{
  "success": false,
  "operation": "install",
  "state": "install_failed",
  "error": "download_failed",
  "message": "ExampleEmu could not be downloaded.",
  "details": "Connection timed out."
}
```

Modules should provide:

- boolean `success`
- matching `operation`
- stable machine-readable `state`
- human-readable `message`
- optional `error`
- optional `details`

Core adds module identity when necessary.

Do not rely on console printing as the machine interface.

## Resource Ownership

A module decides which ProjectHomelab Resources it requires.

Emulator BIOS, firmware, controlled archives, or other emulator-specific artifacts remain module responsibilities.

Modules may consume controlled resources from:

```text
Resources/EmuKit/
```

A module remains responsible for:

- selecting required resources
- validating them
- mapping them into the emulator's actual installed layout
- writing emulator configuration that points at those resources when necessary

Core must not know which BIOS belongs to which emulator.

## Shared Core Dependencies

Modules may assume that required Core dependencies passed startup preflight before normal EmuKit initialization.

Core 1.0.0 currently provides:

```text
7-Zip 26.03
  Windows
  Linux
  Mac

Microsoft Visual C++ v14 Redistributable
  Windows only
```

An emulator-specific dependency that is not genuinely shared still belongs to the module.

## Emulator Version Policy

A module should manage a known tested emulator version.

Do not blindly interpret upstream `latest` as compatible.

When adopting a new upstream version:

```text
test emulator
→ update module logic or metadata as needed
→ update EmulatorVersion
→ increment ModuleVersion when package logic/metadata changes
→ build source/development module ZIP
→ test through development feed
→ build target release package
→ test through release channel
```

## Module Package Removal

Core may remove the physical module package without calling `uninstall()`.

Modules must therefore not assume their code will always remain present after emulator installation.

`Remove Module` and `Uninstall` are intentionally different operations.

## Module Package Update

Core may replace a module package while leaving the managed emulator installation in place.

A replacement module must retain the same stable `Id`.

The new module should be able to understand the existing managed emulator state or provide a deterministic repair/update path.

## Local Development

A local module is discoverable because it exists under `EmuKitModules` and passes registration validation.

It does not need a remote manifest entry.

Normal loop:

```text
edit
→ run
→ test
→ fix
```

## Remote Distribution

Before release packaging, the source/development module ZIP should be tested through the `backend/EmuKit` development feed.

The release package may differ from the development package when Python lifecycle code is compiled into an executable manager. The release package must keep the same stable module identity and intended module version, and it must be tested independently through the release channel.

Every distributed package is hashed independently. Backend manifests must carry the development-package SHA-256, while release manifests must carry the release-package SHA-256.

## Data Policy

Each module should have a clearly documented data policy when its individual module documentation is written.

At minimum, consider:

- emulator binaries
- generated configuration
- emulator cache
- saves
- states
- screenshots
- controller profiles
- user-supplied firmware/BIOS
- writable emulator disk images or similar state

`uninstall()` and `repair()` behavior should be explicit rather than assumed.

## Validation Checklist

Before publishing a module:

- exactly one `EmuKit*Info.json` exists in the module root
- Info JSON parses
- schema `Version` is supported
- stable module `Id` is valid
- `ModuleVersion` is correct
- `EmulatorVersion` is correct
- `Manager` exists
- `DependencyPath` resolves to a child of `ROOT/Emulators`
- required lifecycle handlers exist
- `Systems` contains at least one valid system
- every declared system has valid Brand and Platform metadata
- system identity does not conflict with existing modules
- all launch paths and arguments are intentional
- `check()` correctly reports missing, installed, and broken states
- `install()` succeeds from a clean state
- `repair()` restores a deliberately broken state
- `uninstall()` follows the module's data policy
- `update()` follows the emulator-update policy
- launch with a game works
- launch without a game works
- development ZIP installs through the development feed
- backend package SHA-256 matches backend manifests
- release package is built for the intended target
- release manager entry point matches the release Info JSON
- release package SHA-256 matches release manifests
- extracted `Id` and `ModuleVersion` match the active platform manifest
- release package installs through the release feed
