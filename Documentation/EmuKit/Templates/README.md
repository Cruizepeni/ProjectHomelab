# EmuKit Template Set

These templates represent the current EmuKit 1.0.0 contracts for emulator modules, the platform catalogue/manifests, Core release metadata, and the disposable Core Updater.

## Emulator Module Source Files

For an emulator named `ExampleEmu`, copy/rename:

```text
EmuKit_Module_Info_Template.json
→ EmuKitExampleEmuInfo.json

EmuKit_Module_Manager_Template.py
→ ExampleEmuManager.py

EmuKit_Module_Installer_Template.py
→ ExampleEmuInstaller.py

EmuKit_Module_Repair_Template.py
→ ExampleEmuRepair.py

EmuKit_Module_Uninstall_Template.py
→ ExampleEmuUninstall.py

EmuKit_Module_Common_Template.py
→ _ExampleEmuCommon.py
```

Development module root:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
├── ExampleEmuManager.py
├── ExampleEmuInstaller.py
├── ExampleEmuRepair.py
├── ExampleEmuUninstall.py
└── _ExampleEmuCommon.py
```

## Root Contract

`.AppRoot` is the sole host marker.

Managed emulator files belong below:

```text
ROOT/Emulators/
```

## System Metadata

System names and aliases in module Info must mirror the platform catalogue.

Do not use module aliases for console names.

Do not add per-system `Default`; the catalogue owns `RecommendedPrimary` and user overrides live in settings.

## Lifecycle Metadata

Use:

```json
"Lifecycle": {
  "ProcessName": "ExampleEmu.exe"
}
```

when an explicit process identity is useful. It enables Core lifecycle commands even for manually started emulator processes.

## Development Distribution

Use:

```text
EmuKit_Module_Manifest_Template.json
EmuKit_Platform_Manifest_Template.json
EmuKit_Platform_Catalogue_Template.json
```

Repository location:

```text
SourceCode/EmuKit/EmuKitModules/<OS>/<Module>/
```

## Windows Release Distribution

Compile the manager:

```powershell
py -m PyInstaller --clean --noconfirm --onefile --console --name ExampleEmuManager ExampleEmuManager.py
```

Release module:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
└── ExampleEmuManager.exe
```

Release ZIP:

```text
ExampleEmu_1.0.0_Windows_x86_64.zip
```

Use:

```text
EmuKit_Module_Release_Manifest_Template.json
EmuKit_Platform_Release_Manifest_Template.json
```

Repository location:

```text
Resources/EmuKit/EmuKitModules/Windows/<Module>/
```

## Catalogue + Hash Chain

When module Info or catalogue metadata changes:

```text
change Info/catalogue
→ rebuild affected module ZIPs
→ calculate new module ZIP SHA values
→ update per-module manifests
→ update platform manifests
→ calculate new catalogue SHA when catalogue changed
→ update platform Catalogue.SHA256
```

## Updater Templates

Use:

```text
EmuKit_Updater_Manifest_Template.json
EmuKit_Updater_Release_Manifest_Template.json
```

Generic source location:

```text
SourceCode/EmuKit/EmuKitModules/Updater/
```

Windows release location:

```text
Resources/EmuKit/EmuKitModules/Windows/Updater/
```

The release Updater is advertised in platform `InternalModules`, not public `Modules`.

See `../EmuKitUpdater.md` and `../Examples/Example_Updater_Package_Layout.md`.

## Core Manifest Templates

Use:

```text
EmuKit_Core_Manifest_Template.json
EmuKit_Core_Release_Manifest_Template.json
```

Core releases are published below:

```text
Releases/EmuKit/
```

## Packaging Hygiene

Never package:

```text
__pycache__/
*.pyc
*.pyo
build/
dist/
```

unless a specific compiled release artifact is deliberately being copied from a build output into a clean release package.

## Source Policy

Keep emulator-specific behavior inside modules and generic orchestration inside Core.

Do not add legacy path compatibility, alternate root markers, obsolete public command aliases, or old system-assignment behavior to new templates.
