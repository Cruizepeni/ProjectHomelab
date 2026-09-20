# EmuKit Progress Reporting Standard

## Purpose

EmuKit progress output should use the same wording for the same kind of work across Core and every emulator module while still allowing emulator-specific steps when the work genuinely differs.

## Progress Event Roles

`stage` describes the kind of work currently being performed.

`message` identifies the specific file, resource, package, configuration target, or other item involved in that stage.

`percent` represents overall progress for the current EmuKit operation. It is not automatically a stage-local percentage.

A download stage must not begin at an arbitrary non-zero percentage merely to reserve progress space. When byte progress is available, actual transferred bytes are mapped into the range assigned to that download within the overall operation. When byte progress is unavailable, the event may use a null percentage until a meaningful overall progress value is available.

## Canonical Core Module Acquisition Stages

- `Downloading Module`
- `Validating Module`
- `Extracting Module`
- `Installing Module`
- `Module Installed`

The module package filename should be carried in `message` during download, validation, and extraction.

## Canonical Emulator Install Stages

Use these exact stage names when the corresponding work exists:

- `Checking Host`
- `Preparing Install`
- `Checking Release`
- `Preparing Resources`
- `Downloading Emulator`
- `Validating Emulator`
- `Extracting Emulator`
- `Installing Emulator`
- `Configuring Emulator`
- `Downloading Resources`
- `Validating Resources`
- `Installing Resources`
- `Downloading Firmware`
- `Validating Firmware`
- `Installing Firmware`
- `Downloading System Data`
- `Validating System Data`
- `Installing System Data`
- `Writing Receipt`
- `Verifying Installation`

Modules should only emit stages for work they actually perform. They do not need identical stage counts or identical percentage boundaries.

## Naming Rules

Do not put the emulator name into a generic stage when the module column already identifies it.

Use:

`Downloading Emulator`

not:

`Downloading Xemu`

Use:

`Installing Resources`

not:

`Installing Xbox resources`

Use the `message` field for specificity such as:

`xemu-win-release.zip`

`bios_CD_E.bin`

`PS3UPDAT.PUP`

`config.yml`

## Validation And Verification

`Validating` means checking a downloaded or staged artifact before or during installation, such as a checksum, size, archive integrity, firmware package, or resource file.

`Verifying Installation` means the final post-install check that the managed emulator installation is healthy and usable.

## Completion

Module install logic should normally finish below 100 percent after its final verification step.

Core owns the final normalized install result and emits the final `Installed 100%` event.

The following result message should then use the canonical form:

```text
<Module Name> version "<EmulatorVersion>" installed successfully.
```

Keep the success sentence limited to module name, emulator version, and successful completion. Firmware, resource, profile, and system-specific completion data belongs in structured result `details`.

Module display names shown in progress and result output must begin with a capital letter even when upstream branding begins with lowercase.

This keeps one authoritative completion event and one concise completion sentence for every module.

## Terminal UI Rendering

The interactive terminal UI renders known-percentage progress in this order:

`<Module>  <Progress Bar>  <Percent>  <Stage>  <Message>`

When percent is unavailable, the progress bar and percent are omitted and the module/stage remain visible.

The message is omitted when empty and is suppressed on a 100 percent progress line to avoid duplicating the normalized result message that Core prints immediately afterward.

Consecutive completed progress stages are separated by a single blank line so stacked progress bars remain visually distinct. Core should not add an unnecessary extra blank line between the final progress stage and its normalized operation result.

Terminal rendering is presentation only. Modules continue to emit structured progress events and must not format their own bars, ANSI colours, or terminal control sequences.

## Output Discipline

Progress output is user-facing status, not debug logging.

Do not emit internal function names, stack traces, HTTP chunks, raw child-process output, or every individual filesystem operation as progress.

Use structured failure details for diagnostics and keep normal progress concise.
