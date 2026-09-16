# EmuKit Module Contract

## Purpose

An EmuKit emulator module is the adapter between generic EmuKit Core behavior and one emulator's specific behavior.

Core must not need emulator-specific knowledge.

A compliant module tells Core:

- who the module is
- which emulator version it manages
- which systems it supports
- where the managed emulator will live
- how games are launched
- how the emulator itself is launched
- how to check installation state
- how to install
- how to uninstall
- how to repair
- how to update

## Local Module Layout

A normal source module directory is:

```text
<EmuKit>/
└── <ModuleFolder>/
    ├── EmuKit<ModuleName>Info.json
    ├── <ModuleManager>.py
    └── <module-owned supporting files>
```

The exact folder name is not the module identity.

The stable `Id` inside the Info JSON is the module identity.

Each local module directory must contain exactly one file matching:

```text
EmuKit*Info.json
```

Templates and examples outside the runtime EmuKit module location are not modules.

## Module Info Schema

The Info JSON root is an object.

`Version` is the module-info schema version, not the module package version.

For schema version `1`, a normal module registration contains:

```json
{
  "Version": 1,
  "Id": "duckstation",
  "Name": "DuckStation",
  "Aliases": [
    "PS1",
    "PlayStation"
  ],
  "ModuleVersion": "1.0.0",
  "EmulatorVersion": "0.0.0",
  "Manager": "DuckStationManager.py",
  "DependencyPath": "dependencies/EmuKit/DuckStation",
  "LaunchPath": "dependencies/EmuKit/DuckStation/duckstation.exe",
  "WorkingDirectory": "dependencies/EmuKit/DuckStation",
  "EmulatorLaunchArguments": [],
  "DefaultInstalled": false,
  "Systems": {}
}
```

### Required Identity Fields

`Id`

- stable machine-safe module ID
- lowercase
- may contain lowercase letters, numbers, `.`, `_`, and `-`
- must not be renamed merely for display preference

`Name`

- human-readable module/emulator name

`Aliases`

- optional list of alternative names accepted by Core lookup

### Version Fields

`Version`

- Info-schema version
- currently `1`

`ModuleVersion`

- version of the EmuKit module package/logic
- independent of emulator version

`EmulatorVersion`

- emulator version the module is currently written/tested to manage
- may be a pinned upstream version or another stable module-defined identifier

The module should not silently reinterpret these concepts.

## Manager Entry Point

`Manager` identifies the lifecycle entry point relative to the module directory.

Source modules normally use a Python manager.

Example:

```json
"Manager": "DuckStationManager.py"
```

A release module may use a packaged executable manager when supported by Core.

The module contract is defined by lifecycle operations and structured results, not by one programming language.

## DependencyPath

`DependencyPath` is the ProjectHomelab-relative or standalone-root-relative location containing the emulator installation managed by the module.

It is not the location of the EmuKit module package itself.

The module package and emulator dependency are separate things.

## LaunchPath

`LaunchPath` is the default emulator executable/app entry path.

A system may override it when required.

Paths should be relative to the resolved ProjectHomelab/standalone root unless an absolute path is genuinely required by the platform.

## WorkingDirectory

`WorkingDirectory` is optional.

When present, Core uses it as the emulator process working directory.

When absent, Core may default to the launch executable's parent directory.

## EmulatorLaunchArguments

`EmulatorLaunchArguments` is optional.

It contains arguments used when launching the emulator without a game.

Example:

```json
"EmulatorLaunchArguments": []
```

This is separate from each system's game-launch arguments.

## Systems

`Systems` maps stable system IDs to system registration objects.

Example:

```json
{
  "Systems": {
    "playstation": {
      "Name": "PlayStation",
      "Aliases": [
        "PS1",
        "PSX"
      ],
      "Brand": {
        "Id": "sony",
        "Name": "Sony",
        "Aliases": []
      },
      "Platform": {
        "Id": "playstation",
        "Name": "PlayStation",
        "Aliases": []
      },
      "LaunchArguments": [
        "{fullscreen}",
        "{game}"
      ],
      "FullscreenArgument": "-fullscreen",
      "Default": true
    }
  }
}
```

A system registration must provide:

- system `Name`
- optional `Aliases`
- `Brand`
- `Platform`
- `LaunchArguments`

It may provide:

- system-specific `LaunchPath`
- system-specific `WorkingDirectory`
- `FullscreenArgument`
- `Default`

## Brand and Platform Identity

`Brand` and `Platform` each contain:

```json
{
  "Id": "sony",
  "Name": "Sony",
  "Aliases": []
}
```

The same stable ID must describe the same identity across every module.

Conflicting names for one ID are registration errors.

## Launch Arguments

Supported placeholders include:

```text
{game}
{system}
{fullscreen}
```

`{game}` is replaced with the selected game path.

`{system}` is replaced with the stable system ID.

`{fullscreen}` expands according to EmuKit's current fullscreen setting and the system's `FullscreenArgument`.

Do not quote placeholders inside an argument merely to compensate for shell parsing. Core launches processes using an argument array.

## Required Lifecycle Operations

Every source manager must implement:

```python
check()
install()
uninstall()
repair()
update()
```

Handlers may optionally accept:

```python
progress=None
```

Core detects whether a Python handler accepts the progress callback.

### check()

`check()` inspects the managed emulator state.

It must not perform destructive repair or installation as a side effect.

Expected successful states include:

```text
missing
installed
broken
```

A typical installed result includes the detected emulator version:

```json
{
  "success": true,
  "operation": "check",
  "state": "installed",
  "message": "DuckStation is installed.",
  "details": {
    "version": "0.0.0"
  }
}
```

### install()

`install()` creates a known-good managed emulator installation.

The module owns:

- emulator download/source selection
- emulator checksum/integrity validation
- extraction or installation
- emulator-specific runtime requirements
- emulator-specific resource requirements
- emulator-specific initial configuration

Core does not implement those details.

### uninstall()

`uninstall()` removes the managed emulator installation according to the module's documented data policy.

It must not remove the EmuKit module package itself.

User data must not be destroyed unless the module contract/documentation clearly defines that behavior and the operation specifically requires it.

### repair()

`repair()` returns a broken managed emulator installation to the known-good module-managed state.

A module may implement repair as reinstall/restore when that is the safest deterministic behavior.

Repair should preserve user-owned data unless the module explicitly owns that data and replacement is necessary.

### update()

`update()` updates the emulator installation according to the module's emulator-update policy.

This is not a module-package update.

Core owns module-package updates.

## Progress Callback

Long operations should report progress.

Example:

```python
def install(progress=None):
    if progress:
        progress(percent=10, stage="Checking", message="Checking existing installation.")
    ...
```

Callback keyword arguments are:

- `percent`
- `stage`
- `message`

Percent should remain within `0..100`.

## Structured Results

Lifecycle handlers return a dictionary.

A successful example:

```json
{
  "success": true,
  "operation": "install",
  "state": "installed",
  "message": "DuckStation installed successfully.",
  "details": {
    "version": "0.0.0"
  }
}
```

A failure example:

```json
{
  "success": false,
  "operation": "install",
  "state": "install_failed",
  "error": "download_failed",
  "message": "DuckStation could not be downloaded.",
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

Core adds `module` when necessary.

Do not return arbitrary strings or rely on console printing as the machine interface.

## Resource Ownership

A module decides which Resources it requires.

For emulator BIOS, firmware, controlled archives, or other external artifacts, use the ProjectHomelab Resources system when an appropriate controlled Resource exists.

Modules must not require Core to know which BIOS belongs to which emulator.

A module may consume:

```text
Resources/EmuKit/
```

but the module remains responsible for mapping those controlled resources into the emulator-specific installed layout.

## Emulator Version Policy

A module should use a known tested emulator version.

Do not blindly interpret "latest" as compatible.

When a new upstream emulator version is adopted:

```text
test emulator
→ update module behavior if required
→ update EmulatorVersion/source metadata
→ increment ModuleVersion when module logic/metadata changes
→ package and test module through the development feed
→ promote exact tested package
```

## Module Package Removal

Core may remove the physical module package without calling `uninstall()`.

Therefore modules must not assume their code will always remain present after emulator installation.

Removing a module must not be required to clean emulator state.

## Module Package Update

A module package can be replaced by Core.

A replacement package must use the same stable module `Id`.

The new package should be able to operate against the existing emulator-managed state or document a migration/repair requirement.

Module package updates must not silently change identity.

## Local Development

A local module is discoverable solely because it exists in the local EmuKit module location and passes registration validation.

It does not need to exist in a remote manifest.

This enables:

```text
edit
→ run
→ test
→ fix
```

without publishing every intermediate revision.

## Remote Distribution

Before promotion to `Releases/EmuKit`, the module package should be tested through `backend/EmuKit`.

The exact package that passed remote development installation should be promoted to release.

Do not rebuild a supposedly identical release package after testing unless the rebuilt artifact is tested again.

## Data Policy

Every module should have a clear data policy.

At minimum, module implementation should distinguish:

- module-owned emulator binaries
- module-owned generated configuration
- emulator cache
- user saves
- user states
- user screenshots
- user controller profiles
- user-supplied firmware/BIOS where applicable

`uninstall()` and `repair()` must not casually destroy user-owned data.

## Validation Checklist

Before publishing a module:

- exactly one `EmuKit*Info.json` exists in the module root
- Info JSON parses
- schema `Version` is supported
- stable module `Id` is valid
- `ModuleVersion` is correct
- `EmulatorVersion` is correct
- `Manager` exists
- required lifecycle handlers exist
- every declared system has valid identity metadata
- all declared launch paths/arguments are intentional
- `check()` correctly reports missing, installed, and broken states
- `install()` succeeds from a clean machine state
- `repair()` restores a deliberately broken installation
- `uninstall()` follows the data policy
- `update()` follows the emulator-update policy
- launch with a game works
- launch without a game works
- development package installs successfully through the development feed
- package SHA-256 matches the development manifest
- the exact tested package is promoted to the release feed
