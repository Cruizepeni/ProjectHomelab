# EmuKit Updater

## Purpose

`EmuKitUpdater` is EmuKit's disposable internal Core-update module.

It exists because a running Core cannot safely replace its own executable and version directory. Core stages the next release and hands control to a small external updater process, then exits.

The Updater is infrastructure, not an emulator. It is never included in the emulator catalogue and must not appear in `Install All`, `Get Emulator Catalogue`, or normal emulator module commands.

## Source Location

The canonical source module is platform-neutral:

```text
SourceCode/
└── EmuKit/
    └── EmuKitModules/
        └── Updater/
            ├── EmuKitUpdater_Manifest.json
            └── EmuKitUpdater_1.0.0.zip
```

Development source package:

```text
EmuKitUpdater_1.0.0.zip
└── EmuKitUpdater_1.0.0/
    └── EmuKitUpdater.py
```

Do not package `__pycache__`, `.pyc`, `.pyo`, `build`, or `dist` artifacts into the source ZIP.

The source manifest records the exact source ZIP SHA-256.

## Source Manifest

Canonical schema version 1 shape:

```json
{
  "SchemaVersion": 1,
  "Id": "updater",
  "Name": "EmuKit Updater",
  "Kind": "core-updater",
  "Channel": "development",
  "Latest": "1.0.0",
  "Versions": {
    "1.0.0": {
      "Status": "supported",
      "Package": "EmuKitUpdater_1.0.0.zip",
      "SHA256": "replace-with-source-package-sha256",
      "RootDirectory": "EmuKitUpdater_1.0.0",
      "EntryPoint": "EmuKitUpdater.py",
      "SupportedPlatforms": [
        "Windows",
        "Linux",
        "Mac"
      ]
    }
  }
}
```

The source is intentionally OS-agnostic where practical. Platform-specific compiled artifacts are produced from the same source.

## Release Location

Each platform publishes its compiled Updater below that platform's EmuKit module feed.

Windows x86_64:

```text
Resources/
└── EmuKit/
    └── EmuKitModules/
        └── Windows/
            └── Updater/
                ├── EmuKitUpdater_Release_Manifest.json
                └── EmuKitUpdater_1.0.0_Windows_x86_64.zip
```

Release package:

```text
EmuKitUpdater_1.0.0_Windows_x86_64.zip
└── EmuKitUpdater_1.0.0/
    └── EmuKitUpdater.exe
```

The package ZIP, not the inner executable, is the artifact whose SHA-256 is advertised by the release manifest and platform manifest.

## Release Manifest

Example Windows release manifest:

```json
{
  "SchemaVersion": 1,
  "Id": "updater",
  "Name": "EmuKit Updater",
  "Kind": "core-updater",
  "Platform": "Windows",
  "Channel": "release",
  "Latest": "1.0.0",
  "Versions": {
    "1.0.0": {
      "Status": "supported",
      "Package": "EmuKitUpdater_1.0.0_Windows_x86_64.zip",
      "SHA256": "replace-with-release-package-sha256",
      "RootDirectory": "EmuKitUpdater_1.0.0",
      "Executable": "EmuKitUpdater.exe"
    }
  }
}
```

The per-Updater release manifest is retained distribution metadata. Runtime Core acquisition is driven by the platform release manifest.

## Platform Manifest Registration

The compiled Updater is registered under `InternalModules`, not public `Modules`:

```json
{
  "InternalModules": {
    "updater": {
      "Name": "EmuKit Updater",
      "Kind": "core-updater",
      "Version": "1.0.0",
      "Package": "Updater/EmuKitUpdater_1.0.0_Windows_x86_64.zip",
      "SHA256": "replace-with-release-package-sha256",
      "RootDirectory": "EmuKitUpdater_1.0.0",
      "Executable": "EmuKitUpdater.exe"
    }
  }
}
```

`InternalModules` keeps infrastructure modules in the legitimate platform distribution manifest without making them emulator modules.

The platform manifest and `EmuKitUpdater_Release_Manifest.json` must agree on version, package filename, and SHA-256.

## Runtime Flow

Core performs the network and integrity work before launching the Updater:

```text
Core detects a newer Core release
→ downloads Core ZIP
→ verifies Core ZIP SHA-256
→ downloads Updater ZIP
→ verifies Updater ZIP SHA-256
→ safely extracts Updater ZIP
→ resolves RootDirectory + Executable
→ launches Updater
→ exits
```

The Updater then:

```text
waits for old Core PID to exit
→ safely extracts the staged Core package
→ validates the expected EmuKit_<Version> Core root
→ copies the old Core executable into the new Core as a temporary rollback executable
→ moves the old Core directory into update staging
→ installs the new Core version directory
→ applies the Windows folder icon when applicable
→ launches new Core with fresh-update handoff arguments
→ exits
```

If installation/handoff fails before the new Core takes ownership, the Updater restores the old Core directory.

The new Core owns final cleanup after successful startup/migration.

## Updater CLI Contract

Core launches the Updater with:

```text
--old-pid <PID>
--from-version <Version>
--to-version <Version>
--core-package <Path>
--core-directory <Path>
--core-executable <RelativePath>
```

`--core-executable` is deliberately passed by Core rather than hardcoded by the Updater. This allows the same source logic to support platform-specific Core executable names.

The Updater returns `0` on successful handoff and non-zero on failure. It is intentionally dependency-light and may write a concise fatal error to stderr when handoff fails.

## Core Fresh-Update Handoff

The newly launched Core receives handoff fields including:

```text
--fresh-update
--from-version <Version>
--updater-pid <PID>
--updater-path <Path>
--staging-path <Path>
```

Core then:

- runs migrations
- confirms it initialized successfully
- waits for the Updater process to exit
- removes the temporary old executable
- removes staging/update leftovers
- removes the disposable Updater copy where appropriate

Migration belongs to Core, not to the Updater.

## Windows Build

Compile the Windows updater from the unpacked source package.

Example:

```powershell
py -m PyInstaller --clean --noconfirm --onefile --console --name EmuKitUpdater EmuKitUpdater.py
```

ProjectHomelab has a shared generic Updater icon under:

```text
Resources/Icons/Shared/Updater/
```

When the canonical `.ico` asset is selected, add it to the Windows build with PyInstaller's `--icon` option.

The output distributed inside the release package is:

```text
EmuKitUpdater.exe
```

The target-qualified platform ZIP remains:

```text
EmuKitUpdater_1.0.0_Windows_x86_64.zip
```

## Windows Folder Identity

After installing a new Core, the Updater applies the icon embedded in the new `EmuKit.exe` to its versioned folder by creating `desktop.ini` and applying the Explorer folder attributes.

Equivalent shell configuration:

```ini
[.ShellClassInfo]
IconResource=EmuKit.exe,0
```

This behavior is Windows-only. Linux and Mac simply skip it.

## Safety Requirements

The Updater must:

- reject absolute or parent-traversing Core executable paths
- safely validate ZIP extraction targets
- wait for the old Core process to exit before replacement
- never overwrite an unexpected existing destination silently
- preserve a rollback path until the new Core is launched
- restore the old Core when the swap/handoff fails before ownership transfers
- never perform settings-schema migration itself
- never depend on emulator catalogue data

## Publication Checklist

Before publishing a target Updater package:

```text
source package contains no cache/build artifacts
source manifest SHA matches exact source ZIP
compiled executable starts on target OS/architecture
release ZIP contains exactly one declared RootDirectory
release ZIP contains declared Executable
release ZIP SHA is recalculated after every rebuild
Updater release manifest contains that exact SHA
platform release manifest InternalModules.updater contains that exact SHA
Kind is core-updater
Core can download, verify, unpack, and execute the package
successful Core update is tested end-to-end
failed handoff rollback is tested
new Core fresh-update cleanup is tested
Windows folder identity is verified on Windows builds
```
