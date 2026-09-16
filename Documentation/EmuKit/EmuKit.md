# EmuKit

## Purpose

`EmuKit` is ProjectHomelab's emulator-module manager.

EmuKit Core provides shared orchestration. Emulator-specific behavior belongs to emulator modules.

The Core is responsible for:

- ProjectHomelab root detection
- host operating-system detection
- local module discovery
- registry generation
- settings reconciliation
- remote module-manifest discovery
- module package download and SHA-256 verification
- module package installation, update, and removal
- serialized lifecycle invocation
- system-to-module assignment
- emulator launching
- progress and structured operation results

The Core is not responsible for emulator-specific download URLs, firmware rules, BIOS requirements, emulator configuration, emulator repair logic, or emulator update logic.

Those responsibilities belong to each emulator module.

## Versioning

Core source filenames do not contain version numbers.

Canonical Core filenames include:

```text
EmuKit.py
EmuKitManager.py
EmuKitSettings.py
EmuKitLauncher.py
```

The EmuKit Core version belongs to its containing release/version metadata.

Do not create versioned script names such as:

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

Changing one does not imply the others changed.

## Root Resolution

`.ProjectHomelabRoot` is the ProjectHomelab root marker.

When EmuKit starts, it searches upward from its own location for:

```text
.ProjectHomelabRoot
```

If found, that directory is the ProjectHomelab root.

Shared ProjectHomelab locations such as settings, registry, dependencies, resources, and release/source paths are resolved from that root.

If no marker is found, EmuKit operates in standalone mode and treats its own containing directory as its local root.

No other HomeLab-host detection mechanism should be introduced.

## Core Location and Local Modules

EmuKit discovers installed modules from its local EmuKit module location.

A physically present valid module is locally installed even if it does not appear in any remote manifest.

The local module directory is authoritative for:

```text
What module code is physically installed?
```

The generated registry is authoritative for:

```text
What valid local modules did EmuKit discover?
```

A remote platform manifest is authoritative for:

```text
What modules are available to download or update?
```

These are deliberately separate authorities.

## Development and Release Channels

EmuKit uses the same Core behavior in development and release builds.

Only the remote feed root changes.

Development/source builds use:

```text
backend/EmuKit/
```

Release/target builds use:

```text
Releases/EmuKit/
```

Both feeds mirror the same structure.

A normal module-manifest path is:

```text
<feed>/EmulatorModules/<OS>/EmuKit_<OS>_Manifest.json
```

Canonical operating-system names are:

```text
Windows
Linux
Mac
```

Examples:

```text
backend/EmuKit/EmulatorModules/Windows/EmuKit_Windows_Manifest.json
Releases/EmuKit/EmulatorModules/Windows/EmuKit_Windows_Manifest.json
```

Development and release must not use different downloader, installer, registry, or module-lifecycle implementations.

The channel changes the source, not the behavior.

## Development Workflow

A normal module-development workflow is:

```text
Create module locally
→ place it inside EmuKit's local module location
→ run EmuKit
→ local discovery registers the module
→ develop and test lifecycle behavior
→ package the working module
→ publish the package and manifest entry to backend/EmuKit
→ remove the local module copy
→ ask EmuKit to install the module
→ verify remote download, hash verification, extraction, discovery, and installation
→ promote the exact tested package and manifest data to Releases/EmuKit
```

A locally present development module does not need a remote manifest entry.

This is intentional. It allows module development without repeatedly uploading and downloading unfinished code.

## Remote Module Discovery

At startup or on explicit refresh, EmuKit may load the current host platform's remote manifest.

The platform manifest uses schema version `1`.

A minimal empty manifest is:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {}
}
```

A populated manifest maps stable module IDs to package metadata.

Example:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {
    "duckstation": {
      "Name": "DuckStation",
      "Aliases": [
        "PS1",
        "PlayStation"
      ],
      "Version": "1.0.0",
      "Package": "DuckStation/1.0.0/DuckStation_1.0.0.zip",
      "SHA256": "<64-character lowercase sha256>"
    }
  }
}
```

`Package` is relative to:

```text
<feed>/EmulatorModules/<OS>/
```

The remote manifest describes module distribution.

It must not duplicate emulator-specific installation logic from the module.

## Installing a Module

`Install <Module>` has two possible paths.

If the module is already physically present:

```text
resolve local module
→ enable it for management
→ invoke module install()
```

If the module is not physically present:

```text
resolve module from remote platform manifest
→ download package to staging
→ verify SHA-256
→ safely extract package
→ validate contained module registration
→ verify module ID matches requested manifest entry
→ install module package into EmuKit
→ rebuild registry
→ reconcile settings
→ invoke module install()
```

Core installs the module package.

The module installs the emulator.

## Install All

`Install All` operates on the active platform manifest.

For each remote module:

```text
already local
    → do not redownload unnecessarily
missing locally
    → acquire and install module package
then
    → invoke emulator install lifecycle
```

Failures are reported per module and do not silently disappear.

## Updating

There are two separate update concepts.

### Module Package Update

Core owns module-package updates.

Core compares the installed module's `ModuleVersion` with the version advertised by the current remote platform manifest.

A module-package update replaces the module package only after the new package has downloaded, passed SHA-256 validation, and passed module-contract validation.

### Emulator Update

The emulator module owns emulator updates.

Core invokes the module's:

```text
update()
```

handler.

Core does not know how a particular emulator updates itself.

## Removing Modules and Uninstalling Emulators

These are different operations.

### Remove Module

`Remove Module <Module>` removes the EmuKit module package itself.

It does not invoke emulator uninstall logic.

The emulator installation and emulator-owned data are left untouched.

After removal, the registry is rebuilt and assignments that can no longer be satisfied are cleared.

### Uninstall

`Uninstall <Module>` invokes the module's emulator uninstall lifecycle.

The module decides how its managed emulator installation is removed according to the module contract.

The module package may remain installed so the emulator can be installed again later.

## Registry

The registry is generated state.

It must be rebuildable from valid physically present modules.

A missing module directory must eventually disappear from the registry.

The registry is not the authority for whether module files actually exist.

The registry contains normalized module, brand, platform, and system information used by EmuKit.

## Settings

Settings preserve user choices independently from registry regeneration where possible.

Settings may contain:

- global Core settings
- module enabled/managed state
- per-system module assignment

Registry synchronization must not discard unrelated user choices.

Assignments must be cleared when their module or supported system no longer exists.

## Systems and Assignments

Modules declare the systems they support.

EmuKit combines those declarations into a normalized system catalogue.

A system may have multiple supporting modules.

A user may assign one module as the active/default module for that system.

Supported-system presentation should include enough context to be unambiguous, normally Brand + System.

Example:

```text
Nintendo GameCube
Sony PlayStation 2
Microsoft Xbox
```

## Launching

EmuKit supports two launch modes.

### Launch Emulator With Game

A system assignment determines which module launches the game.

Core verifies the module/emulator state before launch and may invoke install or repair when the user has enabled management of that module.

### Launch Emulator Without Game

A module can also be launched without a game.

This is required for emulator configuration, controller setup, graphics settings, maintenance, and emulator-native UI tasks.

Module registration may provide module-level emulator launch arguments in addition to per-system game launch arguments.

## Core Dependencies

Core dependencies must remain generic and genuinely shared.

Emulator-specific runtimes or dependencies belong to the module that requires them.

ProjectHomelab Resources are the controlled source for shared external artifacts where applicable.

Do not add emulator-specific installation knowledge to Core merely because several current modules happen to use the same external component.

## Operation Serialization

Module mutation operations are serialized.

Do not run concurrent install, uninstall, repair, update, module-package replacement, or removal operations that could mutate the same EmuKit/module state.

Read-only discovery and status operations may remain independent when safe.

## Structured Results

Core and modules communicate using structured result objects.

A normal result contains:

```json
{
  "success": true,
  "module": "duckstation",
  "operation": "install",
  "state": "installed",
  "message": "DuckStation installed successfully.",
  "details": {}
}
```

Required semantic fields are:

- `success`
- `operation`
- `state`
- `message`

`module` should be present for module operations.

`details` may contain operation-specific machine-readable information.

Core normalizes incomplete module results but modules should return complete results themselves.

## Progress

Lifecycle handlers may accept a `progress` callback.

Expected usage is conceptually:

```python
progress(percent=25, stage="Downloading", message="Downloading emulator package.")
```

Progress is optional for instantaneous operations but strongly recommended for download, extract, install, repair, and update operations.

## Security and Validation

Before installing a remote module package, Core must:

- download into a staging location
- verify SHA-256 before installation
- reject unsafe archive paths
- reject packages with no valid module
- reject packages containing multiple valid module roots
- reject a package whose module ID does not match the requested manifest entry
- avoid overwriting the working installed module until the replacement package is validated

A failed module-package update should leave the previous valid module recoverable.

## Documentation

Core documentation belongs under:

```text
Documentation/EmuKit/
```

Module-author documentation and contracts belong beside the Core documentation.

Reusable contributor aids belong under:

```text
Documentation/EmuKit/Templates/
```

Concrete non-runtime examples belong under:

```text
Documentation/EmuKit/Examples/
```

Templates and Examples are documentation artifacts. They are not scanned as installed emulator modules.

## Validation Checklist

Before declaring an EmuKit Core build ready:

- `.ProjectHomelabRoot` resolution works
- standalone root fallback works
- host OS maps to Windows, Linux, or Mac
- local valid modules are discovered without a remote manifest
- invalid modules are rejected with useful errors
- registry rebuild works
- settings survive registry rebuild
- active platform manifest validates
- missing network/manifest does not destroy local module functionality
- package download uses staging
- package SHA-256 is verified
- unsafe archive paths are rejected
- acquired module ID matches manifest ID
- registry refresh sees newly acquired modules
- `Install <Module>` works for local and remote modules
- `Install All` handles multiple modules and reports per-module failures
- module-package update is separate from emulator update
- `Remove Module` does not uninstall the emulator
- `Uninstall` invokes module emulator-uninstall behavior
- emulator launch with a game works
- emulator launch without a game works
- operations remain serialized
- structured results remain stable
