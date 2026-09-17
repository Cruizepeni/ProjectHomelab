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

The current ProjectHomelab module-source convention is:

```text
EmuKitModules/
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    ├── ExampleEmuManager.py
    ├── ExampleEmuInstaller.py
    ├── ExampleEmuRepair.py
    ├── ExampleEmuUninstall.py
    └── _ExampleEmuCommon.py
```

This split is the canonical pattern used by the current Windows modules.

`ExampleEmuManager.py` owns the lifecycle gateway and status checks.

`ExampleEmuInstaller.py` owns clean installation.

`ExampleEmuRepair.py` owns repair behavior.

`ExampleEmuUninstall.py` owns uninstall behavior.

`_ExampleEmuCommon.py` owns shared paths, root resolution, resource helpers, checksums, progress helpers, host validation, and other module-wide utilities.

Emulator-specific modules may add files where genuinely required, but new modules should begin from this structure instead of collapsing all behavior into one manager file.

Release packages normally replace the Python manager with a compiled executable manager while retaining the external Info JSON:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
└── ExampleEmuManager.exe
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
            └── ExampleEmu/
                ├── ExampleEmu_Manifest.json
                └── ExampleEmu_1.0.0.zip
```

The Windows x86_64 release convention is:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Release_Manifest.json
            └── ExampleEmu/
                ├── ExampleEmu_Release_Manifest.json
                └── ExampleEmu_1.0.0_Windows_x86_64.zip
```

Core manifests follow the same development/release split:

```text
backend/EmuKit/EmuKitCore/EmuKit_Core_Manifest.json
Releases/EmuKit/EmuKitCore/EmuKit_Core_Release_Manifest.json
```

The Windows x86_64 Core release package is named:

```text
EmuKit_1.0.0_Windows_x86_64.zip
```

There is no extra `1.0.0/` directory between a module folder and its ZIP.

The development ZIP contains its versioned source module directory:

```text
ExampleEmu_1.0.0.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    ├── ExampleEmuManager.py
    ├── ExampleEmuInstaller.py
    ├── ExampleEmuRepair.py
    ├── ExampleEmuUninstall.py
    └── _ExampleEmuCommon.py
```

The release ZIP contains the versioned compiled module directory:

```text
ExampleEmu_1.0.0_Windows_x86_64.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    └── ExampleEmuManager.exe
```

The release Info JSON must point `Manager` at the executable actually present in the release package.

Core 1.0.0 consumes the platform manifest for runtime discovery, download, and update decisions.

The backend per-module `<Module>_Manifest.json` and release `<Module>_Release_Manifest.json` are retained module-version catalogues for their respective channels. They record available versions and package hashes, but Core 1.0.0 does not require a second lookup through those files to install a module advertised by the active platform manifest.

Development and release packages are different artifacts and are hashed independently. Never copy the development ZIP checksum into a release manifest or the release ZIP checksum into a development manifest.

## Development Workflow

A normal module-development workflow is:

```text
Create the canonical source module locally
→ place it under EmuKitModules
→ run EmuKit
→ local discovery registers the module
→ develop and test check/install/uninstall/repair/update
→ verify progress reporting
→ package the source module
→ calculate the exact development ZIP SHA-256
→ update the development per-module manifest
→ update the development platform manifest
→ remove the local module copy
→ install through the development feed
→ verify package download, hash verification, extraction, discovery, progress, and emulator installation
→ compile the manager for the release target
→ create a release Info JSON pointing Manager at the compiled executable
→ package the target-qualified release ZIP
→ calculate the exact release ZIP SHA-256
→ update the release per-module manifest
→ update the release platform manifest
→ test acquisition and lifecycle behavior through the release channel
```

A locally present development module does not need a remote platform-manifest entry.

When a package is rebuilt in place while retaining the same `ModuleVersion`, every manifest that references that exact ZIP must receive the new SHA-256 before the package is published.

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

Python lifecycle handlers return these dictionaries directly to Core.

Executable managers wrap the final dictionary inside the strict JSONL result record described in the next section.

## Progress

Progress is part of the current module contract.

Python lifecycle handlers must accept the `progress` keyword argument. Core invokes handlers as:

```python
handler(progress=progress)
```

A handler may report progress with:

```python
progress(percent=25, stage="Downloading", message="Downloading emulator package.")
```

The current executable-manager contract is strict newline-delimited JSON.

Core invokes a compiled manager as:

```text
<Manager.exe> <operation> --json
```

The executable's stdout is a machine-only JSONL stream.

Progress record:

```json
{"type":"progress","percent":25,"stage":"Downloading","message":"Downloading emulator package."}
```

Final result record:

```json
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu installed successfully.","details":{}}}
```

Executable managers must:

- emit only JSON objects on stdout
- emit one complete JSON object per line
- flush progress records immediately
- use `type: "progress"` for progress
- use `type: "result"` for the final lifecycle result
- emit exactly one final result
- never emit progress after the final result
- keep progress percent between `0` and `100` when a percentage is supplied
- use `null` or strings for `stage` and `message`
- use stderr for diagnostic text that is not part of the machine protocol
- exit `0` when the final result is successful
- exit non-zero when the final result is unsuccessful

Blank stdout records, plain text, malformed JSON, unknown record types, duplicate final results, progress after the result, or a missing final result are protocol errors.

There is no legacy plain-text or single-final-JSON fallback.

Long operations should report meaningful stages and percentages. Instantaneous operations may report only a small number of progress events, but every lifecycle handler must support the progress interface.

## Current Module Contract Policy

Core 1.0.0 and current modules use one current contract.

Do not add legacy manager-protocol fallbacks, old emulator installation paths, alternate host-detection systems, or compatibility branches for obsolete EmuKit layouts.

When the contract intentionally changes during active development, update Core, the affected modules, the templates, the examples, and this documentation together.

ProjectHomelab's current EmuKit source convention also avoids comments and docstrings in Core/module runtime code and reusable Python module templates. Keep implementation names and structure clear instead of adding explanatory source comments.

Compiled managers must resolve their module directory from `sys.executable` when frozen. Source managers use `__file__`.

Canonical module-directory selection is:

```python
MODULE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
```

Module root resolution then searches upward for `.ProjectHomelabRoot`. If the marker is absent, the module may resolve the nearby standalone EmuKit runtime/`EmuKitModules` relationship, but it must not introduce a second ProjectHomelab host marker.

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

Before publishing or relying on a Core/module set:

- Core still resolves ProjectHomelab only through `.ProjectHomelabRoot`
- standalone root behavior still works
- shared Core dependency preflight still succeeds
- source modules are discoverable below `EmuKitModules`
- module Info JSON paths resolve below `ROOT/Emulators`
- Python lifecycle handlers accept `progress`
- compiled managers use frozen-safe `sys.executable` module-directory resolution
- compiled managers implement strict JSONL progress/result stdout
- compiled managers emit no plain-text stdout
- `check`, `install`, `uninstall`, `repair`, and `update` all return valid structured results
- long lifecycle operations report live progress
- game launch works
- emulator-only launch works
- development package SHA-256 matches the exact development ZIP
- development per-module and platform manifests agree
- release package uses the target-qualified filename
- release Info JSON points at the compiled manager
- release package SHA-256 matches the exact release ZIP
- release per-module and platform manifests agree
- no stale checksum remains after rebuilding a package in place
- no obsolete EmuKit compatibility path or protocol has been reintroduced
- Core/module runtime Python source and reusable Python templates contain no comments or docstrings

