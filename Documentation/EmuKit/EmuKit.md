# EmuKit

## Purpose

`EmuKit` is ProjectHomelab's emulator-module manager.

EmuKit Core provides shared orchestration while emulator-specific behavior belongs to emulator modules.

Core is responsible for:

- ProjectHomelab and standalone root resolution
- host operating-system and architecture detection
- shared Core dependency preflight
- local module discovery from `EmuKitModules`
- registry generation
- settings reconciliation
- remote platform-manifest discovery
- module package download and SHA-256 verification
- safe module package extraction, installation, update, and removal
- serialized lifecycle invocation
- system-to-module assignment
- emulator and game launching
- progress reporting
- structured operation results

Core is not responsible for emulator-specific download URLs, BIOS or firmware rules, emulator configuration, emulator repair logic, emulator uninstall policy, or emulator update logic.

Those responsibilities belong to each emulator module.

## Core 1.0.0 Layout

Core source lives in a versioned directory while the Python filenames themselves remain unversioned.

```text
backend/
└── EmuKit/
    └── EmuKitCore/
        └── EmuKit_1.0.0/
            ├── EmuKit.py
            ├── EmuKitManager.py
            ├── EmuKitSettings.py
            ├── EmuKitLauncher.py
            └── EmuKitModules/
```

Do not create filenames such as:

```text
EmuKit_1.0.0.py
EmuKitManager_1.0.0.py
```

Core version, module version, and emulator version are independent concepts.

```text
EmuKit Core Version
Module Version
Emulator Version
```

Changing one does not imply that either of the others changed.

## Root Resolution

`.ProjectHomelabRoot` is the sole ProjectHomelab root marker.

When EmuKit starts, it searches upward from its runtime location for:

```text
.ProjectHomelabRoot
```

If found, that directory becomes `ROOT`.

If no marker is found, EmuKit operates in standalone mode and its own runtime directory becomes `ROOT`.

No secondary ProjectHomelab-host detection mechanism should be introduced.

A normal ProjectHomelab layout is:

```text
ROOT/
├── .ProjectHomelabRoot
├── backend/
│   └── EmuKit/
│       └── EmuKitCore/
│           └── EmuKit_1.0.0/
│               └── EmuKitModules/
├── Emulators/
├── dependencies/
├── appdata/
└── Resources/
```

A standalone EmuKit layout uses the same relative concepts locally:

```text
EmuKit_1.0.0/
├── EmuKit.py or EmuKit.exe
├── EmuKitModules/
├── Emulators/
├── dependencies/
└── appdata/
```

## Local Module Location

Installed module packages live under:

```text
<EmuKit runtime>/EmuKitModules/
```

A normal installed module is:

```text
EmuKitModules/
└── Xemu_1.0.0/
    ├── EmuKitXemuInfo.json
    ├── XemuManager.py
    └── module-owned supporting files
```

A physically present valid module is locally installed even if it does not appear in any remote manifest.

The local module directory answers:

```text
What module code is physically installed?
```

The generated registry answers:

```text
What valid local modules did Core discover and normalize?
```

The remote platform manifest answers:

```text
What module packages are available to download or update?
```

These are deliberately separate authorities.

## Emulator Installation Location

Modules manage emulator installations below:

```text
ROOT/Emulators/
```

For example:

```text
ROOT/Emulators/Xemu/
```

A module's `DependencyPath` must be relative to `ROOT`, must resolve inside `ROOT/Emulators`, and must identify a child directory of `Emulators`.

The old `dependencies/EmuKit/<Emulator>` emulator layout is not part of Core 1.0.0.

The general `ROOT/dependencies/` directory remains available for shared non-emulator dependencies.

## Core Dependencies

Core 1.0.0 performs dependency preflight before normal initialization.

Required shared dependencies are:

```text
7-Zip 26.03
  Windows: required
  Linux:   required
  Mac:     required

Microsoft Visual C++ v14 Redistributable
  Windows: required
  Linux:   not required
  Mac:     not required
```

If required dependencies are missing, EmuKit lists them and asks whether it should install them automatically.

If the user chooses `No`, EmuKit closes instead of entering the normal CLI without required dependencies.

If automatic installation fails and dependencies remain missing, EmuKit closes.

### 7-Zip Resource Resolution

Core pins the required 7-Zip version but does not hard-code each artifact filename or checksum.

Core starts from:

```text
Resources/7Zip/7Zip_Manifest.json
```

The root resource manifest identifies the pinned version manifest, for example:

```text
26.03/7Zip_26.03_Manifest.json
```

Core then selects the target matching the current OS and architecture and consumes the target's:

- artifact path
- SHA-256
- executable name
- install method
- silent installer arguments where applicable

On Windows, the controlled installer is executed according to manifest metadata.

On Linux and macOS, the controlled archive is extracted into the shared dependency area and `7zz` is made executable.

Local controlled Resources are preferred when present and valid; otherwise Core can retrieve the controlled artifact from the resource manifest's raw repository location.

### Visual C++ Redistributable

On Windows, Core detects the installed Microsoft Visual C++ v14 runtime through the Windows registry.

If missing and the user accepts automatic dependency installation, Core downloads the latest supported x64 redistributable from Microsoft's official `vc14` permalink, installs it quietly, and verifies detection afterward.

## Development and Release Channels

EmuKit uses the same Core behavior in development and release builds.

The remote module feed changes by channel.

Normal Python source execution defaults to:

```text
backend/EmuKit/
```

Frozen executable builds default to:

```text
Releases/EmuKit/
```

Development platform manifests use:

```text
backend/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Manifest.json
```

Release platform manifests use:

```text
Releases/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Release_Manifest.json
```

Backend/source manifests always use `Name_Manifest.json`. Release-side mirrors always use `Name_Release_Manifest.json`.

Canonical operating-system names are:

```text
Windows
Linux
Mac
```

Examples:

```text
backend/EmuKit/EmulatorModules/Windows/EmuKit_Windows_Manifest.json
Releases/EmuKit/EmulatorModules/Windows/EmuKit_Windows_Release_Manifest.json
```

`EMUKIT_CHANNEL` may explicitly select development or release behavior for testing.

`EMUKIT_FEED_BASE_URL` may override the feed base for controlled development/testing scenarios.

Development and release must not use different module lifecycle, validation, registry, or installer semantics.

The channel changes the source of distributed module packages, not the module contract.

## Distribution Layout

The current backend convention is:

```text
backend/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
            └── Xemu/
                ├── Xemu_Manifest.json
                └── Xemu_1.0.0.zip
```

The release convention is:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Release_Manifest.json
            └── Xemu/
                ├── Xemu_Release_Manifest.json
                └── Xemu_1.0.0.zip
```

Core manifests follow the same split:

```text
backend/EmuKit/EmuKitCore/EmuKit_Core_Manifest.json
Releases/EmuKit/EmuKitCore/EmuKit_Core_Release_Manifest.json
```

There is no extra `1.0.0/` directory between the module folder and `Xemu_1.0.0.zip`.

The ZIP itself contains its versioned module directory:

```text
Xemu_1.0.0.zip
└── Xemu_1.0.0/
    ├── EmuKitXemuInfo.json
    └── module code
```

Core 1.0.0 consumes the platform manifest for runtime discovery, download, and update decisions.

The backend per-module `<Module>_Manifest.json` and release `<Module>_Release_Manifest.json` are retained module-version catalogues for their respective channels. They record available versions and package hashes, but Core 1.0.0 does not require a second lookup through those files to install a module advertised by the active platform manifest.

## Development Workflow

A normal module-development workflow is:

```text
Create module locally
→ place it under EmuKitModules
→ run EmuKit
→ local discovery registers the module
→ develop and test lifecycle behavior
→ package the working module
→ calculate package SHA-256
→ publish the source/development package and `Name_Manifest.json` metadata to backend/EmuKit
→ remove the local module copy
→ install through the development feed
→ verify source-package download, hash verification, extraction, discovery, and emulator installation
→ build the release package for the target OS/architecture
→ use an executable manager in release packaging when that target is distributed as a compiled module
→ publish `Name_Release_Manifest.json` metadata with the release-package hash
→ test the release package through the release channel
```

A locally present development module does not need a remote platform-manifest entry.

## Installing a Module

`Install <Module>` has two paths.

If the module is already physically present:

```text
resolve local module
→ enable it for management
→ invoke module install()
```

If the module is not physically present:

```text
resolve module from platform manifest
→ download package to staging
→ verify SHA-256
→ safely extract package
→ locate exactly one valid module root
→ validate module registration
→ verify module ID and version against manifest metadata
→ copy validated module into EmuKitModules
→ rebuild registry
→ reconcile settings
→ invoke module install()
```

Validated modules are copied out of staging rather than renamed from the temporary extraction directory so the installed module inherits normal destination permissions.

Core installs the module package.

The module installs the emulator.

## Install All

`Install All` operates on the current host platform manifest.

For each remote module:

```text
already local
    → do not redownload unnecessarily
missing locally
    → acquire and install module package
then
    → invoke emulator install lifecycle
```

Failures are reported per module.

## Updating

There are two separate update concepts.

### Module Package Update

`Update Module <Module>` is owned by Core.

Core compares the installed module's `ModuleVersion` with the version advertised by the current platform manifest.

A replacement module is installed only after the package has downloaded, passed SHA-256 verification, and passed module-contract validation.

### Emulator Update

`Update <Module>` is owned by the module.

Core invokes the module's:

```text
update()
```

handler.

Core does not contain emulator-specific update knowledge.

## Removing Modules and Uninstalling Emulators

These are different operations.

### Remove Module

`Remove Module <Module>` removes the EmuKit module package from `EmuKitModules`.

It does not invoke emulator uninstall logic.

The emulator installation is left untouched.

The registry is then rebuilt and invalid assignments are cleared.

### Uninstall

`Uninstall <Module>` invokes the module's emulator uninstall lifecycle.

The module package remains available unless separately removed.

## Registry

The registry is generated state stored below:

```text
ROOT/appdata/registry/EmuKitRegistry.json
```

It must be rebuildable from valid physically present modules.

The registry normalizes:

- modules
- brands
- platforms
- systems

A missing module directory must eventually disappear from the registry.

The registry is not the authority for whether module files physically exist.

## Settings

Settings are stored below:

```text
ROOT/appdata/settings/EmuKitSettings.json
```

They preserve user choices independently from registry regeneration where possible.

Settings include:

- global fullscreen state
- module enabled/managed state
- per-system module assignment

When a module is first discovered, `DefaultInstalled` is used to seed that module's enabled state.

Registry synchronization should preserve unrelated user choices and clear assignments that can no longer be satisfied.

## Systems and Assignments

Modules declare the systems they support.

Core combines those declarations into a normalized catalogue.

A user may assign one module as the active module for a system.

Supported-system presentation includes Brand + System to remain unambiguous.

Examples:

```text
Nintendo GameCube
Sony PlayStation 2
Microsoft Xbox
```

## Launching

EmuKit supports two launch modes.

### Launch a Game

```text
Launch <GamePath> <System>
```

The system assignment determines which local module launches the game.

Core resolves the module's executable, working directory, system launch arguments, fullscreen setting, and game path.

### Launch an Emulator Without a Game

```text
Launch Emulator <Module>
```

This is used for emulator configuration, controller setup, graphics settings, maintenance, and emulator-native UI tasks.

Module registration may provide `EmulatorLaunchArguments` separately from each system's game-launch arguments.

## Current CLI Commands

Core 1.0.0 exposes:

```text
Get Settings
Get <Module> Settings
Update Setting <Setting> <Value>
Install <Module>
Install All
Uninstall <Module>
Remove Module <Module>
Repair <Module>
Update <Module>
Update Module <Module>
Check <Module>
Refresh Modules
Get <Name> Info
Get Module <Name> Info
Get Brand <Name> Info
Get Platform <Name> Info
Get System <Name> Info
Get Current Installs
Get Supported Modules
Get Supported Brands
Get Supported Platforms
Get Supported Systems [Brand <Name>] [Platform <Name>]
Get Status
Get Core Dependencies
Assign System <System> <Module|None>
Launch <GamePath> <System>
Launch Emulator <Module>
Help
Close
```

`--json` requests raw structured output where supported.

`--verbose` requests additional operation details where supported.

Dependency installation is handled by startup preflight instead of a user-facing `Install Core ...` command.

## Operation Serialization

Mutation operations are serialized.

Do not concurrently run install, uninstall, repair, emulator update, module-package replacement, or module removal operations that may mutate shared EmuKit/module state.

## Structured Results

Core and modules communicate using structured result objects.

A normal result contains:

```json
{
  "success": true,
  "module": "exampleemu",
  "operation": "install",
  "state": "installed",
  "message": "ExampleEmu installed successfully.",
  "details": {}
}
```

Important semantic fields are:

- `success`
- `operation`
- `state`
- `message`

`module` should be present for module operations.

`details` may contain operation-specific machine-readable information.

## Progress

Lifecycle handlers may accept a `progress` callback.

Conceptual usage:

```python
progress(percent=25, stage="Downloading", message="Downloading emulator package.")
```

Progress is optional for instantaneous operations but recommended for long download, extraction, installation, repair, update, and uninstall operations.

## Security and Validation

Before installing a remote module package, Core must:

- download into staging
- verify package SHA-256
- reject absolute or traversal archive paths
- reject unsafe symbolic-link package entries
- reject packages with no valid module
- reject packages containing multiple valid module roots
- reject a package whose module ID does not match the requested manifest entry
- reject a package whose module version does not match the manifest entry
- validate `DependencyPath` inside `ROOT/Emulators`
- preserve the previous module during replacement until the new package has validated

A failed module-package update should leave the previous valid module recoverable.

## Documentation Scope

General EmuKit documentation belongs under:

```text
Documentation/EmuKit/
```

Reusable contributor aids belong under:

```text
Documentation/EmuKit/Templates/
```

Generic non-runtime examples belong under:

```text
Documentation/EmuKit/Examples/
```

Individual emulator-module documentation is maintained separately as modules are documented.

Generic Core documentation should not become a collection of emulator-specific instructions.

## Validation Checklist

Before declaring an EmuKit Core build ready:

- `.ProjectHomelabRoot` resolution works
- standalone fallback works
- frozen runtime resolution uses the executable directory
- host OS maps to Windows, Linux, or Mac
- host architecture maps supported x86_64 and ARM64 forms correctly
- Core dependency preflight blocks startup when required dependencies are missing
- automatic dependency installation can satisfy supported missing dependencies
- 7-Zip resource resolution follows root manifest → pinned version manifest → host target
- local valid modules are discovered only from `EmuKitModules`
- invalid modules are rejected with useful registration errors
- module emulator paths are constrained to `ROOT/Emulators`
- registry rebuild works
- settings survive registry rebuild
- active platform manifest validates
- missing network/manifest does not destroy local module functionality
- package download uses staging
- package SHA-256 is verified
- unsafe archive paths are rejected
- acquired module ID and version match platform-manifest metadata
- validated module installation preserves normal destination permissions
- registry refresh sees newly acquired modules
- `Install <Module>` works for local and remote modules
- `Install All` reports per-module failures
- module-package update is separate from emulator update
- `Remove Module` does not uninstall the emulator
- `Uninstall` invokes module emulator-uninstall behavior
- emulator launch with a game works
- emulator launch without a game works
- operations remain serialized
- structured results remain stable
