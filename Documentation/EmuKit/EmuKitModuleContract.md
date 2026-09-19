# EmuKit Emulator Module Contract

## Purpose

An EmuKit emulator module is the adapter between generic EmuKit Core behavior and one emulator's specific install/repair/update/uninstall behavior.

Core must not contain emulator-specific installation knowledge.

A compliant module tells Core:

- stable module identity
- module version and managed emulator version
- manager entry point
- emulator install/launch locations
- supported systems and identities
- lifecycle process identity when needed
- source/resource metadata
- data/uninstall policy

and implements the lifecycle operations:

```text
check
install
uninstall
repair
update
```

## Package Root

Development:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
├── ExampleEmuManager.py
├── ExampleEmuInstaller.py
├── ExampleEmuRepair.py
├── ExampleEmuUninstall.py
└── _ExampleEmuCommon.py
```

Typical Windows release:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
└── ExampleEmuManager.exe
```

Core discovers `EmuKit*Info.json` and validates the manager entry point it declares.

## Root Resolution

`.AppRoot` is the sole host marker.

Module code starts from its own module directory and searches upward for `.AppRoot`. If found, that directory is `ROOT`.

When no marker exists, a module installed below:

```text
<EmuKit runtime>/EmuKitModules/<ModuleVersionDirectory>/
```

resolves the EmuKit runtime as its standalone `ROOT`.

Do not introduce ProjectHomelab-specific marker names or alternate host detection.

## Required Info Fields

Schema version 1 Info begins with:

```json
{
  "Version": 1,
  "Id": "exampleemu",
  "Name": "ExampleEmu",
  "Aliases": [],
  "ModuleVersion": "1.0.0",
  "EmulatorVersion": "4.2.0",
  "Manager": "ExampleEmuManager.py",
  "DependencyPath": "Emulators/ExampleEmu",
  "LaunchPath": "Emulators/ExampleEmu/ExampleEmu.exe",
  "WorkingDirectory": "Emulators/ExampleEmu"
}
```

Required by Core:

- `Version` = current module Info schema
- machine-safe lowercase `Id`
- non-empty user-facing `Name`
- `Manager`
- `DependencyPath`
- `LaunchPath`
- at least one `Systems` registration

`ModuleVersion` and `EmulatorVersion` are expected for distributed modules and must be non-empty when present.

## DependencyPath

`DependencyPath` is relative to resolved `ROOT` and must resolve to a child directory inside:

```text
ROOT/Emulators/
```

Correct:

```json
"DependencyPath": "Emulators/ExampleEmu"
```

Do not use the obsolete `Dependencies/EmuKit/<Emulator>` layout.

## Manager

Development Info points at the source manager:

```json
"Manager": "ExampleEmuManager.py"
```

Windows release Info normally points at the compiled manager:

```json
"Manager": "ExampleEmuManager.exe"
```

The manager must physically exist beside the Info file.

## Aliases

Top-level module aliases identify the emulator itself only.

Do not put console/system names in emulator aliases.

System aliases live in each system registration and must mirror the platform catalogue.

Core normalizes common formatting differences, so aliases should represent meaningful alternate names rather than every capitalization, spacing, underscore, or hyphen variation.

## Lifecycle

Info may declare:

```json
"Lifecycle": {
  "ProcessName": "ExampleEmu.exe"
}
```

`Lifecycle.ProcessName` is an explicit emulator process identity override. Core also derives process identity from `LaunchPath`.

Lifecycle control must work even when the emulator was started outside EmuKit.

Only override `ProcessName` when the real long-running emulator process differs from the normal launch executable or needs explicit identification.

## DefaultInstalled

`DefaultInstalled` is optional and boolean.

It seeds module enabled state when Core first reconciles a module that has no existing settings entry. It is not a system-primary declaration.

System recommendation/primary policy belongs exclusively to the platform catalogue and `SystemPrimaryOverrides` settings.

## IsolateLaunchConsole

Optional module-level:

```json
"IsolateLaunchConsole": false
```

A system may provide its own value to override module-level behavior for that system's game launch.

This controls normal emulator launching. It does not replace the module's responsibility to contain child processes used during installation, repair, update, or uninstall.

## EmulatorLaunchArguments

Optional module-wide emulator-only arguments:

```json
"EmulatorLaunchArguments": []
```

System game-launch arguments are declared in each system registration.

## Systems

Example:

```json
"Systems": {
  "example.exampleconsole": {
    "Name": "Example Console",
    "Aliases": [
      "EC"
    ],
    "Brand": {
      "Id": "example",
      "Name": "Example",
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
    "FullscreenArgument": null
  }
}
```

A system registration must provide:

- machine-safe system ID
- `Name`
- `Aliases`
- `Brand` identity object
- `Platform` identity object
- `LaunchArguments` list

Optional per-system fields include:

- `LaunchPath`
- `WorkingDirectory`
- `FullscreenArgument`
- `IsolateLaunchConsole`

Do not add a per-system `Default` field. Primary recommendation belongs to the catalogue as `RecommendedPrimary`.

## Catalogue Consistency

The platform catalogue is the public authority for support relationships and aliases.

For every system declared by a module:

- the same system ID must exist in the catalogue
- its public `Name` and `Aliases` should match the catalogue
- the catalogue emulator entry must list the system
- the catalogue system entry must list the emulator

Changing system support or aliases usually requires updating both module Info and catalogue, then rebuilding packages and recalculating all affected hashes.

## Source Metadata

Modules may retain upstream source metadata such as:

```json
"Source": {
  "Type": "PinnedRelease",
  "Provider": "GitHub",
  "Repository": "owner/repository",
  "OfficialWebsite": "https://example.invalid",
  "OfficialRepository": "https://github.com/owner/repository",
  "ReleaseTag": "v4.2.0",
  "Asset": "example.zip",
  "DownloadURL": "https://example.invalid/example.zip",
  "Size": 0,
  "SHA256": "replace-with-upstream-sha256"
}
```

Modules are responsible for pinning/validating the emulator bytes they install.

## Resources

ProjectHomelab-controlled emulator resources may be described through the module's resource metadata.

A module must verify the resources it depends on and install them only into destinations it owns or intentionally manages.

BIOS/firmware requirements and placement rules belong to the module, not Core.

## Data Policy

Info should explicitly record the managed emulator tree and uninstall policy, for example:

```json
"DataPolicy": {
  "ManagedEmulatorPath": "Emulators/ExampleEmu",
  "ResourcesInstalledInsideEmulator": true,
  "UninstallRemovesManagedEmulatorTree": true
}
```

The module's uninstall implementation remains the final authority for what is removed/preserved.

## Lifecycle Result Contract

Lifecycle functions return structured dictionaries with at least:

```json
{
  "success": true,
  "module": "exampleemu",
  "operation": "install",
  "state": "installed",
  "message": "ExampleEmu version \"4.2.0\" installed successfully.",
  "details": null
}
```

Failures should include a stable `error` code and useful `details` when applicable.

A single-target Core operation preserves the module's result message. Keep successful messages useful and specific.

## Check

`check` reports the real managed emulator state and should distinguish at least:

```text
missing
installed
broken
```

Check may validate:

- executable presence
- expected version
- install receipt
- required firmware/resources
- critical generated configuration

## Install

`install` owns clean emulator acquisition and initial configuration.

It should:

- validate host support
- download exact expected bytes
- verify checksums
- install/extract into `ROOT/Emulators/<Module>`
- install required controlled resources
- write receipts/configuration owned by the module
- return structured completion data

## Repair

`repair` restores missing/corrupt managed state without inventing user-data policy.

The module documentation should state whether repair replaces binaries, configuration, firmware copies, writable images, or other managed files.

## Update

`update` means update the emulator to the upstream version the current EmuKit module is designed to manage.

The user-facing Core command is:

```text
Update <Emulator>
```

Core handles module-package update first when a newer EmuKit module exists, then invokes the updated/current module's `update` operation.

There is no public `Update Module` command in Core 1.0.0.

## Uninstall

`uninstall` applies the module's explicit data policy.

Document what happens to saves, states, screenshots, configuration, firmware, profiles, caches, and writable media.

## Remove

`Remove <Emulator>` is a Core operation that removes the EmuKit module package only. It does not call the emulator uninstall operation.

## Strict Executable Manager Protocol

Compiled managers are invoked as:

```text
ExampleEmuManager.exe <check|install|uninstall|repair|update> --json
```

Stdout is reserved for strict JSONL protocol records:

```json
{"type":"progress","percent":25,"stage":"Downloading","message":null}
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu version \"4.2.0\" installed successfully.","details":null}}
```

Exactly one final result record is emitted.

Plain text belongs on stderr, not protocol stdout.

See `Examples/Example_Executable_Manager_JSONL.md` and `EmuKitProgressReportingStandard.md`.

## Lifecycle External Processes

Installer/repair/update/uninstall code owns every child process it starts.

Do not allow external child stdout to leak into manager JSONL stdout or routine EmuKit terminal output.

Capture or redirect child stdout/stderr and return useful diagnostic tails through failure `details`.

Frozen Windows managers must avoid leaking PyInstaller DLL-search state into external programs. Use the shared Common helper pattern.

## Distribution

Development package:

```text
SourceCode/EmuKit/EmuKitModules/Windows/ExampleEmu/ExampleEmu_1.0.0.zip
```

Release package:

```text
Resources/EmuKit/EmuKitModules/Windows/ExampleEmu/ExampleEmu_1.0.0_Windows_x86_64.zip
```

Each channel's exact ZIP bytes have their own SHA-256.

For a changed Info JSON:

```text
edit Info
→ rebuild development/release ZIPs
→ recalculate both ZIP hashes
→ update both per-module manifests
→ update both platform manifests
→ if catalogue changed, recalculate catalogue hash too
```

## Acceptance Checklist

Before publishing a module:

- Info `Version` is supported
- stable `Id` is correct
- display `Name` is correct
- emulator aliases identify the emulator, not systems
- `DependencyPath` resolves inside `ROOT/Emulators`
- source/release `Manager` points to the real entry point
- lifecycle ProcessName is correct when supplied
- `DefaultInstalled` is not being used as a system-primary mechanism
- no system-level `Default` field exists
- system Names/Aliases match the catalogue
- Brand/Platform identities validate
- launch/fullscreen arguments are correct
- check/install/repair/update/uninstall return structured results
- external processes are isolated from JSONL stdout
- development and release package hashes match exact ZIP bytes
- manifests contain current hashes
- compiled manager is tested through compiled EmuKit
- emulator-only and game launch are tested
- manually launched emulator can be detected/closed when lifecycle support is expected
