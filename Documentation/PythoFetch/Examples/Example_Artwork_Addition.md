# Example: Adding PythoFetch Artwork

## Purpose

This example shows how to add native artwork under:

```text
ArtAssetsPythoFetch
```

so the PythoFetch Art Database Build Tool can validate it, merge it with the NeoFetch-derived catalogue, and compile it into the next art database.

There are two different tasks that should not be confused:

1. adding artwork for an operating system or distribution PythoFetch already understands
2. adding support for a genuinely new host operating system

Adding artwork is enough for the first case.

A genuinely new host OS also requires a PythoFetch system collector and runtime changes.

## Current Source Layout

```text
ArtAssetsPythoFetch/
├── Windows/
├── Linux/
├── MacOS/
├── Other/
└── Catalogue.json
```

The current logical families and folder names are:

| Logical family | Folder |
| --- | --- |
| Windows | `Windows` |
| Linux | `Linux` |
| macOS | `MacOS` |
| Other | `Other` |

The logical value is case-sensitive in practice and should be copied exactly.

For macOS artwork:

```text
family = macOS
folder = MacOS
```

## Example 1: Add Artwork for a New Linux Distribution

Assume a new Linux distribution is called:

```text
Example Linux
```

and the runtime identifies its distribution ID as:

```text
examplelinux
```

### Step 1: Create the Artwork File

Create:

```text
ArtAssetsPythoFetch/Linux/ExampleLinux.txt
```

Example content:

```text
${c1}       /\
${c1}      /  \
${c2}     / /\ \
${c2}    / ____ \
${c1}   /_/    \_\
```

Color markers may use:

```text
${c1} through ${c8}
```

The markers are kept in the text file. PythoFetch replaces them with ANSI colors at runtime.

### Step 2: Add the Catalogue Entry

Open:

```text
ArtAssetsPythoFetch/Catalogue.json
```

Add an entry such as:

```json
{
  "id": "ExampleLinux",
  "name": "Example Linux",
  "family": "Linux",
  "variant": "default",
  "file": "Linux/ExampleLinux.txt",
  "aliases": [
    "Example Linux",
    "examplelinux",
    "ExampleLinux"
  ],
  "colors": [
    "2",
    "7"
  ],
  "color_rule": "2 7"
}
```

The minimum required fields are:

```text
id
name
family
variant
file
```

The example includes aliases and colors because those are normally needed for correct runtime matching and presentation.

### Step 3: Update Catalogue Counts

If this was the first native PythoFetch entry, change:

```json
"entry_count": 0
```

to:

```json
"entry_count": 1
```

and change:

```json
"family_counts": {
  "Windows": 0,
  "Linux": 0,
  "macOS": 0,
  "Other": 0
}
```

to:

```json
"family_counts": {
  "Windows": 0,
  "Linux": 1,
  "macOS": 0,
  "Other": 0
}
```

The current Build Tool strictly checks `entry_count`.

`family_counts` should also be maintained accurately so the source catalogue remains truthful and useful even though the current validator does not reject a catalogue solely because those counts are stale.

### Step 4: Build a New Database Version

If the current art database is:

```text
1.0.0
```

build a new version, for example:

```text
python Build_PythoFetchArtDB_1.0.0.py --version 1.0.1
```

The Build Tool will:

```text
validate NeoFetch artwork
validate ExampleLinux.txt
validate the new catalogue entry
merge the two art sources
build PythoFetchArt_1.0.1.db
verify the database
update PythoFetchArtDB_Manifest.json
```

### Step 5: Test the Result

Run PythoFetch from source against the newly generated database.

Confirm that the detected Linux distribution resolves to:

```text
ExampleLinux
```

and that the palette renders correctly.

## Why the Aliases Matter

PythoFetch's Linux runtime tries several values when resolving artwork.

These can include:

```text
full operating-system name
distribution ID
version-stripped distribution name
first word of the operating-system name
```

For a distro such as:

```text
Example Linux 1.0
```

useful aliases can therefore include:

```json
"aliases": [
  "Example Linux 1.0",
  "Example Linux",
  "examplelinux",
  "Example"
]
```

Do not add random aliases purely to increase the list.

Aliases should describe names the runtime can realistically detect for that OS.

## Example 2: Add a Small Variant

Create:

```text
ArtAssetsPythoFetch/Linux/ExampleLinux_Small.txt
```

Then add:

```json
{
  "id": "ExampleLinux_Small",
  "name": "Example Linux Small",
  "family": "Linux",
  "variant": "small",
  "file": "Linux/ExampleLinux_Small.txt",
  "aliases": [
    "Example Linux",
    "examplelinux",
    "ExampleLinux"
  ],
  "colors": [
    "2",
    "7"
  ],
  "color_rule": "2 7"
}
```

PythoFetch prefers `small` artwork when the terminal is narrower than its configured narrow-art threshold.

On a normal-width terminal, `default` remains preferred.

The `default` and `small` entries should therefore share aliases that identify the same operating system.

## Example 3: Replace Existing NeoFetch Artwork

Native PythoFetch artwork can deliberately replace a NeoFetch-derived entry.

Assume the NeoFetch source already contains:

```text
id = Ubuntu
```

Create the replacement artwork:

```text
ArtAssetsPythoFetch/Linux/Ubuntu.txt
```

and add:

```json
{
  "id": "Ubuntu",
  "name": "Ubuntu",
  "family": "Linux",
  "variant": "default",
  "file": "Linux/Ubuntu.txt",
  "aliases": [
    "Ubuntu",
    "ubuntu"
  ],
  "colors": [
    "1",
    "7"
  ],
  "color_rule": "1 7",
  "override": true
}
```

`override: true` is required because the ID already exists in the NeoFetch source.

Without it, compilation fails instead of silently replacing upstream artwork.

Do not use `override: true` on a brand-new ID.

The Build Tool rejects an override when there is nothing to replace.

## Example 4: macOS Artwork

The macOS logical family and filesystem folder intentionally use different capitalization.

Correct:

```json
{
  "id": "MyMacArt",
  "name": "My Mac Art",
  "family": "macOS",
  "variant": "default",
  "file": "MacOS/MyMacArt.txt",
  "aliases": [
    "macOS",
    "Darwin"
  ],
  "colors": [
    "2",
    "7"
  ]
}
```

Artwork file:

```text
ArtAssetsPythoFetch/MacOS/MyMacArt.txt
```

Incorrect:

```json
"family": "MacOS"
```

Incorrect:

```json
"file": "macOS/MyMacArt.txt"
```

Use:

```text
logical family: macOS
folder: MacOS
```

## Artwork ID Rules

Valid ID characters are:

```text
A-Z
a-z
0-9
.
_
+
-
```

Examples of valid IDs:

```text
ExampleLinux
ExampleLinux_Small
Windows_12
My.OS
GNU+Example
```

Avoid spaces in IDs.

IDs are compared case-insensitively for collision detection.

## Variant Rules

Use:

```text
default
small
old
```

for normal PythoFetch artwork.

`default` is the normal choice.

`small` is the compact alternative.

`old` can preserve historical artwork but PythoFetch 1.0.0 does not select `old` automatically.

## Color Rules

An artwork file can switch active colors using markers.

Example:

```text
${c1}AAAA
${c2}BBBB
${c1}CCCC
```

With:

```json
"colors": [
  "4",
  "7"
]
```

`${c1}` uses palette entry `4`.

`${c2}` uses palette entry `7`.

Color values are stored as strings in the existing catalogues and are converted by PythoFetch at runtime.

## Optional Catalogue Fields

The Build Tool accepts optional fields such as:

```text
aliases
colors
color_rule
matcher
parent_matcher
override
original_index
original_id
original_file
```

For native PythoFetch artwork, the fields most authors normally need are:

```text
aliases
colors
override
```

The NeoFetch extraction-specific fields such as:

```text
matcher
parent_matcher
original_index
original_id
original_file
```

are not required for ordinary native artwork.

The Build Tool assigns the compiled source identity from the source folder, so a native entry does not need to declare `"source": "PythoFetch"`.

## Adding a Genuinely New Host Operating System

Adding a TXT file and an `Other` catalogue entry does not make PythoFetch support a completely new operating system.

PythoFetch 1.0.0 currently collects systems for:

```text
Windows
Linux
macOS
```

If Python reports a different host through:

```text
platform.system()
```

the current runtime reports an unsupported operating system.

To add a genuinely new host OS such as a BSD family as a first-class supported provider, development work is required in both the runtime and artwork system.

At minimum, that means considering:

```text
1. Add a system-information collector to PythoFetch.
2. Add dispatch for the new platform.system() value.
3. Choose the provider/family identity used by the runtime.
4. Extend alias generation for the new provider.
5. Decide whether the existing Other family is sufficient or a new art family is required.
6. If adding a new family, update the Art Manager FAMILIES and FAMILY_FOLDERS definitions.
7. Add artwork and Catalogue.json entries.
8. Build a new art database version.
9. Test TUI, classic, and headless modes on the target OS.
10. Add/update release assets and platform naming if the OS will receive packaged builds.
```

The `Other` family is useful for retaining and compiling non-primary artwork, but it does not by itself provide a runtime system collector.

## Pre-Build Checklist

Before running the Build Tool, confirm:

```text
[ ] Artwork file is UTF-8.
[ ] Artwork file is not empty.
[ ] ID uses valid characters.
[ ] ID does not unintentionally collide with another entry.
[ ] family is Windows, Linux, macOS, or Other.
[ ] file begins with the correct folder name.
[ ] macOS uses family macOS and folder MacOS.
[ ] variant is appropriate.
[ ] aliases match realistic detected OS names.
[ ] colors cover the ${cN} markers used by the artwork.
[ ] override is only used for an intentional existing-ID replacement.
[ ] entry_count matches the entries array.
[ ] family_counts has been updated.
[ ] New database version is greater than the existing latest version.
```

## Expected Result

After a successful build, the art database folder should contain the new version:

```text
ArtAssetsDB/
├── PythoFetchArt_1.0.0.db
├── PythoFetchArt_1.0.1.db
└── PythoFetchArtDB_Manifest.json
```

The manifest should now report:

```text
latest_version = 1.0.1
```

and retain the previous `1.0.0` entry.

The editable artwork and catalogue should be committed along with the generated database and updated manifest so another developer can reproduce and inspect the art system.
