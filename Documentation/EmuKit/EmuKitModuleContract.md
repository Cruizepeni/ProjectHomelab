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

The canonical current source layout is:

```text
<EmuKit runtime>/
└── EmuKitModules/
    └── ExampleEmu_1.0.0/
        ├── EmuKitExampleEmuInfo.json
        ├── ExampleEmuManager.py
        ├── ExampleEmuInstaller.py
        ├── ExampleEmuRepair.py
        ├── ExampleEmuUninstall.py
        └── _ExampleEmuCommon.py
```

The current responsibility split is:

- `EmuKitExampleEmuInfo.json`: registration, version, source, host, resource, system, and data-policy metadata
- `ExampleEmuManager.py`: lifecycle gateway, installation-state checks, emulator update routing, and executable JSONL bridge
- `ExampleEmuInstaller.py`: clean known-good installation
- `ExampleEmuRepair.py`: deterministic repair
- `ExampleEmuUninstall.py`: uninstall behavior
- `_ExampleEmuCommon.py`: frozen-safe paths, root resolution, progress helpers, resource helpers, checksums, host checks, and other shared utilities

A module may add files when genuinely required by that emulator, but this is the starting structure for new ProjectHomelab modules.

The canonical release layout for a compiled Windows module is:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
└── ExampleEmuManager.exe
```

The release Info JSON points `Manager` at `ExampleEmuManager.exe`.

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

Development/source packages use a Python manager such as:

```json
"Manager": "ExampleEmuManager.py"
```

Compiled release packages use the executable manager present in that package, for example:

```json
"Manager": "ExampleEmuManager.exe"
```

The source manager must be written so it can also be compiled into the release executable.

Module-directory resolution must be frozen-safe:

```python
MODULE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
```

A compiled one-file manager must not rely on `Path(__file__)` as its installed module location.

Core invokes executable managers as:

```text
<manager> <operation> --json
```

from the module directory.

Executable stdout uses the strict JSONL protocol documented below. A release manager is not allowed to substitute plain console text or a single untyped JSON object.

The lifecycle contract is defined by operations, progress, structured results, and the JSONL executable protocol rather than by one programming language.

## Runtime and Root Resolution

Source and compiled managers must resolve the module directory differently.

Canonical module directory:

```python
MODULE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
```

The module then resolves `ROOT` from `MODULE_DIR`.

The only ProjectHomelab marker is:

```text
.ProjectHomelabRoot
```

Search upward for that marker first.

If the marker is absent, standalone resolution may use the nearby EmuKit runtime relationship, such as an `EmuKitModules` parent or a nearby `EmuKit.py` plus `EmuKitModules`.

Do not introduce another ProjectHomelab root marker or host-detection mechanism.

Managed emulator paths remain below:

```text
ROOT/Emulators/
```

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

Every Python lifecycle handler must accept the `progress` keyword argument.

Canonical signature:

```python
def install(progress: ProgressCallback | None = None) -> dict[str, Any]:
```

Core calls Python handlers with:

```python
handler(progress=progress)
```

The default value may remain `None` so the handler can be invoked directly during development, but accepting `progress` is part of the current contract.

The compiled executable bridge dispatches the same five operations and passes its JSONL progress emitter as the lifecycle callback.

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

Progress is part of the current lifecycle contract.

Supported callback values are:

- `percent`
- `stage`
- `message`

Conceptual use:

```python
emit_progress(progress, 25, "Downloading", "Downloading emulator package.")
```

or:

```python
progress(percent=25, stage="Downloading", message="Downloading emulator package.")
```

Percent may be `None` when a meaningful numeric percentage is unavailable.

When present, percent must remain inside `0..100`.

`stage` and `message` may be strings or `None`.

Long downloads, extraction, installation, repair, update, and uninstall work should report useful live progress rather than remaining at the Core-generated starting state until completion.

Shared module code should provide reusable progress helpers and a scaling helper when one lifecycle operation is composed from several sub-operations.

## Executable Manager JSONL Protocol

Compiled managers use strict newline-delimited JSON on stdout.

Core launches:

```text
ExampleEmuManager.exe install --json
```

The manager must emit one JSON object per line and flush each record.

A progress record is:

```json
{"type":"progress","percent":25,"stage":"Downloading","message":"Downloading emulator package."}
```

A final result record is:

```json
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu installed successfully.","details":{}}}
```

Rules:

- stdout is reserved for protocol records
- every stdout line must contain one JSON object
- blank stdout lines are invalid
- `type` must be `progress` or `result`
- `progress.percent` may be `null` or a number from `0` through `100`
- `progress.stage` may be `null` or a string
- `progress.message` may be `null` or a string
- exactly one final `result` record is required
- the final `result.result` value must be an object
- progress must not be emitted after the final result
- duplicate final results are invalid
- unknown record types are invalid
- malformed JSON is invalid
- plain-text stdout is invalid
- stderr may contain diagnostic text
- successful final results exit with code `0`
- unsuccessful final results exit non-zero

There is no legacy fallback that searches arbitrary stdout for a JSON object.

A manager that violates this protocol fails with a Core manager-protocol error.

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

A stable release tag or immutable upstream artifact should be pinned when practical.

If upstream uses a rolling release, the module should pin enough upstream identity and checksum metadata to prevent a future rolling asset from silently replacing the tested bytes.

When adopting a new emulator build:

```text
verify upstream build
→ test emulator
→ update module source or metadata as needed
→ update EmulatorVersion
→ rebuild the development package
→ calculate its exact SHA-256
→ test through the development feed
→ rebuild each release target
→ calculate each exact release SHA-256
→ test through the release channel
```

`ModuleVersion` identifies the EmuKit module package version and is independent from `EmulatorVersion`.

During active development a package may intentionally be rebuilt in place while retaining its current `ModuleVersion`; when that happens all exact package checksums in the affected channel manifests must be replaced before publication.

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

## Windows Release Build

After the source module passes development-feed testing, compile its manager from inside the module directory.

Example:

```powershell
py -m PyInstaller --clean --noconfirm --onefile --console --name ExampleEmuManager ExampleEmuManager.py
```

Copy the resulting `dist/ExampleEmuManager.exe` into the release module root alongside the release Info JSON.

The release package contains the compiled manager, not the Python lifecycle source files.

The release Info JSON must point `Manager` at the `.exe`.

The manager source must remain import-complete for PyInstaller so its Installer, Repair, Uninstall, and Common dependencies are collected into the executable.

Test the compiled manager directly before packaging:

```powershell
.\ExampleEmuManager.exe check --json
```

Its stdout must contain only strict JSONL protocol records.

## Remote Distribution

Before release packaging, the source/development module ZIP should be tested through the `backend/EmuKit` development feed.

Development package example:

```text
ExampleEmu_1.0.0.zip
```

A Windows x86_64 compiled release package uses the target-qualified name:

```text
ExampleEmu_1.0.0_Windows_x86_64.zip
```

The release package normally contains the external Info JSON plus the compiled executable manager.

The release Info JSON must change `Manager` from the source `.py` entry to the `.exe` entry actually present.

Development and release packages are independent exact byte artifacts. They retain the same stable module identity, intended `ModuleVersion`, emulator-management behavior, and system metadata for that version, but each package has its own SHA-256.

Backend manifests carry the development ZIP SHA-256.

Release manifests carry the release ZIP SHA-256.

Rebuilding either ZIP, even while intentionally keeping `ModuleVersion` unchanged, requires recalculating every manifest checksum that references that ZIP.

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

## Source Policy

Current EmuKit runtime/module Python source and reusable Python templates do not use source comments or docstrings.

Use clear file responsibilities, names, functions, and structured metadata instead.

Do not add legacy protocol fallbacks, obsolete `dependencies/EmuKit/<Emulator>` emulator paths, alternate root markers, or compatibility branches for superseded EmuKit layouts.

When the active contract changes during development, Core, current modules, reusable templates, examples, and contract documentation should be updated together.

## Validation Checklist

Before publishing a module:

- source layout follows the current manager/installer/repair/uninstall/common pattern
- exactly one `EmuKit*Info.json` exists in the module root
- Info JSON parses
- schema `Version` is supported
- stable module `Id` is valid
- `ModuleVersion` is intentional
- `EmulatorVersion` matches the tested emulator build
- source `Manager` exists
- `DependencyPath` resolves to a child of `ROOT/Emulators`
- frozen manager uses `sys.executable` for `MODULE_DIR`
- `.ProjectHomelabRoot` remains the only ProjectHomelab root marker
- required lifecycle handlers exist
- every lifecycle handler accepts `progress`
- `Systems` contains at least one valid system
- every declared system has valid Brand and Platform metadata
- system identity does not conflict with existing modules
- all launch paths and arguments are intentional
- `check()` correctly reports missing, installed, and broken states
- `install()` succeeds from a clean state
- long install work emits live progress
- `repair()` restores a deliberately broken state
- `uninstall()` follows the module's data policy
- `update()` follows the emulator-update policy
- launch with a game works
- launch without a game works
- development ZIP uses the source manager and installs through the development feed
- backend package SHA-256 matches both backend manifests
- release package uses the target-qualified filename
- release Info JSON points at the compiled executable manager
- compiled manager emits strict JSONL progress/result stdout
- compiled manager emits exactly one final result
- compiled manager emits no plain-text stdout
- release package SHA-256 matches both release manifests
- extracted `Id` and `ModuleVersion` match the active platform manifest
- release package installs through the release feed
- rebuilt packages do not retain stale SHA-256 values in manifests
- runtime/module Python source contains no comments or docstrings
- no legacy EmuKit protocol or obsolete emulator path has been introduced

