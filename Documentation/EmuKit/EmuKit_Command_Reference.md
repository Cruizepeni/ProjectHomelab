# EmuKit Command Reference

## Discovery

```text
Get Catalogue
```

Displays the complete platform catalogue.

```text
Get Brand Catalogue
```

Lists every catalogue brand.

```text
Get System Catalogue
```

Lists every system as a human-readable brand-qualified name, for example:

```text
Microsoft Xbox
Microsoft Xbox 360
Nintendo Game Boy Advance
Sony PlayStation
Sony PlayStation 2
```

```text
Get Emulator Catalogue
```

Lists every emulator.

```text
Get <Brand> Catalogue
```

Lists systems belonging to one brand.

```text
Get <System> Catalogue
```

Lists emulators supporting one system and identifies the recommended primary.

```text
Get <Emulator> Catalogue
```

Lists systems supported by one emulator.

Typed forms may be used when an entity name is ambiguous:

```text
Get Brand <Name> Catalogue
Get System <Name> Catalogue
Get Emulator <Name> Catalogue
```

## Info

```text
Get <Brand> Info
Get <System> Info
Get <Emulator> Info
```

Info is not a catalogue alias. It renders detailed metadata for one entity.

Typed forms are:

```text
Get Brand <Name> Info
Get System <Name> Info
Get Emulator <Name> Info
```

## Local State

These commands list installed emulator applications:

```text
Get Current Installs
Get Installed Emulators
```

These commands list locally present EmuKit module packages:

```text
Get Current Modules
Get Installed Modules
```

These commands are intentionally separate because module presence and emulator-application installation are different states.

## Runtime State

```text
Get Running Emulators
Is <Emulator|System> Running
Close <Emulator|System>
Restart <Emulator|System>
```

## Launch

```text
Launch <Emulator>
Launch <GamePath> <System>
Launch <Emulator> <GamePath> <System>
```

A system-only game launch uses the effective system primary.

## Emulator Application Lifecycle

```text
Install <Emulator(s)>
Install All
Uninstall <Emulator(s)>
Uninstall All
Repair <Emulator(s)>
Update <Emulator(s)>
```

`Install <Emulator>` and `Install All` both run a Core preflight check. State `installed` is skipped, state `missing` is installed, and state `broken` is reported for Repair rather than overwritten.

Lifecycle failures are presented with operation-specific terminal states such as `Install Failed`, `Repair Failed`, `Update Failed`, `Uninstall Failed`, and `Check Failed`.

## Module Package Lifecycle

```text
Remove <Emulator(s)>
Remove All
```

Remove deletes local EmuKit module packages. It does not uninstall emulator applications.

## Updates

```text
Updates
Check Updates
Check for Updates
Get Updates
Update EmuKit
```

## Primary Emulator Settings

```text
Set <Emulator> as <System> Primary
Restore <System> Primary
Restore Systems Primary
```

## Settings and Status

```text
Get Settings
Set Feature Fullscreen True|False
Get Status
Get Core Dependencies
```

## Utility

```text
Help
Close
```

Append `--json` where supported for machine-readable output and `--verbose` for expanded lifecycle details.
