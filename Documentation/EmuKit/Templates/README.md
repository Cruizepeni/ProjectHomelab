# EmuKit Module Template Set

These templates define the current ProjectHomelab starting point for a new EmuKit module.

## Source Files

For an emulator named `ExampleEmu`, copy and rename:

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

Replace every `ReplaceModule`, `replace-with-*`, source URL, executable name, host rule, resource rule, system identity, and data-policy placeholder with emulator-specific values.

The resulting development module normally has:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
├── ExampleEmuManager.py
├── ExampleEmuInstaller.py
├── ExampleEmuRepair.py
├── ExampleEmuUninstall.py
└── _ExampleEmuCommon.py
```

## Lifecycle Contract

Implement and test:

```text
check
install
uninstall
repair
update
```

Every lifecycle handler accepts `progress`.

The manager template already contains the strict JSONL executable bridge used after compilation.

Do not replace it with plain console output or a legacy single-JSON interface.

## Root Resolution

Keep the frozen-safe module-directory rule:

```python
MODULE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
```

`.ProjectHomelabRoot` is the only ProjectHomelab root marker.

Managed emulator files belong below:

```text
ROOT/Emulators/
```

## Development Package

Package:

```text
ExampleEmu_1.0.0.zip
└── ExampleEmu_1.0.0/
    └── source files
```

Use:

```text
EmuKit_Module_Manifest_Template.json
EmuKit_Platform_Manifest_Template.json
```

Calculate SHA-256 from the exact development ZIP.

## Release Manager

On Windows, compile the manager from inside the completed source module directory:

```powershell
py -m PyInstaller --clean --noconfirm --onefile --console --name ExampleEmuManager ExampleEmuManager.py
```

The resulting executable is:

```text
dist/ExampleEmuManager.exe
```

Create the release Info JSON from:

```text
EmuKit_Module_Info_Release_Template.json
```

with:

```json
"Manager": "ExampleEmuManager.exe"
```

The Windows x86_64 release package is:

```text
ExampleEmu_1.0.0_Windows_x86_64.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    └── ExampleEmuManager.exe
```

Use:

```text
EmuKit_Module_Release_Manifest_Template.json
EmuKit_Platform_Release_Manifest_Template.json
```

Calculate SHA-256 from the exact release ZIP.

Development and release hashes are independent.

## Source Policy

Do not add comments or docstrings to EmuKit Core/module runtime Python or these reusable Python templates.

Do not add legacy protocol fallbacks or obsolete EmuKit path compatibility.

Keep emulator-specific behavior inside the module and generic orchestration inside Core.
