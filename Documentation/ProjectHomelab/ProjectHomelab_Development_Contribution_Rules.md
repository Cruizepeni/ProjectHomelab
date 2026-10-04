# ProjectHomelab Development & Contribution Rules

**Status:** Active project conventions  
**Purpose:** Define the development, packaging, versioning, portability, update, resource, and contribution rules used across ProjectHomelab features.

ProjectHomelab is intentionally contract-driven. Features should be portable, inspectable, independently maintainable, easy to integrate, and predictable for both users and contributors.

---

## 1. Terminology

Use **feature**, **app**, or **standalone app**.

Avoid calling ProjectHomelab components “products”.

Typical component types are:

- Feature
- Feature module
- Feature updater
- Feature assets/resources
- Build tools
- Third-party dependency
- Release

---

## 2. `.AppRoot`

`.AppRoot` is the external integration-root marker used by ProjectHomelab-compatible features that create persistent runtime folders such as `Appdata`, `Dependencies`, caches, settings, registries, or downloaded resources.

A feature does **not** create `.AppRoot` for itself in standalone mode. The marker belongs to the containing application or suite that is integrating the feature.

Example integrated environment:

```text
ProjectHomelab/
├── .AppRoot
├── Appdata/
├── Dependencies/
├── Registry/
└── Features/
    └── TerminalSS/
        └── TerminalSS.exe
```

### Resolution order

Application-root resolution must happen before the feature creates persistent runtime files or folders.

The runtime first establishes its own real location. Packaged Linux AppImages must resolve the outer AppImage path rather than an internal temporary mount/payload path.

Once the feature runtime is correctly contained in its own feature folder, `.AppRoot` discovery begins at the **parent of that feature folder** and walks upward through every ancestor directory until the filesystem root is reached.

The first `.AppRoot` file encountered is authoritative.

Therefore:

```text
nearest ancestor .AppRoot wins
```

There is no arbitrary search-depth limit.

Example:

```text
Outer/
├── .AppRoot
└── Inner/
    ├── .AppRoot
    └── Features/
        └── TerminalSS/
            └── TerminalSS.exe
```

TerminalSS uses:

```text
Outer/Inner/
```

because that is the nearest containing `.AppRoot`.

If `.AppRoot` is found:

```text
APP_ROOT = folder containing .AppRoot
```

The feature then uses the integrating application's shared root structure for persistent paths.

Example:

```text
ProjectHomelab/
├── .AppRoot
├── Appdata/
│   ├── Assets/
│   │   └── TerminalSS/
│   ├── Cache/
│   │   └── TerminalSS/
│   └── Settings/
│       └── TerminalSSSettingsConfig.json
└── Dependencies/
    └── TerminalSS/
```

The feature's relative storage contracts remain the same; only `APP_ROOT` changes.

### Standalone behaviour

If no `.AppRoot` exists anywhere above the feature:

```text
APP_ROOT = feature's own folder
```

Example:

```text
TerminalSS/
├── TerminalSS.exe
├── Appdata/
├── Dependencies/
└── ...
```

No `.AppRoot` marker is created in this standalone folder.

The same runtime therefore works standalone, inside ProjectHomelab, or inside another compatible application implementing the `.AppRoot` contract.

There should not be separate HomeLab and standalone codebases.

### Central root authority

A feature should resolve `APP_ROOT` once during startup and pass that resolved root to the components that need it.

Subsystems such as asset managers, settings managers, dependency managers, migration handlers, and updater logic should not independently invent or rediscover different application roots.

No persistent data should be written until root resolution is complete.

### Stateless feature exception

A feature that does not create persistent application folders does not need to implement self-containment solely for `.AppRoot` compatibility.

For example, a self-contained snapshot utility that reads system information and exits without creating Appdata or dependency trees can remain location-independent.

Features such as TerminalSS and EmuKit that create persistent runtime structures must follow the `.AppRoot` and containment rules.

---

## 3. Feature-folder safety and automatic containment

A packaged feature that creates persistent runtime folders must live inside a folder bearing its own feature name.

Example:

```text
TerminalSS/
└── TerminalSS.exe
```

or:

```text
TerminalSS/
└── TerminalSS.AppImage
```

Folder-name detection may be case-insensitive, but a folder created automatically by the feature should use the canonical feature name.

This requirement prevents a loose executable placed on a Desktop, Downloads folder, or unrelated directory from creating structures such as:

```text
Desktop/Appdata/
Desktop/Dependencies/
Desktop/Registry/
```

### Packaged-runtime bootstrap

If a packaged persistent feature starts outside a folder bearing its own name, it should create the correctly named feature folder beside itself and relocate into it before normal initialization.

Conceptually:

```text
Desktop/
└── TerminalSS.exe
```

becomes:

```text
Desktop/
└── TerminalSS/
    └── TerminalSS.exe
```

Because a running Windows executable cannot safely replace/move itself directly, relocation uses a process handoff:

```text
loose runtime
    -> create FeatureName/
    -> copy runtime into FeatureName/
    -> launch relocated copy with an internal relocation handoff
    -> original process exits
    -> relocated copy waits for the original PID to exit
    -> relocated copy verifies the old file matches itself
    -> remove the original loose copy
    -> resolve .AppRoot
    -> continue normal startup
```

Linux packaged runtimes follow the same logical contract while preserving executable permissions.

If a runtime already exists at the intended destination, the loose runtime must **not** silently overwrite it. The operation should stop and report the existing installation rather than using containment as an undocumented update mechanism.

### Source-code exception

Raw source execution must never auto-relocate or rearrange the source repository.

When running from Python source, the source directory acts as the feature runtime directory unless an external ancestor `.AppRoot` is found.

Automatic feature-folder creation is therefore a packaged-runtime behaviour, not a source-development behaviour.

### Filesystem boundary

`.AppRoot` discovery walks normal ancestor directories until the current filesystem path reaches its root. It does not jump sideways into unrelated directories or perform a broad filesystem search.

---

## 4. ProjectHomelab version format

ProjectHomelab components use:

```text
X.Y.Z
```

Where:

```text
X = HomeLab Generation
Y = Major Version
Z = Minor Version
```

Example:

```text
1.2.14
```

---

## 5. HomeLab Generation — `X`

The first number represents the **ProjectHomelab Generation**.

Generation changes are expected to be rare. Most ProjectHomelab changes should occur without changing generation.

When ProjectHomelab eventually moves to a new generation:

```text
1.x.x → 2.x.x
```

all actively maintained ProjectHomelab features receive a corresponding generation release.

For example:

```text
TerminalSS_2.x.x
PythoFetch_2.x.x
EmuKit_2.x.x
```

Old-generation releases are then archived and become **archived, deprecated, and unsupported**.

Users may manually retrieve and run archived software at their own risk, but ProjectHomelab provides no current compatibility or support guarantee.

The officially supported software is always identified by the current generation.

---

## 6. Major Version — `Y`

The second number represents a meaningful compatibility or capability change to a feature.

Examples include:

- major new feature/module
- important architecture redesign
- new platform support
- major data/resource format change
- new integration contract
- major UI/application behaviour change

Example:

```text
TerminalSS_1.1.0
→
TerminalSS_1.2.0
```

The Major Version is also a **compatibility lock for that feature's supporting components**.

If TerminalSS is `1.2.x`, its officially supported updater, assets, and resources must also have a compatible `1.2.x` release family.

---

## 7. Minor Version — `Z`

The final number represents maintenance within the same compatibility family.

Examples include:

- dependency refresh
- compatibility patch
- emulator update
- FFmpeg update
- asset curation update
- small bug fix
- minor resource update

The exact `Z` numbers do **not** need to match between compatible components.

This is valid:

```text
TerminalSS_1.2.0
TerminalSSUpdater_1.2.7
Alien_1.2.34
Matrix_1.2.8
Mystic_1.2.19
```

because everything belongs to the `1.2.x` compatibility family.

---

## 8. Feature compatibility family

The compatibility family for a feature is:

```text
X.Y
```

Example:

```text
1.2
```

Official TerminalSS `1.2.x` resources should come from the TerminalSS `1.2.x` family.

Do not officially pair `TerminalSS_1.2.x` with `TerminalSSUpdater_1.1.x` or `Alien_1.0.x`, even if they happen to work.

Possible compatibility is not the same as supported compatibility.

When a feature moves Major Version, its supporting components are reviewed and receive matching Major-Version releases even if some require no actual changes.

---

## 9. HomeLab feature requirements

ProjectHomelab itself does **not** need to chase every feature update.

If HomeLab works perfectly with `Feature_1.0.0`, it may continue using that version.

If a later HomeLab change requires behaviour introduced in `Feature_1.6.4`, then a HomeLab maintenance update can change its requirement to:

```text
Feature >= 1.6.4
```

within whatever compatibility constraints apply.

The philosophy is:

> Support a compatible version until there is an actual reason to increase the requirement.

---

## 10. Source-code versioning rules

### Multi-script feature

A feature consisting of multiple scripts is versioned by its **folder**.

Example:

```text
SourceCode/
└── TerminalSS/
    └── TerminalSS/
        └── TerminalSS_1.0.0/
            ├── TerminalSS.py
            ├── TerminalSSUI.py
            ├── TerminalSSAssetManager.py
            └── TerminalSSHackerSimulator.py
```

Do not unnecessarily rename every internal module with the version. The containing version folder already identifies the source snapshot.

---

## 11. Single-script module/updater versioning

When a component consists primarily of one script, both its folder and script may carry the version.

Example:

```text
SomeModule_1.3.4/
└── SomeModule_1.3.4.py
```

Feature updaters that are single-script source components follow the same principle.

---

## 12. Multi-script modules

If a feature module grows into a multi-script component, treat it like a normal feature:

```text
ModuleName_1.4.0/
├── ModuleName.py
├── Provider.py
├── UI.py
└── ...
```

The folder provides the version identity.

---

## 13. Source code should remain inspectable

ProjectHomelab source is normally stored as raw files rather than opaque source ZIPs.

The objective is that developers/users can inspect source before downloading, modifying, building, or executing it.

Git history represents exact development history. Component manifests represent the current component/version structure.

Source SHA-256 values may be recorded in manifests where useful, but source development does not rely on immutable release-package hashing in the same way release artifacts do.

---

## 14. Source-code comments and docstrings

ProjectHomelab first-party source should normally contain **no unnecessary comments or docstrings**.

Code should be written so that its structure, filenames, functions, classes, constants, and variable names communicate what the implementation is doing without explanatory clutter.

Avoid routine comments such as:

```python
# Download the manifest
manifest = download_manifest()

def resolve_root():
    """Find the ProjectHomelab root directory."""
```

Prefer clear implementation:

```python
manifest = download_manifest()

def resolve_root():
```

Architectural and behavioural explanation belongs primarily in:

```text
Documentation/
README.md
component documentation
manifest documentation
architecture documentation
```

Documentation should explain things such as:

- architecture
- supported arguments
- workflows
- update contracts
- build procedures
- compatibility rules
- manifest behaviour
- unusual implementation decisions

Comments or embedded notices are acceptable where they are genuinely required, including:

- licence or attribution requirements
- third-party source that must retain original notices
- generated code that should not be manually altered
- unusually obscure platform workarounds where removing the explanation would make future maintenance unsafe or unreasonable

The general rule is:

> **Make the code readable through its design; keep the explanation in the documentation.**

---

## 15. Source manifests

A feature source tree should normally contain a root manifest.

Examples:

```text
SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
SourceCode/TerminalSS/TerminalSS_Source_Manifest.json
```

The root manifest acts primarily as a router to subordinate source components.

Example conceptual structure:

```text
TerminalSS_Source_Manifest.json
    ↓
    ├── TerminalSS/TerminalSS_Manifest.json
    ├── TerminalSSUpdater/TerminalSSUpdater_Manifest.json
    ├── TerminalSSAssets/TerminalSSAssets_Manifest.json
    └── TerminalSSBuildTools/TerminalSSBuildTools_Manifest.json
```

Each component then maintains its own version history.

---

## 16. Canonical manifest entry points and router boundaries

Each first-party feature has three independent top-level manifest entry points, one for each repository environment:

```text
SourceCode/<Feature>/<Feature>_Source_Manifest.json
Releases/<Feature>/<Feature>_Release_Manifest.json
Resources/FirstParty/<Feature>/<Feature>_Resources_Manifest.json
```

These are separate entry points rather than one mandatory traversal chain.

A runtime or tool that already knows which feature/component it requires should normally go **directly to the feature-specific or component-specific manifest**.

For example, a packaged feature checking for its own application update should use:

```text
Releases/<Feature>/<Feature>_Release_Manifest.json
```

directly.

When that feature needs one of its own first-party runtime resources, it should begin at:

```text
Resources/FirstParty/<Feature>/<Feature>_Resources_Manifest.json
```

Generic repository routers such as:

```text
Resources/Resources_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
```

exist for navigation and discovery when the caller does not already know the feature-specific location.

Their primary question is:

> **Where do I go next?**

Generic router records should remain lightweight navigation data, typically containing values such as:

```text
file
path
download_url
```

They should not become duplicated inventories for every child payload.

Feature/component manifests are where actual inventory, compatibility, and verification metadata belongs. Downloadable packages/files should carry SHA-256 and byte-size verification data where applicable.

The general boundary is:

```text
generic repository router
    -> navigation

feature/component manifest
    -> inventory + compatibility + verification metadata

downloadable package/file
    -> SHA-256 + byte size
```

---

## 17. Build Tools

Use the terminology **Build Tool** or **Build Script** rather than treating the Python script itself as a “compiler”.

The build tool may invoke:

- PyInstaller
- AppImage tooling
- packaging logic
- icon handling
- metadata generation
- release ZIP creation
- validation
- checksum generation

The compiler/packager may be one thing used **by** the build tool.

---

## 18. Build-tool naming

The established convention is:

```text
Build_<Feature>_<OS>_<Architecture>_<BuildToolVersion>.py
```

Examples:

```text
Build_PythoFetch_Windows_x86_64_1.0.0.py
Build_PythoFetch_Linux_x86_64_1.0.0.py
Build_TerminalSS_Windows_x86_64_1.0.0.py
Build_TerminalSS_Linux_x86_64_1.0.0.py
```

Build tools remain raw Python scripts and are never themselves turned into EXEs/AppImages.

---

## 19. Build-tool workflow

A build tool is stored separately:

```text
SourceCode/<Feature>/<Feature>BuildTools/
```

When building a feature version, copy the appropriate tool into the version folder, run it there, then remove the copied build script.

The tool derives the application/version from the containing folder and produces the appropriately named release package.

Example:

```text
TerminalSS_1.5.7
→
TerminalSS_1.5.7_Windows_x86_64.zip
```

---

## 20. Build-tool versioning

A Build Tool does **not** need its version increased whenever the feature changes.

If `Build_TerminalSS_Windows_x86_64_1.0.0.py` correctly builds TerminalSS `1.0.0` through `1.0.74`, leave it alone.

If TerminalSS `1.0.75` introduces a change requiring a new build process, create:

```text
Build_TerminalSS_Windows_x86_64_1.0.75.py
```

The Build Tool version therefore indicates the first feature version that required that build process.

Windows and Linux Build Tools may evolve independently.

---

## 21. Repository top-level responsibility

ProjectHomelab deliberately separates:

```text
SourceCode/
Releases/
Resources/
```

### `SourceCode`

First-party source code and developer tooling.

### `Releases`

Built first-party applications/features.

### `Resources`

Things applications need to operate.

Resources begins with:

```text
Resources/
├── Icons/
├── ThirdParty/
└── FirstParty/
```

- `Icons` — Project/application icon assets.
- `ThirdParty` — external dependencies required by ProjectHomelab applications.
- `FirstParty` — first-party resources/assets/dependencies made specifically for ProjectHomelab features.

---

## 22. Release naming

Release ZIPs carry the feature name, version, OS, and architecture.

Examples:

```text
TerminalSS_1.2.0_Windows_x86_64.zip
TerminalSS_1.2.0_Linux_x86_64.zip
PythoFetch_1.6.5_Windows_x86_64.zip
PythoFetch_1.6.5_Linux_x86_64.zip
```

Release manifests retain historical versions, with the latest version listed first or otherwise immediately discoverable.

---

## 23. Installed feature directory

A released feature normally creates/uses a stable feature folder:

```text
TerminalSS/
PythoFetch/
EmuKit/
```

rather than a versioned install directory.

This allows persistent data to remain in a predictable location while the runtime is replaced.

---

## 24. Installed-binary convention

Installed runtime binaries use a **stable unversioned name**, while the exact version is retained in release metadata/manifests and internal runtime metadata where required.

Examples:

```text
PythoFetch/PythoFetch.exe
PythoFetch/PythoFetch.AppImage
```

The exact installed version is tracked through metadata/registry information rather than requiring callers to know a versioned binary filename.

This allows HomeLab and third-party integrations to continue calling the same executable path after an update.

The **release ZIP remains versioned**.

---

## 25. Single-binary release philosophy

Where practical, the end-user release should be a single platform-native application:

```text
Windows: Feature.exe
Linux:  Feature.AppImage
macOS:  appropriate single macOS application format
```

Do not package large piles of loose runtime files unless genuinely required.

If the application requires additional assets/resources, it can fetch them from the appropriate ProjectHomelab repository channel on first run.

Goal:

> Download one application, run it once, and it prepares what it needs.

---

## 26. Updaters and application updates

ProjectHomelab treats feature updaters as independent first-party components rather than hidden self-modifying behaviour inside an application. The updater exists to perform the small amount of work that a running application cannot safely perform on itself.

### 26.1. Updater scope and relationship to the general rules

This section defines the detailed ProjectHomelab updater contract and is authoritative together with the general rules elsewhere in this document.

The general ProjectHomelab rules continue to govern:

- versioning
- platform naming
- architecture naming
- Build Tool naming
- manifests
- release naming
- source layout
- `.AppRoot`
- compatibility families
- checksums
- stable installed runtime names

The updater rules below define the updater implementation pipeline in greater detail.

**Validated updater platforms:** Windows x86_64, Linux x86_64  
**Reference implementation:** PythoFetch / PythoFetchUpdater

---

### 26.2. Core updater principle

A running feature should not overwrite its own executable while it is still running.

The normal architecture is:

```text
Feature
    ↓
detects a compatible update
    ↓
downloads and verifies FeatureUpdater
    ↓
launches FeatureUpdater
    ↓
Feature exits
    ↓
FeatureUpdater stages and installs the new Feature runtime
    ↓
FeatureUpdater launches the new Feature with --updated
    ↓
FeatureUpdater exits
    ↓
new Feature completes post-update work
```

The updater should remain small, predictable, independently versioned, and focused on runtime replacement.

---

### 26.3. Application and updater responsibilities

The application is normally responsible for:

- checking its release manifest
- determining whether an update is available
- selecting the correct platform release
- determining the required updater compatibility family
- locating the updater release manifest
- downloading the updater package
- verifying the updater package
- extracting the updater runtime
- verifying the updater runtime
- launching the updater with the required context
- exiting so replacement can occur
- handling `--updated` after the new runtime starts
- performing application-specific migration and cleanup

The updater is normally responsible for:

- validating the supplied update request
- downloading the target application release
- verifying the downloaded release package
- safely extracting the target runtime
- verifying the extracted target runtime
- waiting for the old application process to exit
- preserving the old runtime as a temporary backup
- placing the new runtime at the stable application path
- restoring the old runtime if replacement fails
- launching the new runtime
- exiting so the new runtime can finish cleanup

The updater should not contain application-specific migration logic when that logic belongs to the new application version.

---

### 26.4. Updater source layout

Updater source is stored as a first-party source component.

Canonical layout:

```text
SourceCode/<Feature>/
├── <Feature>_Source_Manifest.json
├── <Feature>/
├── <Feature>Updater/
│   ├── <Feature>Updater_Manifest.json
│   └── <Feature>Updater_<Version>/
│       └── <Feature>Updater_<Version>.py
└── <Feature>BuildTools/
```

Example:

```text
SourceCode/PythoFetch/
├── PythoFetch_Source_Manifest.json
├── PythoFetch/
├── PythoFetchUpdater/
│   ├── PythoFetchUpdater_Manifest.json
│   └── PythoFetchUpdater_1.0.0/
│       └── PythoFetchUpdater_1.0.0.py
└── PythoFetchBuildTools/
```

A single-script updater carries its version in both the folder and source filename.

---

### 26.5. Updater versioning

The updater is independently versioned.

Example:

```text
PythoFetch_1.0.4
PythoFetchUpdater_1.0.2
```

This is valid when both belong to the same supported compatibility family:

```text
1.0
```

The updater patch version does not need to match the application patch version.

The application should select the newest compatible updater from the required `X.Y` family.

When a feature moves to a new Major Version, its updater receives a matching Major-Version release family even if little or no updater logic changes.

---

### 26.6. Updater compatibility family

Updater compatibility follows the ProjectHomelab feature compatibility family:

```text
X.Y
```

Example:

```text
Feature 1.2.7
    ↓
compatible updater family
    ↓
FeatureUpdater 1.2.x
```

Do not officially pair:

```text
Feature 1.2.x
```

with:

```text
FeatureUpdater 1.1.x
```

even if the updater happens to work.

The updater release manifest should explicitly declare:

```text
compatibility_family
```

for each updater release family.

---

### 26.7. Canonical updater component naming

Updater components use:

```text
<Feature>Updater
```

Examples:

```text
PythoFetchUpdater
TerminalSSUpdater
EmuKitUpdater
BootForgeUpdater
```

Do not introduce alternate forms such as:

```text
<Feature>_Updater
<Feature>-Updater
Updater_<Feature>
```

unless a feature has a documented legacy exception.

---

### 26.8. Canonical platform tokens

Updater packages and Build Tools use the ProjectHomelab platform vocabulary.

Operating systems:

```text
Windows
Linux
MacOS
```

Architectures:

```text
x86_64
arm64
Universal
```

Examples:

```text
Windows_x86_64
Windows_arm64

Linux_x86_64
Linux_arm64

MacOS_x86_64
MacOS_arm64
MacOS_Universal
```

`MacOS` is the ProjectHomelab machine-readable token.

Apple's display branding may still be written as `macOS` in ordinary prose.

---

### 26.9. Updater release package naming

Updater release ZIPs use:

```text
<Feature>Updater_<Version>_<OS>_<Architecture>.zip
```

Examples:

```text
PythoFetchUpdater_1.0.0_Windows_x86_64.zip
PythoFetchUpdater_1.0.0_Linux_x86_64.zip

TerminalSSUpdater_1.0.0_Windows_x86_64.zip
TerminalSSUpdater_1.0.0_Linux_x86_64.zip
```

Future platform examples:

```text
PythoFetchUpdater_1.0.0_Linux_arm64.zip
PythoFetchUpdater_1.0.0_MacOS_arm64.zip
PythoFetchUpdater_1.0.0_MacOS_Universal.zip
```

The package filename is versioned.

The updater runtime inside the package uses a stable unversioned name.

---

### 26.10. Stable updater runtime names

Canonical runtime names are:

```text
Windows:
<Feature>Updater.exe

Linux:
<Feature>Updater
```

Examples:

```text
PythoFetchUpdater.exe
PythoFetchUpdater
```

The Linux updater has no filename extension.

The exact updater version is carried by manifests, source metadata, release package naming, and `--version` output rather than the installed runtime filename.

MacOS runtime packaging is not yet considered validated by ProjectHomelab and should be documented when a real MacOS updater has been built and tested.

---

### 26.11. Why the Linux updater is an ELF, not an AppImage

The normal ProjectHomelab Linux application release may be:

```text
<Feature>.AppImage
```

The updater should normally be:

```text
<Feature>Updater
```

as a plain standalone native ELF executable.

The updater should not normally be wrapped in another AppImage.

The PythoFetch updater work demonstrated why this distinction matters.

An updater exists only to replace the application runtime.

Wrapping that helper in another AppImage introduces unnecessary:

- AppImage runtime handling
- FUSE lifecycle
- AppDir construction
- appimagetool packaging
- nested process/runtime behaviour
- environment inheritance
- mount lifecycle complexity
- failure modes during replacement

The plain PyInstaller ELF already provides the single-file Linux updater that ProjectHomelab needs.

Therefore:

> **ProjectHomelab Linux updater helpers should normally be plain standalone ELF executables rather than AppImages.**

A feature that intentionally breaks this rule should document why.

---

### 26.12. Windows updater design

The normal Windows updater runtime is:

```text
<Feature>Updater.exe
```

The current reference design uses:

```text
PyInstaller --onefile
```

with console support enabled so failures and update progress remain observable when appropriate.

Example package:

```text
PythoFetchUpdater_1.0.0_Windows_x86_64.zip
└── PythoFetchUpdater.exe
```

The Windows updater EXE should use the shared ProjectHomelab updater icon rather than the parent feature's application icon.

---

### 26.13. Linux updater design

The normal Linux updater runtime is:

```text
<Feature>Updater
```

The current reference design uses:

```text
PyInstaller --onefile
```

to produce a native ELF executable.

Example package:

```text
PythoFetchUpdater_1.0.0_Linux_x86_64.zip
└── PythoFetchUpdater
```

The Build Tool should:

- verify the expected output exists
- ensure the executable bit is set
- verify the ELF header
- run the generated updater with `--version`
- package only the intended updater runtime

The Linux updater Build Tool does not need:

- AppDir
- AppRun
- appimagetool
- an AppImage runtime
- FUSE packaging
- AppImage desktop metadata
- Pillow solely for AppImage icon preparation

---

### 26.14. MacOS updater status

ProjectHomelab currently has validated updater behaviour for:

```text
Windows x86_64
Linux x86_64
```

MacOS updater behaviour is not yet considered a proven ProjectHomelab implementation.

Canonical package names may already follow the normal naming contract:

```text
<Feature>Updater_<Version>_MacOS_x86_64.zip
<Feature>Updater_<Version>_MacOS_arm64.zip
<Feature>Updater_<Version>_MacOS_Universal.zip
```

However, the exact MacOS updater runtime format, signing behaviour, replacement lifecycle, and Build Tool requirements should not be declared final until a real ProjectHomelab MacOS updater has been built and tested end-to-end.

Do not copy Windows or Linux assumptions into the MacOS specification without validation.

---

### 26.15. Shared updater icons

ProjectHomelab provides shared updater icon assets.

Canonical paths:

```text
Resources/Icons/Shared/Updater/Icon_Updater.ico
Resources/Icons/Shared/Updater/Icon_Updater.png
```

The shared updater icon visually identifies a ProjectHomelab updater as an updater rather than as the parent application itself.

Windows updater builds use:

```text
Icon_Updater.ico
```

for the updater EXE.

The PNG exists for platforms or tooling that require a PNG representation.

A plain Linux updater ELF does not need AppImage desktop/icon machinery simply to perform an update.

If a Linux desktop/launcher representation is later required, the shared PNG should be used rather than inventing a separate unrelated updater icon.

---

### 26.16. Updater Build Tool naming

Updater Build Tools follow the normal ProjectHomelab Build Tool grammar:

```text
Build_<Component>_<OS>_<Architecture>_<BuildToolVersion>.py
```

For updater components:

```text
Build_<Feature>Updater_<OS>_<Architecture>_<BuildToolVersion>.py
```

Examples:

```text
Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
```

Future examples:

```text
Build_PythoFetchUpdater_Linux_arm64_1.0.0.py
Build_PythoFetchUpdater_MacOS_arm64_1.0.0.py
```

---

### 26.17. Build Tool versioning

The Build Tool version is independent from both:

- the parent application version
- the updater component version

Example:

```text
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
```

may build:

```text
PythoFetchUpdater_1.0.0
PythoFetchUpdater_1.0.1
PythoFetchUpdater_1.0.2
```

as long as that Build Tool still correctly performs the required build process.

Increase the Build Tool version when the Build Tool itself changes in a meaningful way.

Do not increase it merely because the updater patch version changed.

---

### 26.18. Updater Build Tool workflow

The canonical Build Tool remains under:

```text
SourceCode/<Feature>/<Feature>BuildTools/
```

To build an updater release:

```text
1. Select the required platform Build Tool.
2. Copy it into the exact updater version folder being built.
3. Run it from that updater version folder.
4. Let it derive the updater version from the containing folder.
5. Validate the updater source/version relationship.
6. Build and test the updater runtime.
7. Create the platform release ZIP.
8. Remove the copied Build Tool after the build.
```

Example temporary build folder:

```text
PythoFetchUpdater_1.0.4/
├── PythoFetchUpdater_1.0.4.py
└── Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
```

The canonical Build Tool remains in:

```text
SourceCode/PythoFetch/PythoFetchBuildTools/
```

---

### 26.19. Source version normalization

The updater version folder is authoritative for the updater version being built.

Example:

```text
PythoFetchUpdater_1.0.4/
```

means the Build Tool is building:

```text
1.0.4
```

The updater source should declare the same version.

A Build Tool may normalize a stale updater source declaration to the containing folder version before building.

The source, folder, generated runtime, package name, and manifest entry must ultimately describe the same updater version.

---

### 26.20. Isolated build environments

Updater Build Tools should create or reuse an isolated build environment rather than relying on arbitrary globally installed Python packages.

The PythoFetch reference Build Tools use an isolated virtual environment and a pinned PyInstaller version.

The purpose is repeatability.

A Build Tool should know which toolchain version it expects rather than silently using whatever happens to exist on the developer machine.

---

### 26.21. Windows updater Build Tool pipeline

The proven Windows pipeline is conceptually:

```text
Updater source
    ↓
validate containing folder/version
    ↓
resolve shared Icon_Updater.ico
    ↓
create/reuse isolated Python build environment
    ↓
install pinned PyInstaller
    ↓
test source with --version
    ↓
PyInstaller --onefile
    ↓
<Feature>Updater.exe
    ↓
test compiled updater with --version
    ↓
create versioned Windows updater ZIP
```

The generated ZIP should contain only the intended updater runtime unless another file is genuinely required by that updater design.

---

### 26.22. Linux updater Build Tool pipeline

The proven Linux pipeline is conceptually:

```text
Updater source
    ↓
validate containing folder/version
    ↓
create/reuse isolated Python build environment
    ↓
install pinned PyInstaller
    ↓
test source with --version
    ↓
PyInstaller --onefile
    ↓
<Feature>Updater
    ↓
set executable permissions
    ↓
verify ELF header
    ↓
test compiled updater with --version
    ↓
create versioned Linux updater ZIP
```

The result is a standalone ELF.

Do not add an AppImage wrapping stage unless a documented feature-specific reason requires it.

---

### 26.23. Required updater command support

A packaged updater should support:

```text
--version
```

so the Build Tool and users can verify the generated updater before it is published.

The updater also needs enough command-line context to perform a specific update request.

The PythoFetch reference implementation uses values equivalent to:

```text
--parent-pid
--target
--current-version
--target-version
--release-manifest-url
```

Future ProjectHomelab updaters should follow the same general contract where applicable.

Feature-specific arguments may be added when required.

Updater invocation must not depend on hidden developer-machine state.

---

### 26.24. Release and resource placement

The parent application release belongs under:

```text
Releases/<Feature>/
```

The updater is a first-party runtime resource and belongs under:

```text
Resources/FirstParty/<Feature>/<Feature>Updater/
```

Example:

```text
Resources/
└── FirstParty/
    └── PythoFetch/
        ├── PythoFetch_Resources_Manifest.json
        └── PythoFetchUpdater/
            ├── PythoFetchUpdater_Release_Manifest.json
            ├── PythoFetchUpdater_1.0.0_Windows_x86_64.zip
            └── PythoFetchUpdater_1.0.0_Linux_x86_64.zip
```

This keeps the application release and the helper used to update that application as separate independently versioned components.

---

### 26.25. Updater release manifest

The updater release manifest uses:

```text
Resources/FirstParty/<Feature>/<Feature>Updater/
<Feature>Updater_Release_Manifest.json
```

Conceptual structure:

```json
{
  "schema": 1,
  "application": "<Feature>",
  "component": "<Feature>Updater",
  "latest_version": "1.0.0",
  "versions": {
    "1.0.0": {
      "compatibility_family": "1.0",
      "assets": {
        "Windows_x86_64": {
          "file": "<Feature>Updater_1.0.0_Windows_x86_64.zip",
          "download_url": "...",
          "sha256": "...",
          "size_bytes": 123,
          "executable": "<Feature>Updater.exe",
          "executable_sha256": "...",
          "executable_size_bytes": 123
        },
        "Linux_x86_64": {
          "file": "<Feature>Updater_1.0.0_Linux_x86_64.zip",
          "download_url": "...",
          "sha256": "...",
          "size_bytes": 123,
          "executable": "<Feature>Updater",
          "executable_sha256": "...",
          "executable_size_bytes": 123
        }
      }
    }
  }
}
```

The outer ZIP and contained updater runtime are independently verifiable.

---

### 26.26. Updater manifest routing

When a feature already knows which updater component it needs, it should normally begin from its own feature-specific resource manifest rather than crawling generic repository routers.

Preferred runtime path:

```text
Resources/FirstParty/<Feature>/<Feature>_Resources_Manifest.json
    ↓
<Feature>Updater component reference
    ↓
<Feature>Updater_Release_Manifest.json
```

Generic manifests such as:

```text
Resources/Resources_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
```

remain useful for repository navigation and discovery.

They are not required traversal steps for runtime code that already knows the exact feature/component it needs.

---

### 26.27. Package verification

Before executing a downloaded updater package:

```text
1. Download the updater ZIP.
2. Verify ZIP byte size.
3. Verify ZIP SHA-256.
4. Safely inspect/extract the expected updater runtime.
5. Verify updater runtime byte size.
6. Verify updater runtime SHA-256.
7. Verify the runtime filename matches the manifest and current platform.
8. Only then execute it.
```

The same principle applies when the updater downloads the new application release.

Never execute a downloaded payload merely because the download completed successfully.

---

### 26.28. Safe ZIP extraction

Updater and application release archives must be treated as untrusted input until validated.

Archive extraction should reject unsafe member paths including:

- absolute paths
- parent traversal such as `..`
- drive-letter paths where inappropriate
- embedded NUL characters
- unexpected nested paths when a single runtime is expected
- unexpected executable names

A release package intended to contain one stable runtime should not be allowed to write arbitrary files outside its staging directory.

---

### 26.29. Stage before replacing

The target application release should be downloaded, extracted, and verified **before the currently installed runtime is moved or replaced**.

Preferred sequence:

```text
download target release
    ↓
verify target ZIP
    ↓
extract target runtime into staging
    ↓
verify staged runtime
    ↓
wait for old application process to exit
    ↓
move old runtime to temporary backup
    ↓
move staged runtime into stable location
```

This prevents network failure, corrupt downloads, or invalid packages from taking a working installation offline before a valid replacement exists.

This ordering supersedes older updater designs that moved the installed runtime before downloading the replacement.

---

### 26.30. Parent-process handoff

The application should provide the updater with the process identity it needs to wait for.

Conceptually:

```text
Feature PID
    ↓
--parent-pid <PID>
    ↓
FeatureUpdater
```

The updater must not assume that launching successfully means the parent application has already terminated.

It should explicitly wait for the supplied parent process to finish before replacing the stable runtime.

---

### 26.31. Stable runtime and temporary backup names

ProjectHomelab applications normally use stable runtime names.

Examples:

```text
Windows:
<Feature>.exe

Linux:
<Feature>.AppImage
```

During replacement, the old runtime may be temporarily renamed.

Examples:

```text
Windows:
<Feature>Temp.exe

Linux:
<Feature>Temp.AppImage
```

The temporary file is a rollback copy.

It should not be deleted until the new runtime has been installed and the update has progressed far enough that rollback is no longer required.

---

### 26.32. Replacement sequence

Once a valid staged runtime exists and the old application process has exited:

```text
stable old runtime
    ↓
rename/move to temporary backup
    ↓
staged new runtime
    ↓
move to stable runtime name
```

Example:

```text
PythoFetch.AppImage
    ↓
PythoFetchTemp.AppImage

staged/PythoFetch.AppImage
    ↓
PythoFetch.AppImage
```

Where practical, staging should occur on the same filesystem as the target so final replacement operations remain simple and reliable.

---

### 26.33. Rollback

If replacement fails after the old runtime has been moved to its temporary backup name, the updater should attempt to restore the previous runtime.

Conceptually:

```text
installation failure
    ↓
remove incomplete/broken stable replacement if necessary
    ↓
restore temporary backup to stable name
    ↓
relaunch previous runtime where safe
```

Rollback should favor returning the user to the previously working version rather than leaving no runnable application.

The old runtime should not be permanently destroyed merely because a new release was downloaded.

---

### 26.34. Launching the new runtime

After successful replacement, the updater launches the new stable runtime.

The new runtime should receive:

```text
--updated
```

ProjectHomelab features may also pass internal post-update context such as:

```text
--updater-pid
--previous-version
```

when useful.

These arguments are internal update coordination interfaces and should be documented if another component depends on them.

---

### 26.35. `--updated` responsibilities

The new application version knows what state it requires.

Therefore application-specific compatibility work belongs primarily to the new runtime rather than to the updater.

Possible `--updated` responsibilities include:

- waiting for the updater process to exit
- migrating Appdata
- converting settings
- updating registry metadata
- updating resource compatibility
- validating persistent state
- removing obsolete files
- deleting the temporary old runtime
- deleting the extracted updater runtime
- clearing updater ZIPs or staging directories
- confirming the new installed version

The updater should remain generic wherever possible.

---

### 26.36. Linux AppImage environment cleanup

A Linux application launched from an AppImage may carry AppImage-specific environment variables into child processes.

The updater should not accidentally inherit an environment that makes it behave as though it is still running inside the parent's AppImage runtime.

The PythoFetch reference implementation cleans AppImage-related variables before launching its plain ELF updater.

Examples include:

```text
APPIMAGE
APPDIR
ARGV0
OWD
APPIMAGE_EXTRACT_AND_RUN
```

A feature-specific auto-terminal marker should also be removed from the updater environment when appropriate.

For PyInstaller child-process isolation, the reference design sets:

```text
PYINSTALLER_RESET_ENVIRONMENT=1
```

`LD_LIBRARY_PATH` should be restored from the original environment where available rather than blindly inheriting AppImage-modified library paths.

---

### 26.37. Linux terminal handoff

Linux AppImages may create a temporary terminal when launched graphically.

That terminal may close as soon as the application exits.

An updater must not remain dependent on stdin/stdout/stderr belonging to a terminal that is about to disappear.

The PythoFetch reference implementation distinguishes two cases.

#### Existing persistent terminal

If the user launched the feature from an already-open terminal:

```text
terminal
    ↓
Feature.AppImage
    ↓
FeatureUpdater
```

the updater may continue using that terminal.

#### Automatically created temporary terminal

If the feature created its own terminal because it was launched graphically:

```text
desktop
    ↓
temporary terminal
    ↓
Feature.AppImage
```

the updater should be handed off to a separate terminal/process context before the original feature exits.

The new updater process should not retain dead standard-stream file descriptors from the temporary terminal.

This avoids the failure mode where the updater launches successfully but dies as soon as the application's temporary terminal closes.

---

### 26.38. Linux terminal candidates

A feature that needs a separate updater terminal may probe common terminal applications.

The PythoFetch reference implementation supports candidates such as:

```text
gnome-terminal
kgx
x-terminal-emulator
konsole
xterm
```

This list is an implementation detail rather than a mandatory universal list.

The architectural rule is:

> If the updater needs an interactive terminal for visibility, that terminal must have a lifecycle independent from the temporary terminal the application is about to close.

---

### 26.39. Windows process handoff

Windows does not use the AppImage/FUSE environment model.

The application can normally launch:

```text
<Feature>Updater.exe
```

as a separate process, pass the parent PID and update arguments, then exit.

The updater waits for the parent feature process to terminate before attempting runtime replacement.

Platform-specific process creation flags may be used where required, but the updater's logical lifecycle remains the same as Linux.

---

### 26.40. Updater progress and errors

An updater should make meaningful stages visible or loggable.

Useful stage labels include:

```text
DOWNLOAD
VERIFY
STAGE
WAIT
BACKUP
INSTALL
START
ROLLBACK
CLEANUP
```

Errors should identify the stage that failed.

An updater should not silently leave the application in an unknown state.

When possible, errors should include enough information to determine whether:

- the old runtime remains installed
- rollback succeeded
- the new runtime was staged but not installed
- a package failed verification
- relaunch failed

---

### 26.41. Failure boundaries

The updater should distinguish between failures that occur:

#### Before the old runtime is touched

Examples:

- manifest failure
- target release download failure
- ZIP checksum mismatch
- extraction failure
- staged runtime checksum mismatch

These failures should leave the current application installation unchanged.

#### After the old runtime is moved

Examples:

- final install move failure
- new runtime launch failure
- unexpected filesystem error

These failures require rollback handling.

This boundary is one of the most important updater safety rules.

---

### 26.42. Updater cleanup

Temporary update artifacts should eventually be removed.

Examples:

```text
downloaded updater ZIP
extracted updater runtime
downloaded application ZIP
staging directory
temporary old runtime
temporary download files
```

Cleanup must not happen so early that rollback becomes impossible.

The new application runtime may perform the final cleanup after the updater has exited.

---

### 26.43. Persistent data boundary

The updater replaces the runtime.

It should not casually delete persistent application state.

Persistent state may include:

```text
Appdata/
Settings/
Registry/
Downloaded resources/
User configuration/
Databases/
Caches that are intended to survive updates/
```

`.AppRoot`-aware features may store this data outside the feature runtime directory when integrated.

The updater should preserve that architecture.

---

### 26.44. Updater Build Tool validation

Before publishing an updater package, the Build Tool should validate as much as practical.

Minimum checks should include:

- correct target OS
- correct target architecture
- valid updater source location
- valid updater version
- source/folder version agreement or explicit normalization
- successful source `--version`
- successful PyInstaller build
- expected runtime filename
- non-empty runtime
- successful compiled `--version`
- correct executable permission on Linux
- valid ELF signature on Linux
- valid EXE output on Windows
- valid release ZIP structure

The Build Tool should fail rather than publishing an obviously invalid updater.

---

### 26.45. Updater release testing

A new updater pipeline should be tested in layers.

#### Layer 1 — source test

```text
python <Feature>Updater_<Version>.py --version
```

#### Layer 2 — packaged updater test

Windows:

```text
<Feature>Updater.exe --version
```

Linux:

```text
./<Feature>Updater --version
```

#### Layer 3 — controlled replacement test

Use a known test installation and a known target version.

Verify:

```text
download
verification
staging
parent wait
backup
replacement
relaunch
cleanup
```

#### Layer 4 — normal user launch path

Test the application exactly as an ordinary user launches it.

On Linux this includes testing a graphical/AppImage launch path, not only running the AppImage from an already-open terminal.

The normal user launch path can expose lifecycle problems that a persistent development shell hides.

---

### 26.46. Proving an update path

A ProjectHomelab updater should not be considered fully validated merely because:

```text
Updater --version
```

works.

The important proof is:

```text
old packaged application
    ↓
detects update
    ↓
downloads updater
    ↓
updater replaces old runtime
    ↓
new packaged application starts
    ↓
installed version is confirmed
```

PythoFetch established this proof for the first ProjectHomelab Windows/Linux updater architecture.

---

### 26.47. Reference PythoFetch implementation

PythoFetch is the initial reference design for this rulebook.

Reference source components:

```text
SourceCode/PythoFetch/PythoFetch/
SourceCode/PythoFetch/PythoFetchUpdater/
SourceCode/PythoFetch/PythoFetchBuildTools/
```

Reference updater Build Tools:

```text
Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
```

Reference updater resources:

```text
Resources/FirstParty/PythoFetch/PythoFetchUpdater/
```

Reference shared icons:

```text
Resources/Icons/Shared/Updater/Icon_Updater.ico
Resources/Icons/Shared/Updater/Icon_Updater.png
```

PythoFetch should be treated as a proven architectural starting point, not as code that must be copied blindly.

Feature names, arguments, target runtime names, and application-specific post-update work still need to be adapted correctly.

---

### 26.48. Reusing the updater design for another feature

When creating a new ProjectHomelab updater, the PythoFetch design can be used as a base.

The expected adaptation points are primarily:

```text
Feature name
Updater component name
Version constant name
Application runtime filename
Temporary backup filename
Release manifest URL/path
Resource manifest URL/path
User-Agent names
Build Tool labels
Feature-specific post-update arguments
```

The safety model should remain substantially the same:

```text
verify updater
stage new runtime
wait for old process
backup old runtime
install new runtime
launch new runtime
rollback on failure
clean up after success
```

Avoid rewriting the updater architecture differently for every feature unless that feature genuinely requires different behaviour.

---

### 26.49. What belongs in the updater versus the application

The updater should know how to replace the runtime.

The application should know how to become the new version.

Prefer:

```text
Updater:
download
verify
stage
wait
backup
replace
rollback
launch

New application:
migrate
repair
update resources
validate persistent data
cleanup
continue startup
```

Avoid turning the updater into a second copy of the feature's application logic.

---

### 26.50. New updater checklist

Before publishing a new ProjectHomelab updater, verify:

1. Is the updater an independent versioned source component?
2. Does its `X.Y` compatibility family match the parent feature?
3. Does the source folder follow `<Feature>Updater_<Version>`?
4. Does the source file follow `<Feature>Updater_<Version>.py`?
5. Does the Build Tool follow `Build_<Feature>Updater_<OS>_<Architecture>_<BuildToolVersion>.py`?
6. Does the Windows package contain stable `<Feature>Updater.exe`?
7. Does the Linux package contain stable `<Feature>Updater`?
8. Is the Linux updater a plain ELF unless a documented exception exists?
9. Does the Windows updater use the shared updater ICO?
10. Does `--version` work from source?
11. Does `--version` work from the built updater?
12. Is the release ZIP checksummed?
13. Is the updater runtime independently checksummed?
14. Does the release manifest declare `compatibility_family`?
15. Does the feature resolve the newest compatible updater?
16. Are ZIP extraction paths validated?
17. Is the updater runtime verified before execution?
18. Is the target application release fully downloaded before touching the installed runtime?
19. Is the target runtime fully staged and verified before replacement?
20. Does the updater wait for the old application process?
21. Is the old runtime preserved as a temporary rollback copy?
22. Can replacement failure restore the old runtime?
23. Does the new runtime launch with `--updated`?
24. Does application-specific migration remain in the new runtime?
25. Are AppImage environment variables cleaned before Linux updater launch where required?
26. Does graphical Linux launch correctly hand the updater to an independent process/terminal context?
27. Are temporary files cleaned only after rollback is no longer needed?
28. Is persistent Appdata left intact?
29. Has the complete update been tested from the normal packaged user launch path?
30. Has the installed target version been confirmed after replacement?

If those checks pass, the updater is generally following the current ProjectHomelab updater contract.

---

### 26.51. Current validated baseline

The current ProjectHomelab updater baseline is:

```text
Windows x86_64
    Feature.exe
    FeatureUpdater.exe
    PyInstaller one-file updater

Linux x86_64
    Feature.AppImage
    FeatureUpdater
    PyInstaller one-file ELF updater
```

The current shared updater icon baseline is:

```text
Resources/Icons/Shared/Updater/Icon_Updater.ico
Resources/Icons/Shared/Updater/Icon_Updater.png
```

The current safety baseline is:

```text
download
    ↓
verify package
    ↓
stage runtime
    ↓
verify staged runtime
    ↓
wait for old process
    ↓
backup old runtime
    ↓
install new runtime
    ↓
launch --updated
    ↓
rollback if required
    ↓
cleanup after success
```

These rules should continue to be refined as additional ProjectHomelab applications are released and new platform behaviour is proven.

---

## 27. Released packages/resources use checksums

Released application packages, assets, updater packages, and other distributable resources use SHA-256 checksums.

Their manifests record version, platform, architecture, URL/path, SHA-256, and size where useful.

Downloads should be verified before installation.

---

## 28. TerminalSS release manifest hierarchy example

TerminalSS runtime releases:

```text
ProjectHomelab/
└── Releases/
    └── TerminalSS/
        └── TerminalSS_Release_Manifest.json
```

TerminalSS first-party resources:

```text
Resources/
└── FirstParty/
    └── TerminalSS/
        ├── TerminalSS_Resources_Manifest.json
        ├── TerminalSSUpdater/
        │   └── TerminalSSUpdater_Release_Manifest.json
        └── TerminalSSAssets/
            ├── TerminalSSAssets_Release_Manifest.json
            ├── TerminalSSAlienMode/
            │   └── TerminalSSAlienMode_Release_Manifest.json
            ├── TerminalSSMysticMode/
            │   └── TerminalSSMysticMode_Release_Manifest.json
            └── ...
```

Each layer only needs to know about the layer immediately beneath it.

---

## 29. Development resources vs release resources

Development/source builds may obtain assets from `SourceCode/` because those resources are intended for development and inspection.

For example, TerminalSS source can:

1. use local source assets if present
2. fall back to raw GitHub source assets if the local source asset tree is absent

Packaged release builds should instead use the proper:

```text
Resources/FirstParty/<Feature>/
```

release channel.

An EXE/AppImage should not depend on the development `SourceCode` branch for production resources.

---

## 30. Versioned assets

Asset packs may have their own independent Minor Version.

Example:

```text
TerminalSS_1.0.0
Alien_1.0.34
```

This is valid because both are part of the `1.0.x` compatibility family.

The runtime may remain unchanged while an asset collection is repeatedly improved, curated, expanded, reduced, or corrected.

A Major Version change to the parent feature requires matching Major-Version asset releases.

---

## 31. Independent first-party apps should remain independent

If one ProjectHomelab feature wants to use another finished ProjectHomelab application, avoid unnecessarily duplicating its code/resources.

Example: TerminalSS may use PythoFetch in headless mode.

Rather than copying PythoFetch into TerminalSS's asset system, TerminalSS can resolve/download the appropriate PythoFetch release and invoke it through its supported interface.

This preserves independent versioning, independent updating, one source of truth, and reusable architecture.

---

## 32. OS-aware, not OS-forked

Cross-platform apps should prefer:

```text
Shared Core
+ OS-specific provider/modules
```

rather than separate Windows and Linux applications.

Build tools package only the platform modules required for that target build.

Do not ship irrelevant platform dependencies just because they exist in source.

---

## 33. Minimum-version dependencies

When one ProjectHomelab feature depends on another, prefer stating a **minimum compatible version** rather than hardcoding one exact release forever.

Conceptually:

```text
PythoFetch >= 1.6.4
```

If later versions remain compatible, they should continue to work.

Only increase the minimum version when an actual compatibility requirement appears.

Generation and feature-specific Major-Version compatibility rules still apply.

---

## 34. ProjectHomelab local port allocation

ProjectHomelab local HTTP, WebSocket, API, and other persistent local service listeners use the canonical port range:

```text
42000-42999
```

The range is divided by ProjectHomelab component type:

| Range | Purpose |
| --- | --- |
| `42000-42099` | ProjectHomelab application/core services |
| `42100-42199` | LocalServices |
| `42200-42299` | MediaHub and MediaHub-specific services/features |
| `42300-42399` | Independent ProjectHomelab features/apps |
| `42400-42899` | Reserved for future categories or expansion |
| `42900-42999` | Development, testing, migration, and temporary port overrides |

Classification is based on architectural ownership rather than what a feature technically does.

Examples:

```text
ProjectHomelab internal application service -> 420xx
LocalStorageAccess                        -> 421xx
MediaHub LiveRadio                       -> 422xx
StatMonitor                              -> 423xx
TorrentSnipe                             -> 423xx
BootForge                                -> 423xx
```

A standalone feature does not move between categories merely because its responsibilities overlap with another category. For example, BootForge remains an independent feature rather than becoming a LocalService or storage-category service.

### Ten-port allocation blocks

An independently running backend/service that requires a persistent listener is normally assigned a permanent ten-port block inside its category.

Example:

```text
42300-42309  StatMonitor
42310-42319  TorrentSnipe
42320-42329  YouSnipe
```

The first port in the block is the component's canonical primary port.

Conceptually:

```text
StatMonitor block:     42300-42309
StatMonitor primary:   42300
```

The remaining ports are reserved for that component and should remain unused unless there is a genuine technical reason for an additional independent listener.

Internal modules do not receive separate ports merely because they expose different functions. CPU, GPU, Wi-Fi, Bluetooth, fan control, telemetry, and similar StatMonitor capabilities normally share the same StatMonitor server and are distinguished by routes, actions, message types, or protocol fields.

### Allocation stability

Adding, removing, renaming, or archiving a feature must not cause unrelated components to be renumbered.

Port allocation is historical rather than compact. Gaps are expected and acceptable.

Once assigned, a component's block should remain associated with that component. If the component is retired, its block becomes retired/reserved rather than being silently reassigned to an unrelated feature.

This prevents old frontends, scripts, integrations, or cached configuration from accidentally connecting to a different service that inherited the same port.

### One feature, one normal listener

A feature normally exposes one primary local listener even when it contains many modules or capabilities.

Prefer:

```text
StatMonitor -> 42300
    CPU actions
    GPU actions
    fan actions
    Wi-Fi actions
    Bluetooth actions
```

over:

```text
42300 CPU
42301 GPU
42302 fans
42303 Wi-Fi
42304 Bluetooth
```

Additional ports from the component's reserved block are used only where a second listener is technically necessary.

### Cross-platform consistency

A component uses the same canonical port on every supported operating system.

Example:

```text
StatMonitor Windows -> 42300
StatMonitor Linux   -> 42300
StatMonitor macOS   -> 42300
```

The purpose of the integration contract is that callers do not need OS-specific port knowledge.

### Standalone defaults and overrides

Each standalone component must know its own canonical default port and must not require ProjectHomelab itself to be installed merely to discover that number.

A component may provide an explicit port override such as:

```text
--port 55000
```

for development, unusual installations, testing, or collision recovery.

A service should not silently increment to another permanent port when its canonical port is occupied. It should fail clearly and allow the caller/user to provide an explicit override. Silent port hopping makes integrations unpredictable.

Ports in `42900-42999` are intended for temporary development/testing use and are not assigned as permanent production defaults.

### Port registry

ProjectHomelab should maintain a central source-controlled port registry, conceptually:

```text
ProjectHomelab_PortRegistry.json
```

The registry records active, reserved, and retired allocations. It is the development authority for avoiding collisions and documenting ownership.

The registry is not a mandatory runtime dependency. Independently usable features retain their own canonical default port in their source/runtime configuration so they continue to work standalone.

The registry should distinguish between a component's allocated block and the ports it currently listens on.

Conceptually:

```json
{
  "StatMonitor": {
    "range": "42300-42309",
    "primaryPort": 42300,
    "status": "active"
  }
}
```

Port changes are integration-compatibility changes and should be avoided once a component has been published with a canonical allocation.

---

## 35. General design philosophy

ProjectHomelab features should aim to be:

- portable
- self-contained
- transparent
- inspectable
- independently usable
- integration-friendly
- version-predictable
- repairable
- updatable
- cross-platform where practical

Prefer:

```text
one codebase
one portable application
shared interfaces
small OS-specific providers
clear manifests
clear compatibility rules
```

over duplicated standalone/HomeLab implementations, hard-coded machine paths, opaque dependencies, or unversioned resources.

---

## 36. Core contribution checklist

When adding or changing a ProjectHomelab feature, ask:

1. Does this work standalone?
2. Does it correctly honor `.AppRoot`, searching every ancestor to the filesystem root and selecting the nearest marker?
3. If it creates persistent runtime folders, does a loose packaged runtime self-contain inside its canonical feature folder before writing data?
4. Does source execution avoid relocating or rearranging the source repository?
5. Does it avoid writing outside its resolved root?
6. Is the component versioned according to its type?
7. Does its Major Version match its tightly coupled assets/updater/resources?
8. Are release artifacts checksummed?
9. Is source inspectable?
10. Are platform-specific pieces isolated?
11. Can persistent Appdata survive an application update?
12. Can another developer understand where the source, release, resources, and build tools belong?
13. Does the feature integrate through a stable interface rather than relying on fragile filenames/paths?
14. Does runtime code use direct feature/component manifest entry points instead of unnecessarily crawling generic repository routers?
15. Is first-party source free of unnecessary comments/docstrings, with architectural explanation kept in documentation instead?
16. Are obsolete generations clearly archived rather than silently treated as supported?
17. If the component exposes a persistent local listener, does it use the correct ProjectHomelab port category, preserve its canonical allocation, and record that allocation in the central port registry?

If those rules are satisfied, the feature is generally following ProjectHomelab conventions.
