# EmuKit Progress Reporting Standard

## Purpose

Every emulator module uses the same stage vocabulary and the same message rules for the same kind of work.

A progress event is not complete if it only says what kind of work is happening when the module knows the concrete file, archive, directory, receipt, firmware image, BIOS, configuration file, or other target being handled.

The standard therefore has two equally important parts:

- `stage` describes the kind of operation.
- `message` identifies the concrete thing being handled.

Emulator-specific stages are allowed only when the underlying work is genuinely different.

## Event Fields

A progress callback receives:

```text
percent
stage
message
```

`percent` is overall lifecycle progress.

`stage` is the canonical lifecycle stage.

`message` is required for emitted module progress and must contain useful context.

For file-oriented or path-oriented work, `message` should identify the actual target. Examples:

```text
Downloading Emulator      exampleemu-4.2.0.zip
Validating Emulator       exampleemu-4.2.0.zip
Extracting Emulator       exampleemu-4.2.0.zip
Installing Emulator       exampleemu.exe
Configuring Emulator      portable.ini
Checking Receipt          .emukit_install.json
Removing Emulator         Emulators/ExampleEmu
Downloading Resources     bios.bin
Installing Firmware       firmware.bin
```

Do not emit vague messages such as:

```text
files
resources
installing
checking
working
```

when a more specific target is available.

## Canonical Install Stages

Use these exact names when the corresponding work exists:

```text
Checking Host
Preparing Install
Downloading Emulator
Validating Emulator
Extracting Emulator
Installing Emulator
Configuring Emulator
Verifying Installation
Writing Receipt
Install Complete
```

Optional emulator-specific install stages include:

```text
Checking Release
Preparing Resources
Downloading Resources
Validating Resources
Installing Resources
Downloading Firmware
Validating Firmware
Installing Firmware
Downloading System Data
Validating System Data
Installing System Data
```

When multiple resources are processed, emit per-file progress when practical so the user can see the current BIOS, firmware, resource, or system-data file.

Avoid an aggregate stage such as `Installing Resources` with a generic message like `9 files` if the module can report the individual files as they are handled.

## Canonical Check Stages

```text
Checking Host
Checking Installation
Checking Emulator
Checking Configuration
Checking Receipt
Checking Integrity
Checking Resources
Checking Release
Check Complete
```

Emit only stages that the module actually performs.

The message should identify the target being checked. Examples:

```text
Checking Emulator         exampleemu.exe
Checking Configuration    portable.ini
Checking Receipt          .emukit_install.json
Checking Integrity        exampleemu.exe
Checking Resources        bios.bin
Checking Release          Version 4.2.0
Check Complete            Version 4.2.0
```

## Canonical Uninstall Stages

```text
Preparing Uninstall
Removing Emulator
Verifying Uninstall
Uninstall Complete
```

Messages should identify the managed emulator directory or specific object being removed or verified.

## Canonical Repair Stages

```text
Preparing Repair
Checking Installation
Preserving User Data
Repairing Configuration
Restoring User Data
Repair Complete
```

Install stages may also appear during repair when repair performs a clean reinstall.

Messages should identify the recovery directory, preserved files, configuration file, executable, or other target involved.

## Update Progress

Update normally composes `check` and `repair`/reinstall progress rather than inventing a separate generic vocabulary.

The final result state is:

```text
already_current
updated
update_failed
```

Core presents failed update lifecycles as:

```text
Update Failed
```

## Completion Events

Module implementations explicitly emit their lifecycle completion stage at module-level `100%`:

```text
Install Complete
Check Complete
Repair Complete
Uninstall Complete
```

The completion message should identify the completed version or target.

Examples:

```text
Install Complete          Version 4.2.0
Check Complete            Version 4.2.0
Repair Complete           Version 4.2.0
Uninstall Complete        Emulators/ExampleEmu
```

Core owns the authoritative terminal presentation.

When forwarding module progress, Core reserves terminal `100%` for the final lifecycle result. A module-reported `100%` completion event is forwarded to the terminal as `99%`, then replaced by Core's final authoritative terminal state after the manager result is known.

A successful install therefore finishes visually as:

```text
ExampleEmu          100%  Installed
```

not as two permanent lines for `Install Complete` and `Installed`.

## Failure Events

Core uses operation-specific terminal failure stages:

```text
Check Failed
Install Failed
Uninstall Failed
Repair Failed
Update Failed
```

Any stage ending in `Failed` is terminal in the UI.

Failures may originate from:

- module acquisition
- pre-operation checks
- explicit module `success: false` results
- checksum or archive validation
- resource or firmware handling
- installation verification
- unhandled module exceptions
- unexpected lifecycle states

All of those paths must converge on the operation-specific failure state.

A module must never present `Installed`, `Repaired`, `Updated`, or `Uninstalled` unless Core has received a successful final lifecycle result.

## Result Messages

Successful install:

```text
<Emulator> Version <version> installed successfully.
```

Successful check:

```text
<Emulator> Version <version> is installed and valid.
```

Already-current update:

```text
<Emulator> Version <version> is already current.
```

Successful update:

```text
<Emulator> Version <version> updated successfully.
```

Successful uninstall:

```text
<Emulator> uninstalled successfully.
```

Successful repair:

```text
<Emulator> repaired successfully.
```

Failure result messages should identify the operation and useful cause without dumping raw internal state into normal terminal output.

## Display Names

Progress and result messages use public emulator display names from module metadata.

Stable internal module IDs remain lowercase machine-safe identifiers.

## Validation vs Verification

`Validating Emulator` means validating downloaded or staged emulator bytes before installation.

`Verifying Installation` means checking final installed state after installation.

Do not interchange these meanings.

## Output Discipline

Progress is user-facing status, not debug logging.

Do not emit:

- internal function names
- Python stack traces during normal successful work
- raw HTTP chunks
- every low-level filesystem operation
- unmanaged child-process output
- ANSI formatting from module code

The terminal UI owns presentation.

## JSONL Example

```json
{"type":"progress","percent":5,"stage":"Checking Host","message":"Windows x86_64"}
{"type":"progress","percent":10,"stage":"Preparing Install","message":"Emulators/ExampleEmu"}
{"type":"progress","percent":30,"stage":"Downloading Emulator","message":"exampleemu-4.2.0.zip"}
{"type":"progress","percent":65,"stage":"Validating Emulator","message":"exampleemu-4.2.0.zip"}
{"type":"progress","percent":75,"stage":"Extracting Emulator","message":"exampleemu-4.2.0.zip"}
{"type":"progress","percent":84,"stage":"Installing Emulator","message":"exampleemu.exe"}
{"type":"progress","percent":90,"stage":"Configuring Emulator","message":"portable.ini"}
{"type":"progress","percent":95,"stage":"Verifying Installation","message":"exampleemu.exe"}
{"type":"progress","percent":98,"stage":"Writing Receipt","message":".emukit_install.json"}
{"type":"progress","percent":100,"stage":"Install Complete","message":"Version 4.2.0"}
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu Version 4.2.0 installed successfully.","details":null}}
```

Core may render the module's `Install Complete` event at `99%` while it waits for the final result, then render the authoritative `100% Installed` state.
