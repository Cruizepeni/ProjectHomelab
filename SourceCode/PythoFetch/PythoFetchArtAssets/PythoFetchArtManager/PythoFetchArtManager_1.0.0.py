import argparse
import hashlib
import json
import os
import re
import sqlite3
import shutil
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


MANAGER_VERSION = "1.0.0"
SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1

SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_ROOT = SCRIPT_DIR.parent

NEOFETCH_DIR = ASSETS_ROOT / "ArtAssetsNeofetch"
PYTHOFETCH_DIR = ASSETS_ROOT / "ArtAssetsPythoFetch"
DATABASE_DIR = ASSETS_ROOT / "ArtAssetsDB"

NEOFETCH_CATALOGUE = NEOFETCH_DIR / "Catalogue.json"
PYTHOFETCH_CATALOGUE = PYTHOFETCH_DIR / "Catalogue.json"


SOURCE_DIR = SCRIPT_DIR / "Neofetch"
SOURCE_FILE = SOURCE_DIR / "neofetch"
OUTPUT_DIR = NEOFETCH_DIR

SOURCE_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Resources/ThirdParty/Neofetch/neofetch"
)

LICENSE_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Resources/ThirdParty/Neofetch/LICENSE.md"
)

DATABASE_DOWNLOAD_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "SourceCode/PythoFetch/"
    "PythoFetchArtAssets/ArtAssetsDB"
)

CATALOGUE_FILE = NEOFETCH_CATALOGUE
LICENSE_FILE = NEOFETCH_DIR / "NeoFetch_LICENSE.md"
README_FILE = NEOFETCH_DIR / "README.txt"

_DOWNLOADED_SOURCE = False
_SOURCE_DIR_PREEXISTED = False
STAGING_DB = DATABASE_DIR / "PythoFetchArtNew.db"
MANIFEST_FILE = DATABASE_DIR / "PythoFetchArtDB_Manifest.json"
OLD_MANIFEST_FILE = DATABASE_DIR / "PythoFetchArt_Manifest.json"
MANIFEST_TEMP = DATABASE_DIR / "PythoFetchArtDB_Manifest.json.building"

FAMILIES = (
    "Windows",
    "Linux",
    "macOS",
    "Other",
)

FAMILY_FOLDERS = {
    "Windows": "Windows",
    "Linux": "Linux",
    "macOS": "MacOS",
    "Other": "Other",
}

VERSION_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+$"
)

DATABASE_PATTERN = re.compile(
    r"^PythoFetchArt_(\d+\.\d+\.\d+)\.db$",
    re.IGNORECASE,
)

ARTWORK_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9._+\-]+$"
)

COLOR_TOKEN_PATTERN = re.compile(
    r"\$\{c([1-8])\}"
)


class ManagerCancelled(Exception):
    pass


WINDOWS_NAMES = {
    "windows",
    "windows 10",
    "windows 11",
}

MACOS_NAMES = {
    "mac",
    "darwin",
}

OTHER_NAMES = {
    "aix",
    "bitrig",
    "bsd",
    "dragonfly",
    "dragonfly_old",
    "dragonfly_small",
    "freebsd",
    "freebsd_small",
    "freemint",
    "gnu",
    "haiku",
    "haiku_small",
    "irix",
    "minix",
    "netbsd",
    "netbsd_small",
    "openbsd",
    "openbsd_small",
    "openindiana",
    "pacbsd",
    "pcbsd",
    "smartos",
    "sunos",
    "sunos_small",
}

CANONICAL_BASE_OVERRIDES = {
    "CBL-Mariner": "CBL_Mariner",
    "Ubuntu-GNOME": "Ubuntu_GNOME",
    "mac": "macOS",
}

def download_file(url, destination):
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"PythoFetchArtManager/{MANAGER_VERSION}",
        },
    )

    temporary = destination.with_name(
        destination.name + ".download"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            with temporary.open("wb") as handle:
                shutil.copyfileobj(
                    response,
                    handle,
                )

        if (
            not temporary.is_file()
            or temporary.stat().st_size == 0
        ):
            raise RuntimeError(
                f"Downloaded file was empty: {url}"
            )

        temporary.replace(destination)

    finally:
        if temporary.exists():
            temporary.unlink()


def ensure_source():
    global _DOWNLOADED_SOURCE
    global _SOURCE_DIR_PREEXISTED

    if SOURCE_FILE.is_file():
        return "Local"

    _SOURCE_DIR_PREEXISTED = SOURCE_DIR.exists()

    print(
        "NeoFetch source was not found locally."
    )
    print(
        "Downloading ProjectHomelab mirror..."
    )
    print()

    download_file(
        SOURCE_URL,
        SOURCE_FILE,
    )

    _DOWNLOADED_SOURCE = True

    return "Downloaded"


def cleanup_downloaded_source():
    if not _DOWNLOADED_SOURCE:
        return

    if SOURCE_FILE.exists():
        SOURCE_FILE.unlink()

    if (
        not _SOURCE_DIR_PREEXISTED
        and SOURCE_DIR.exists()
    ):
        shutil.rmtree(
            SOURCE_DIR
        )
        return

    if SOURCE_DIR.exists():
        try:
            next(
                SOURCE_DIR.iterdir()
            )
        except StopIteration:
            SOURCE_DIR.rmdir()


def visible_indent(line):
    expanded = line.expandtabs(8)
    return len(expanded) - len(
        expanded.lstrip()
    )


def is_case_matcher(line):
    stripped = line.strip()

    if not stripped:
        return False

    if stripped.startswith("#"):
        return False

    if stripped.startswith("case "):
        return False

    return stripped.endswith(")")


def sanitize_filename(value):
    value = value.replace('"', "")
    value = value.replace("'", "")
    value = value.replace("*", "")
    value = value.replace("/", "_")
    value = value.replace("\\", "_")
    value = value.replace("|", "_OR_")

    value = re.sub(
        r"\$\{[^}]+\}",
        "",
        value,
    )

    value = re.sub(
        r"[^A-Za-z0-9._+ -]+",
        "",
        value,
    )

    value = re.sub(
        r"\s+",
        "_",
        value.strip(),
    )

    value = re.sub(
        r"_+",
        "_",
        value,
    )

    return value.strip("._") or "Unknown"


def extract_aliases(matcher):
    aliases = []

    quoted_matches = re.findall(
        r'"([^"]+)"|\'([^\']+)\'',
        matcher,
    )

    for pair in quoted_matches:
        item = pair[0] or pair[1]
        item = item.replace(
            "*",
            "",
        ).strip()

        if (
            item
            and item not in aliases
        ):
            aliases.append(item)

    raw = matcher.rstrip(")").strip()

    for part in raw.split("|"):
        part = part.strip()
        part = part.replace(
            "*",
            "",
        )
        part = part.strip('"')
        part = part.strip("'")
        part = part.strip()

        if re.fullmatch(
            r"[A-Za-z0-9_.!+ -]+",
            part or "",
        ):
            if (
                part
                and part not in aliases
            ):
                aliases.append(part)

    return aliases


def display_name(matcher, index):
    aliases = extract_aliases(matcher)

    if aliases:
        return aliases[0]

    cleaned = matcher.rstrip(")")
    cleaned = cleaned.replace(
        "*",
        "",
    )
    cleaned = cleaned.replace(
        '"',
        "",
    )
    cleaned = cleaned.replace(
        "'",
        "",
    )
    cleaned = cleaned.strip()

    return (
        cleaned
        or f"Artwork_{index:03d}"
    )


def variant_from_entry(
    name,
    matcher,
    aliases,
):
    values = [
        name,
        matcher,
        *aliases,
    ]

    combined = " ".join(
        str(value)
        for value in values
        if value
    ).lower()

    if "small" in combined:
        return "small"

    if "old" in combined:
        return "old"

    return "default"


def parse_colors(raw):
    if not raw:
        return []

    return raw.split()


def find_catalogue_function(text):
    marker = "get_distro_ascii() {"
    start = text.find(marker)

    if start < 0:
        raise RuntimeError(
            "Could not find get_distro_ascii() "
            "in the NeoFetch source."
        )

    end = text.find(
        "\nmain() {",
        start,
    )

    if end < 0:
        raise RuntimeError(
            "Could not determine the end of "
            "get_distro_ascii()."
        )

    return text[start:end]


def find_nearest_matcher(
    lines,
    before_index,
):
    for index in range(
        before_index - 1,
        -1,
        -1,
    ):
        if is_case_matcher(
            lines[index]
        ):
            return (
                lines[index].strip(),
                index,
                visible_indent(
                    lines[index]
                ),
            )

    return "Unknown)", -1, 0


def find_parent_matcher(
    lines,
    before_index,
    child_indent,
):
    if child_indent <= 8:
        return None, None

    for index in range(
        before_index - 1,
        -1,
        -1,
    ):
        if not is_case_matcher(
            lines[index]
        ):
            continue

        current_indent = visible_indent(
            lines[index]
        )

        if current_indent < child_indent:
            return (
                lines[index].strip(),
                index,
            )

    return None, None


def find_color_rule(
    lines,
    matcher_index,
    art_index,
    parent_matcher_index=None,
):
    rules = []
    start = max(
        matcher_index,
        0,
    )

    for index in range(
        start,
        art_index,
    ):
        stripped = lines[index].strip()

        match = re.search(
            r"\bset_colors\s+(.+?)"
            r"(?:\s*;;)?$",
            stripped,
        )

        if match:
            rules.append(
                match.group(1).strip()
            )

    if (
        not rules
        and parent_matcher_index
        is not None
    ):
        for index in range(
            max(
                parent_matcher_index,
                0,
            ),
            art_index,
        ):
            stripped = (
                lines[index].strip()
            )

            match = re.search(
                r"\bset_colors\s+(.+?)"
                r"(?:\s*;;)?$",
                stripped,
            )

            if match:
                rules.append(
                    match.group(1).strip()
                )

    return (
        rules[-1]
        if rules
        else None
    )


def classify_family(name):
    lowered = name.lower()

    if lowered in WINDOWS_NAMES:
        return "Windows"

    if lowered in MACOS_NAMES:
        return "macOS"

    if lowered in OTHER_NAMES:
        return "Other"

    return "Linux"


def canonical_base(name):
    if name in CANONICAL_BASE_OVERRIDES:
        return CANONICAL_BASE_OVERRIDES[
            name
        ]

    return sanitize_filename(name)


def strip_variant_suffix(
    value,
    variant,
):
    if variant == "small":
        return re.sub(
            r"(?i)(?:[_ -]?small)$",
            "",
            value,
        ).rstrip("_ -")

    if variant == "old":
        return re.sub(
            r"(?i)(?:[_ -]?old)$",
            "",
            value,
        ).rstrip("_ -")

    return value


def make_canonical_id(
    name,
    variant,
    used_ids,
):
    base = canonical_base(name)
    base = strip_variant_suffix(
        base,
        variant,
    )

    if (
        name == "mac"
        and variant == "default"
    ):
        candidate = "macOS_Alt"

    elif variant == "small":
        candidate = (
            f"{base}_Small"
        )

    elif variant == "old":
        candidate = (
            f"{base}_Old"
        )

    else:
        candidate = base

    original = candidate
    alternate = 1

    while (
        candidate.lower()
        in used_ids
    ):
        suffix = (
            "_Alt"
            if alternate == 1
            else f"_Alt{alternate}"
        )

        candidate = (
            original
            + suffix
        )

        alternate += 1

    used_ids.add(
        candidate.lower()
    )

    return candidate


def prepare_output():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for family in FAMILIES:
        family_dir = (
            OUTPUT_DIR
            / FAMILY_FOLDERS[family]
        )

        if family_dir.exists():
            shutil.rmtree(
                family_dir
            )

    for generated_file in (
        CATALOGUE_FILE,
        LICENSE_FILE,
        README_FILE,
    ):
        if generated_file.exists():
            generated_file.unlink()

    for family in FAMILIES:
        (
            OUTPUT_DIR
            / FAMILY_FOLDERS[family]
        ).mkdir(
            parents=True,
            exist_ok=True,
        )


def copy_license():
    for license_name in (
        "LICENSE.md",
        "LICENSE",
    ):
        candidate = (
            SOURCE_DIR / license_name
        )

        if candidate.is_file():
            shutil.copy2(
                candidate,
                LICENSE_FILE,
            )

            return "Local"

    try:
        download_file(
            LICENSE_URL,
            LICENSE_FILE,
        )

        return "Downloaded"

    except Exception:
        return None


def write_readme(
    family_counts,
    entry_count,
    license_state,
):
    readme = [
        "PYTHOFETCH ART ASSETS - NEOFETCH",
        "================================",
        "",
        (
            "This folder contains the "
            "extracted and curated NeoFetch "
            "artwork source used by PythoFetch."
        ),
        (
            "No NeoFetch artwork entries "
            "are removed during extraction."
        ),
        "",
        "Families:",
        (
            "  Windows : "
            f"{family_counts['Windows']}"
        ),
        (
            "  Linux   : "
            f"{family_counts['Linux']}"
        ),
        (
            "  macOS   : "
            f"{family_counts['macOS']}"
        ),
        (
            "  Other   : "
            f"{family_counts['Other']}"
        ),
        (
            "  Total   : "
            f"{entry_count}"
        ),
        "",
        "Structure:",
        (
            "  Windows/  - Windows "
            "logos and variants"
        ),
        (
            "  Linux/    - Linux "
            "distributions and Linux-family "
            "artwork"
        ),
        (
            "  MacOS/    - macOS / "
            "Darwin artwork"
        ),
        (
            "  Other/    - non-target "
            "families retained so nothing "
            "is lost"
        ),
        "",
        "Notes:",
        (
            "- TXT files remain the "
            "editable source artwork."
        ),
        (
            "- ${c1}..${c6} markers are "
            "intentional and must remain "
            "in the artwork."
        ),
        (
            "- Duplicate and generic "
            "fallback artworks are retained."
        ),
        (
            "- Where canonical filenames "
            "collide, _Alt suffixes are "
            "added."
        ),
        (
            "- Catalogue.json contains "
            "curated paths and original "
            "NeoFetch extraction metadata."
        ),
        "",
        "NeoFetch source:",
        str(SOURCE_FILE),
        "",
        "ProjectHomelab mirror:",
        SOURCE_URL,
        "",
    ]

    if not license_state:
        readme.extend(
            [
                "WARNING:",
                (
                    "NeoFetch license could "
                    "not be located or "
                    "downloaded."
                ),
                (
                    "The upstream MIT "
                    "license must accompany "
                    "the derived artwork."
                ),
                "",
            ]
        )

    README_FILE.write_text(
        "\n".join(readme),
        encoding="utf-8",
    )


def extract_art():
    source_state = ensure_source()
    prepare_output()

    text = SOURCE_FILE.read_text(
        encoding="utf-8",
        errors="replace",
    )

    function_text = (
        find_catalogue_function(text)
    )

    lines = (
        function_text.splitlines()
    )

    entries = []
    used_ids = set()

    family_counts = {
        family: 0
        for family in FAMILIES
    }

    index = 0
    line_index = 0

    while line_index < len(lines):
        line = lines[line_index]

        if (
            "read -rd '' ascii_data "
            "<<'EOF'"
            not in line
        ):
            line_index += 1
            continue

        index += 1

        (
            matcher,
            matcher_index,
            matcher_indent,
        ) = find_nearest_matcher(
            lines,
            line_index,
        )

        (
            parent_matcher,
            parent_index,
        ) = find_parent_matcher(
            lines,
            matcher_index,
            matcher_indent,
        )

        art_lines = []
        end_index = line_index + 1

        while end_index < len(lines):
            if (
                lines[end_index].strip()
                == "EOF"
            ):
                break

            art_lines.append(
                lines[end_index]
            )

            end_index += 1

        if end_index >= len(lines):
            raise RuntimeError(
                "Unterminated ASCII-art "
                "heredoc near catalogue "
                f"entry {index}."
            )

        color_rule = find_color_rule(
            lines,
            matcher_index,
            line_index,
            parent_index,
        )

        name = display_name(
            matcher,
            index,
        )

        aliases = extract_aliases(
            matcher
        )

        variant = variant_from_entry(
            name,
            matcher,
            aliases,
        )

        family = classify_family(
            name
        )

        artwork_id = make_canonical_id(
            name,
            variant,
            used_ids,
        )

        filename = (
            artwork_id + ".txt"
        )

        folder_name = (
            FAMILY_FOLDERS[family]
        )

        relative_file = (
            f"{folder_name}/{filename}"
        )

        art_path = (
            OUTPUT_DIR
            / folder_name
            / filename
        )

        art_path.write_text(
            "\n".join(art_lines)
            + "\n",
            encoding="utf-8",
        )

        original_base = (
            sanitize_filename(name)
        )

        original_id = (
            f"{index:03d}_"
            f"{original_base}"
        )

        original_file = (
            "Logos/"
            f"{original_id}.txt"
        )

        entry = {
            "id": artwork_id,
            "name": name,
            "family": family,
            "variant": variant,
            "file": relative_file,
            "aliases": aliases,
            "colors": parse_colors(
                color_rule
            ),
            "color_rule": color_rule,
            "matcher": matcher,
            "parent_matcher": (
                parent_matcher
            ),
            "source": "NeoFetch",
            "original_index": index,
            "original_id": original_id,
            "original_file": (
                original_file
            ),
        }

        entries.append(entry)

        family_counts[family] += 1

        line_index = end_index + 1

    catalogue = {
        "format": (
            "PythoFetchArtCatalogue"
        ),
        "format_version": 2,
        "source_project": "NeoFetch",
        "source_repository": (
            "dylanaraps/neofetch"
        ),
        "source_mirror": (
            "Cruizepeni/ProjectHomelab/"
            "Resources/ThirdParty/Neofetch"
        ),
        "source_function": (
            "get_distro_ascii"
        ),
        "curated": True,
        "entry_count": len(entries),
        "family_counts": (
            family_counts
        ),
        "notes": [
            (
                "Direct curated extraction "
                "of NeoFetch artwork for "
                "PythoFetch."
            ),
            (
                "No artwork entries are "
                "removed during extraction."
            ),
            (
                "TXT files are editable "
                "source assets."
            ),
            (
                "${c1}..${c6} markers are "
                "preserved for runtime ANSI "
                "color substitution."
            ),
            (
                "Duplicate canonical names "
                "are retained using _Alt "
                "suffixed filenames."
            ),
        ],
        "entries": entries,
    }

    CATALOGUE_FILE.write_text(
        json.dumps(
            catalogue,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    license_state = copy_license()

    write_readme(
        family_counts,
        len(entries),
        license_state,
    )

    return (
        len(entries),
        family_counts,
        source_state,
        license_state,
    )

def version_key(value):
    return tuple(
        int(part)
        for part in value.split(".")
    )


def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def normalize_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def database_download_url(filename):
    return (
        DATABASE_DOWNLOAD_BASE_URL
        + "/"
        + str(filename)
    )


def display_path(path):
    path = Path(path)

    try:
        return path.resolve().relative_to(
            ASSETS_ROOT.resolve()
        ).as_posix()
    except Exception:
        return path.name




def run_neofetch_extractor():
    print()
    print(
        "PYTHOFETCH NEOFETCH ART EXTRACTOR"
    )
    print("=" * 72)
    print(
        "Source : NeoFetch"
    )
    print(
        "Output : ArtAssetsNeofetch"
    )
    print("=" * 72)
    print()

    try:
        (
            count,
            family_counts,
            source_state,
            license_state,
        ) = extract_art()

        print(
            f"Extracted : {count} artworks"
        )
        print(
            "Windows   : "
            f"{family_counts['Windows']}"
        )
        print(
            "Linux     : "
            f"{family_counts['Linux']}"
        )
        print(
            "macOS     : "
            f"{family_counts['macOS']}"
        )
        print(
            "Other     : "
            f"{family_counts['Other']}"
        )
        print(
            f"Source    : {source_state}"
        )
        print(
            "License   : "
            + (
                license_state
                if license_state
                else "NOT FOUND"
            )
        )
        print()
        print(
            "Extraction and curation complete."
        )

    finally:
        cleanup_downloaded_source()


def load_or_rebuild_neofetch_source():
    reason = None

    if not NEOFETCH_DIR.is_dir():
        reason = (
            "ArtAssetsNeofetch folder "
            "was not found."
        )

    elif not NEOFETCH_CATALOGUE.is_file():
        reason = (
            "ArtAssetsNeofetch is missing "
            "Catalogue.json."
        )

    else:
        try:
            (
                catalogue,
                raw_entries,
            ) = load_catalogue(
                NEOFETCH_CATALOGUE,
                "NeoFetch",
            )

            entries = validate_source(
                NEOFETCH_DIR,
                "NeoFetch",
                raw_entries,
            )

            return (
                catalogue,
                entries,
            )

        except Exception as exc:
            reason = str(exc)

    print(
        "NeoFetch art assets are missing "
        "or malformed."
    )
    print()
    print(
        f"Reason: {reason}"
    )
    print()

    try:
        response = input(
            "Rebuild ArtAssetsNeofetch "
            "now? [Y/n]: "
        ).strip().lower()
    except EOFError:
        response = ""

    if response not in (
        "",
        "y",
        "yes",
    ):
        print()
        print(
            "ArtAssetsNeofetch is required "
            "to build PythoFetch art "
            "databases."
        )
        print(
            "No changes were made. Closing."
        )

        raise ManagerCancelled()

    run_neofetch_extractor()

    if (
        not NEOFETCH_DIR.is_dir()
        or not NEOFETCH_CATALOGUE.is_file()
    ):
        raise RuntimeError(
            "NeoFetch art extraction "
            "completed but the curated "
            "assets were not created."
        )

    (
        catalogue,
        raw_entries,
    ) = load_catalogue(
        NEOFETCH_CATALOGUE,
        "NeoFetch",
    )

    entries = validate_source(
        NEOFETCH_DIR,
        "NeoFetch",
        raw_entries,
    )

    return (
        catalogue,
        entries,
    )


def rename_case_sensitive_folder(
    parent,
    old_name,
    new_name,
):
    old_path = parent / old_name
    new_path = parent / new_name

    if not old_path.exists():
        return False

    if (
        new_path.exists()
        and old_path.resolve()
        != new_path.resolve()
    ):
        raise RuntimeError(
            f"Both {old_name} and "
            f"{new_name} folders exist in "
            f"{display_path(parent)}."
        )

    temporary = (
        parent
        / (
            new_name
            + ".__pythofetch_rename__"
        )
    )

    if temporary.exists():
        if temporary.is_dir():
            shutil.rmtree(
                temporary
            )
        else:
            temporary.unlink()

    old_path.rename(
        temporary
    )

    temporary.rename(
        new_path
    )

    return True


def migrate_catalogue_folder_case(
    catalogue_file,
):
    if not catalogue_file.is_file():
        return False

    try:
        data = json.loads(
            catalogue_file.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return False

    entries = data.get("entries")

    if not isinstance(entries, list):
        return False

    changed = False

    for entry in entries:
        relative_file = entry.get(
            "file"
        )

        if (
            isinstance(
                relative_file,
                str,
            )
            and relative_file.startswith(
                "macOS/"
            )
        ):
            entry["file"] = (
                "MacOS/"
                + relative_file[
                    len("macOS/")
                :]
            )

            changed = True

    if changed:
        catalogue_file.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    return changed


def migrate_asset_folder_names():
    for source_dir, catalogue_file in (
        (
            NEOFETCH_DIR,
            NEOFETCH_CATALOGUE,
        ),
        (
            PYTHOFETCH_DIR,
            PYTHOFETCH_CATALOGUE,
        ),
    ):
        if not source_dir.is_dir():
            continue

        rename_case_sensitive_folder(
            source_dir,
            "macOS",
            "MacOS",
        )

        migrate_catalogue_folder_case(
            catalogue_file
        )


def ensure_pythofetch_source():
    PYTHOFETCH_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for family in FAMILIES:
        (
            PYTHOFETCH_DIR
            / FAMILY_FOLDERS[family]
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

    if PYTHOFETCH_CATALOGUE.is_file():
        return False

    catalogue = {
        "format": "PythoFetchArtCatalogue",
        "format_version": 2,
        "source_project": "PythoFetch",
        "curated": True,
        "entry_count": 0,
        "family_counts": {
            family: 0
            for family in FAMILIES
        },
        "entries": [],
    }

    PYTHOFETCH_CATALOGUE.write_text(
        json.dumps(
            catalogue,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return True


def load_catalogue(
    catalogue_file,
    source_name,
):
    if not catalogue_file.is_file():
        raise RuntimeError(
            f"{source_name} Catalogue.json "
            "was not found:\n"
            f"{display_path(catalogue_file)}"
        )

    try:
        data = json.loads(
            catalogue_file.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise RuntimeError(
            f"{source_name} Catalogue.json "
            "could not be read."
        ) from exc

    if (
        data.get("format")
        != "PythoFetchArtCatalogue"
    ):
        raise RuntimeError(
            f"{source_name} Catalogue.json "
            "has an unsupported format."
        )

    entries = data.get("entries")

    if not isinstance(entries, list):
        raise RuntimeError(
            f"{source_name} Catalogue.json "
            "does not contain a valid "
            "entries list."
        )

    declared_count = data.get(
        "entry_count"
    )

    if (
        declared_count is not None
        and int(declared_count)
        != len(entries)
    ):
        raise RuntimeError(
            f"{source_name} Catalogue.json "
            "entry_count does not match "
            "the entries list."
        )

    return data, entries


def validate_art_path(
    source_dir,
    relative_file,
):
    root = source_dir.resolve()
    art_file = (
        source_dir / relative_file
    ).resolve()

    try:
        art_file.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(
            "Artwork path escapes its "
            "source folder:\n"
            f"{relative_file}"
        ) from exc

    return art_file


def validate_entry(
    entry,
    source_dir,
    source_name,
    position,
):
    required = (
        "id",
        "name",
        "family",
        "variant",
        "file",
    )

    for field in required:
        value = entry.get(field)

        if value in (None, ""):
            raise RuntimeError(
                f"{source_name} entry "
                f"{position} is missing "
                f"required field: {field}"
            )

    artwork_id = str(
        entry["id"]
    ).strip()

    if not ARTWORK_ID_PATTERN.fullmatch(
        artwork_id
    ):
        raise RuntimeError(
            f"{source_name} entry "
            f"{position} has an invalid "
            f"artwork ID:\n{artwork_id}"
        )

    family = str(
        entry["family"]
    ).strip()

    if family not in FAMILIES:
        raise RuntimeError(
            f"{source_name} entry "
            f"{position} has an invalid "
            f"family:\n{family}"
        )

    relative_file = str(
        entry["file"]
    ).replace(
        "\\",
        "/",
    )

    expected_prefix = (
        FAMILY_FOLDERS[family]
        + "/"
    )

    if not relative_file.startswith(
        expected_prefix
    ):
        raise RuntimeError(
            f"{source_name} entry "
            f"{position} is not stored "
            "inside its family folder:\n"
            f"{relative_file}"
        )

    art_file = validate_art_path(
        source_dir,
        relative_file,
    )

    if not art_file.is_file():
        raise RuntimeError(
            "Artwork file is missing:\n"
            f"{display_path(art_file)}"
        )

    art = art_file.read_text(
        encoding="utf-8",
        errors="strict",
    )

    if not art.strip():
        raise RuntimeError(
            "Artwork file is empty:\n"
            f"{display_path(art_file)}"
        )

    aliases = []

    for value in normalize_list(
        entry.get("aliases")
    ):
        alias = str(value).strip()

        if (
            alias
            and alias.casefold()
            not in {
                item.casefold()
                for item in aliases
            }
        ):
            aliases.append(alias)

    colors = [
        str(value).strip()
        for value in normalize_list(
            entry.get("colors")
        )
        if str(value).strip()
    ]

    color_markers = sorted(
        {
            int(match.group(1))
            for match in
            COLOR_TOKEN_PATTERN.finditer(
                art
            )
        }
    )

    return {
        "id": artwork_id,
        "name": str(
            entry["name"]
        ).strip(),
        "family": family,
        "variant": str(
            entry["variant"]
        ).strip(),
        "file": relative_file,
        "aliases": aliases,
        "colors": colors,
        "color_rule": entry.get(
            "color_rule"
        ),
        "matcher": entry.get(
            "matcher"
        ),
        "parent_matcher": entry.get(
            "parent_matcher"
        ),
        "source": source_name,
        "override": bool(
            entry.get("override", False)
        ),
        "art": art,
        "color_markers": color_markers,
        "original_index": entry.get(
            "original_index"
        ),
        "original_id": entry.get(
            "original_id"
        ),
        "original_file": entry.get(
            "original_file"
        ),
    }


def validate_source(
    source_dir,
    source_name,
    raw_entries,
):
    validated = []
    ids = set()

    print(
        f"Validating {source_name}: "
        f"{len(raw_entries)} entries"
    )

    for position, entry in enumerate(
        raw_entries,
        start=1,
    ):
        item = validate_entry(
            entry,
            source_dir,
            source_name,
            position,
        )

        id_key = item[
            "id"
        ].casefold()

        if id_key in ids:
            raise RuntimeError(
                f"Duplicate {source_name} "
                "artwork ID found:\n"
                f"{item['id']}"
            )

        ids.add(id_key)
        validated.append(item)

    return validated


def merge_entries(
    neofetch_entries,
    pythofetch_entries,
):
    merged = {
        entry["id"].casefold():
            entry
        for entry in neofetch_entries
    }

    override_count = 0
    added_count = 0

    for entry in pythofetch_entries:
        id_key = entry[
            "id"
        ].casefold()

        existing = merged.get(
            id_key
        )

        if existing:
            if not entry["override"]:
                raise RuntimeError(
                    "PythoFetch artwork "
                    "collides with an "
                    "existing artwork ID:\n"
                    f"{entry['id']}\n\n"
                    "Add \"override\": true "
                    "to the PythoFetch "
                    "catalogue entry if the "
                    "replacement is "
                    "intentional."
                )

            merged[id_key] = entry
            override_count += 1
            continue

        if entry["override"]:
            raise RuntimeError(
                "PythoFetch artwork is "
                "marked as an override but "
                "no existing artwork has "
                "that ID:\n"
                f"{entry['id']}"
            )

        merged[id_key] = entry
        added_count += 1

    return (
        list(
            merged.values()
        ),
        added_count,
        override_count,
    )


def create_schema(connection):
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE artwork (
            id TEXT PRIMARY KEY COLLATE NOCASE,
            name TEXT NOT NULL,
            family TEXT NOT NULL,
            variant TEXT NOT NULL,
            file TEXT NOT NULL,
            matcher TEXT,
            parent_matcher TEXT,
            color_rule TEXT,
            colors_json TEXT NOT NULL,
            color_markers_json TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            source TEXT NOT NULL,
            art TEXT NOT NULL,
            original_index INTEGER,
            original_id TEXT,
            original_file TEXT
        );

        CREATE TABLE aliases (
            alias TEXT NOT NULL COLLATE NOCASE,
            artwork_id TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY (
                alias,
                artwork_id
            ),
            FOREIGN KEY (
                artwork_id
            )
            REFERENCES artwork(id)
            ON DELETE CASCADE
        );

        CREATE INDEX idx_artwork_family
        ON artwork(
            family COLLATE NOCASE
        );

        CREATE INDEX idx_artwork_name
        ON artwork(
            name COLLATE NOCASE
        );

        CREATE INDEX idx_artwork_variant
        ON artwork(
            variant COLLATE NOCASE
        );

        CREATE INDEX idx_artwork_family_name
        ON artwork(
            family COLLATE NOCASE,
            name COLLATE NOCASE
        );

        CREATE INDEX idx_alias_lookup
        ON aliases(
            alias COLLATE NOCASE
        );
        """
    )


def count_values(
    entries,
    field,
):
    counts = {}

    for entry in entries:
        value = entry[field]

        counts[value] = (
            counts.get(
                value,
                0,
            )
            + 1
        )

    return counts


def insert_metadata(
    connection,
    database_version,
    entries,
    source_catalogues,
    override_count,
):
    family_counts = count_values(
        entries,
        "family",
    )

    source_counts = count_values(
        entries,
        "source",
    )

    metadata = {
        "database_name":
            "PythoFetchArt",
        "database_version":
            database_version,
        "schema_version":
            str(SCHEMA_VERSION),
        "compiler_version":
            MANAGER_VERSION,
        "created_utc":
            utc_now(),
        "entry_count":
            str(len(entries)),
        "override_count":
            str(override_count),
        "catalogue_format":
            "PythoFetchArtCatalogue",
        "family_counts":
            json.dumps(
                family_counts,
                sort_keys=True,
            ),
        "source_counts":
            json.dumps(
                source_counts,
                sort_keys=True,
            ),
        "source_catalogues":
            json.dumps(
                source_catalogues,
                sort_keys=True,
                ensure_ascii=False,
            ),
    }

    connection.executemany(
        """
        INSERT INTO metadata (
            key,
            value
        )
        VALUES (?, ?)
        """,
        metadata.items(),
    )


def insert_artwork(
    connection,
    entries,
):
    for entry in entries:
        connection.execute(
            """
            INSERT INTO artwork (
                id,
                name,
                family,
                variant,
                file,
                matcher,
                parent_matcher,
                color_rule,
                colors_json,
                color_markers_json,
                aliases_json,
                source,
                art,
                original_index,
                original_id,
                original_file
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                entry["id"],
                entry["name"],
                entry["family"],
                entry["variant"],
                entry["file"],
                entry["matcher"],
                entry[
                    "parent_matcher"
                ],
                entry["color_rule"],
                json.dumps(
                    entry["colors"],
                    ensure_ascii=False,
                ),
                json.dumps(
                    entry[
                        "color_markers"
                    ]
                ),
                json.dumps(
                    entry["aliases"],
                    ensure_ascii=False,
                ),
                entry["source"],
                entry["art"],
                entry[
                    "original_index"
                ],
                entry[
                    "original_id"
                ],
                entry[
                    "original_file"
                ],
            ),
        )

        alias_values = {
            str(value).strip()
            for value in (
                entry["aliases"]
                + [
                    entry["name"],
                    entry["id"],
                ]
            )
            if str(value).strip()
        }

        for alias in sorted(
            alias_values,
            key=str.casefold,
        ):
            connection.execute(
                """
                INSERT OR IGNORE INTO aliases (
                    alias,
                    artwork_id
                )
                VALUES (?, ?)
                """,
                (
                    alias,
                    entry["id"],
                ),
            )


def verify_database(
    connection,
    expected_count,
    database_version,
):
    artwork_count = connection.execute(
        "SELECT COUNT(*) FROM artwork"
    ).fetchone()[0]

    if artwork_count != expected_count:
        raise RuntimeError(
            "Artwork count "
            "verification failed.\n"
            f"Expected : "
            f"{expected_count}\n"
            f"Database : "
            f"{artwork_count}"
        )

    missing_art = connection.execute(
        """
        SELECT COUNT(*)
        FROM artwork
        WHERE art IS NULL
           OR length(art) = 0
        """
    ).fetchone()[0]

    if missing_art:
        raise RuntimeError(
            f"{missing_art} artwork "
            "entries contain no art data."
        )

    stored_version = connection.execute(
        """
        SELECT value
        FROM metadata
        WHERE key = 'database_version'
        """
    ).fetchone()

    if (
        not stored_version
        or stored_version[0]
        != database_version
    ):
        raise RuntimeError(
            "Database version metadata "
            "verification failed."
        )

    integrity = connection.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0]

    if integrity != "ok":
        raise RuntimeError(
            "SQLite integrity check "
            "failed:\n"
            f"{integrity}"
        )

    return artwork_count


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def database_versions_on_disk():
    versions = []

    if not DATABASE_DIR.is_dir():
        return versions

    for path in DATABASE_DIR.iterdir():
        if not path.is_file():
            continue

        match = DATABASE_PATTERN.match(
            path.name
        )

        if match:
            versions.append(
                match.group(1)
            )

    return versions


def empty_manifest():
    return {
        "schema": (
            MANIFEST_SCHEMA_VERSION
        ),
        "database": "PythoFetchArt",
        "latest_version": None,
        "versions": {},
    }


def migrate_manifest_name():
    if MANIFEST_FILE.is_file():
        return

    if OLD_MANIFEST_FILE.is_file():
        OLD_MANIFEST_FILE.replace(
            MANIFEST_FILE
        )


def load_manifest():
    migrate_manifest_name()

    if not MANIFEST_FILE.is_file():
        return empty_manifest()

    try:
        manifest = json.loads(
            MANIFEST_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise RuntimeError(
            "PythoFetchArt manifest "
            "could not be read."
        ) from exc

    if not isinstance(
        manifest.get("versions"),
        dict,
    ):
        raise RuntimeError(
            "PythoFetchArt manifest "
            "contains an invalid "
            "versions object."
        )

    return manifest


def normalize_manifest_download_urls(
    manifest,
):
    changed = False
    versions = manifest.get(
        "versions",
        {},
    )

    for version, entry in versions.items():
        if not isinstance(entry, dict):
            raise RuntimeError(
                "PythoFetchArt manifest "
                "contains an invalid entry "
                f"for version {version}."
            )

        filename = entry.get("file")

        if not filename:
            raise RuntimeError(
                "PythoFetchArt manifest "
                "entry is missing its file "
                f"name for version {version}."
            )

        expected_url = (
            database_download_url(
                filename
            )
        )

        if (
            entry.get("download_url")
            != expected_url
        ):
            entry[
                "download_url"
            ] = expected_url
            changed = True

    return changed


def latest_existing_version(
    manifest,
):
    versions = set(
        database_versions_on_disk()
    )

    versions.update(
        version
        for version in
        manifest.get(
            "versions",
            {}
        )
        if VERSION_PATTERN.fullmatch(
            version
        )
    )

    if not versions:
        return None

    return max(
        versions,
        key=version_key,
    )


def resolve_database_version(
    requested_version,
    manifest,
):
    latest = latest_existing_version(
        manifest
    )

    if requested_version:
        version = (
            requested_version.strip()
        )
    else:
        print(
            "Latest DB version : "
            + (
                latest
                if latest
                else "None"
            )
        )
        print()

        version = input(
            "Version for new database "
            "(x.x.x): "
        ).strip()

    if not VERSION_PATTERN.fullmatch(
        version
    ):
        raise RuntimeError(
            "Database version must use "
            "x.x.x format."
        )

    if latest:
        if (
            version_key(version)
            <= version_key(latest)
        ):
            raise RuntimeError(
                "New database version must "
                "be greater than the "
                "current latest version.\n"
                f"Latest : {latest}\n"
                f"New    : {version}"
            )

    target = DATABASE_DIR / (
        f"PythoFetchArt_{version}.db"
    )

    if target.exists():
        raise RuntimeError(
            "Database version already "
            "exists:\n"
            f"{target}"
        )

    if (
        version
        in manifest.get(
            "versions",
            {}
        )
    ):
        raise RuntimeError(
            "Database version is already "
            "listed in the manifest:\n"
            f"{version}"
        )

    return version


def build_database(
    database_version,
    entries,
    source_catalogues,
    override_count,
):
    DATABASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if STAGING_DB.exists():
        STAGING_DB.unlink()

    print()
    print(
        "Building "
        "PythoFetchArtNew.db..."
    )

    connection = sqlite3.connect(
        STAGING_DB
    )

    try:
        create_schema(connection)

        insert_metadata(
            connection,
            database_version,
            entries,
            source_catalogues,
            override_count,
        )

        insert_artwork(
            connection,
            entries,
        )

        connection.commit()

        count = verify_database(
            connection,
            len(entries),
            database_version,
        )

        connection.execute(
            "VACUUM"
        )

        connection.commit()

        verify_database(
            connection,
            len(entries),
            database_version,
        )

    finally:
        connection.close()

    return count


def build_manifest_entry(
    database_version,
    database_path,
    entries,
    added_count,
    override_count,
):
    return {
        "file": database_path.name,
        "download_url": (
            database_download_url(
                database_path.name
            )
        ),
        "sha256": sha256_file(
            database_path
        ),
        "size_bytes": (
            database_path.stat().st_size
        ),
        "created_utc": utc_now(),
        "schema_version": (
            SCHEMA_VERSION
        ),
        "compiler_version": (
            MANAGER_VERSION
        ),
        "artwork_count": len(entries),
        "added_pythofetch_artworks":
            added_count,
        "override_count":
            override_count,
        "source_counts": count_values(
            entries,
            "source",
        ),
        "family_counts": count_values(
            entries,
            "family",
        ),
    }


def sorted_versions(values):
    return sorted(
        values,
        key=version_key,
    )


def write_manifest_temp(
    manifest,
):
    versions = manifest.get(
        "versions",
        {}
    )

    ordered_versions = {
        version: versions[version]
        for version in sorted_versions(
            versions
        )
    }

    manifest[
        "versions"
    ] = ordered_versions

    MANIFEST_TEMP.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def write_manifest(
    manifest,
):
    DATABASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_manifest_temp(
        manifest
    )

    try:
        os.replace(
            MANIFEST_TEMP,
            MANIFEST_FILE,
        )

    finally:
        if MANIFEST_TEMP.exists():
            MANIFEST_TEMP.unlink()


def promote_database(
    database_version,
    manifest,
    entries,
    added_count,
    override_count,
):
    target = DATABASE_DIR / (
        f"PythoFetchArt_"
        f"{database_version}.db"
    )

    checksum = sha256_file(
        STAGING_DB
    )

    manifest_entry = {
        "file": target.name,
        "download_url": (
            database_download_url(
                target.name
            )
        ),
        "sha256": checksum,
        "size_bytes": (
            STAGING_DB.stat().st_size
        ),
        "created_utc": utc_now(),
        "schema_version": (
            SCHEMA_VERSION
        ),
        "compiler_version": (
            MANAGER_VERSION
        ),
        "artwork_count": len(entries),
        "added_pythofetch_artworks":
            added_count,
        "override_count":
            override_count,
        "source_counts": count_values(
            entries,
            "source",
        ),
        "family_counts": count_values(
            entries,
            "family",
        ),
    }

    normalize_manifest_download_urls(
        manifest
    )

    updated_manifest = {
        "schema": (
            MANIFEST_SCHEMA_VERSION
        ),
        "database": "PythoFetchArt",
        "latest_version": (
            database_version
        ),
        "versions": dict(
            manifest.get(
                "versions",
                {}
            )
        ),
    }

    updated_manifest[
        "versions"
    ][
        database_version
    ] = manifest_entry

    write_manifest_temp(
        updated_manifest
    )

    promoted = False

    try:
        os.replace(
            STAGING_DB,
            target,
        )

        promoted = True

        os.replace(
            MANIFEST_TEMP,
            MANIFEST_FILE,
        )

    except Exception:
        if promoted and target.exists():
            target.unlink()

        raise

    finally:
        if MANIFEST_TEMP.exists():
            MANIFEST_TEMP.unlink()

        if STAGING_DB.exists():
            STAGING_DB.unlink()

    return (
        target,
        manifest_entry,
    )


def build_source_catalogue_metadata(
    neofetch_catalogue,
    pythofetch_catalogue,
):
    return {
        "NeoFetch": {
            "format_version":
                neofetch_catalogue.get(
                    "format_version"
                ),
            "entry_count":
                neofetch_catalogue.get(
                    "entry_count"
                ),
        },
        "PythoFetch": {
            "format_version":
                pythofetch_catalogue.get(
                    "format_version"
                ),
            "entry_count":
                pythofetch_catalogue.get(
                    "entry_count"
                ),
        },
    }


def show_summary(
    database_version,
    database_path,
    manifest_entry,
    entries,
):
    print()
    print("=" * 72)
    print(
        "PYTHOFETCH ART DATABASE COMPLETE"
    )
    print("=" * 72)
    print(
        "Database  : "
        f"{display_path(database_path)}"
    )
    print(
        f"Version   : {database_version}"
    )
    print(
        f"Artworks  : {len(entries)}"
    )
    print(
        "NeoFetch  : "
        f"{manifest_entry['source_counts'].get('NeoFetch', 0)}"
    )
    print(
        "PythoFetch: "
        f"{manifest_entry['source_counts'].get('PythoFetch', 0)}"
    )
    print(
        "New       : "
        f"{manifest_entry['added_pythofetch_artworks']}"
    )
    print(
        "Overrides : "
        f"{manifest_entry['override_count']}"
    )

    for family in FAMILIES:
        print(
            f"{family:<10}: "
            f"{manifest_entry['family_counts'].get(family, 0)}"
        )

    print(
        "SHA-256   : "
        f"{manifest_entry['sha256']}"
    )
    print(
        "Size      : "
        f"{manifest_entry['size_bytes'] / 1024:.1f} KiB"
    )
    print(
        "Manifest  : "
        f"{display_path(MANIFEST_FILE)}"
    )
    print("=" * 72)


def build_argument_parser():
    parser = argparse.ArgumentParser(
        prog=(
            "PythoFetchArtManager"
        ),
    )

    parser.add_argument(
        "--version",
        dest="database_version",
    )

    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
    )

    return parser


def main():
    parser = build_argument_parser()
    args = parser.parse_args()

    print()
    print(
        "PYTHOFETCH ART MANAGER"
    )
    print("=" * 72)
    print(
        "NeoFetch  : ArtAssetsNeofetch"
    )
    print(
        "PythoFetch: ArtAssetsPythoFetch"
    )
    print(
        "Database  : ArtAssetsDB"
    )
    print("=" * 72)
    print()

    migrate_asset_folder_names()
    migrate_manifest_name()

    if args.refresh_manifest:
        manifest = load_manifest()

        changed = (
            normalize_manifest_download_urls(
                manifest
            )
        )

        if changed:
            write_manifest(
                manifest
            )

            print(
                "Manifest download URLs "
                "updated."
            )
        else:
            print(
                "Manifest download URLs "
                "are already current."
            )

        print(
            "Manifest  : "
            f"{display_path(MANIFEST_FILE)}"
        )

        return

    (
        neofetch_catalogue,
        neofetch_entries,
    ) = load_or_rebuild_neofetch_source()

    ensure_pythofetch_source()

    (
        pythofetch_catalogue,
        pythofetch_raw,
    ) = load_catalogue(
        PYTHOFETCH_CATALOGUE,
        "PythoFetch",
    )

    pythofetch_entries = (
        validate_source(
            PYTHOFETCH_DIR,
            "PythoFetch",
            pythofetch_raw,
        )
    )

    (
        entries,
        added_count,
        override_count,
    ) = merge_entries(
        neofetch_entries,
        pythofetch_entries,
    )

    print()
    print(
        f"Merged artwork entries: "
        f"{len(entries)}"
    )
    print(
        f"New PythoFetch artwork: "
        f"{added_count}"
    )
    print(
        f"PythoFetch overrides   : "
        f"{override_count}"
    )
    print()

    manifest = load_manifest()

    normalize_manifest_download_urls(
        manifest
    )

    database_version = (
        resolve_database_version(
            args.database_version,
            manifest,
        )
    )

    source_catalogues = (
        build_source_catalogue_metadata(
            neofetch_catalogue,
            pythofetch_catalogue,
        )
    )

    build_database(
        database_version,
        entries,
        source_catalogues,
        override_count,
    )

    (
        database_path,
        manifest_entry,
    ) = promote_database(
        database_version,
        manifest,
        entries,
        added_count,
        override_count,
    )

    show_summary(
        database_version,
        database_path,
        manifest_entry,
        entries,
    )


if __name__ == "__main__":
    exit_code = 0
    pause_on_exit = True

    try:
        main()

    except ManagerCancelled:
        pause_on_exit = False

    except Exception:
        exit_code = 1

        print()
        print(
            "PYTHOFETCH ART "
            "MANAGER ERROR"
        )
        print("=" * 72)

        traceback.print_exc()

        print("=" * 72)

        if STAGING_DB.exists():
            try:
                STAGING_DB.unlink()
            except Exception:
                pass

        if MANIFEST_TEMP.exists():
            try:
                MANIFEST_TEMP.unlink()
            except Exception:
                pass

    finally:
        if pause_on_exit:
            print()

            try:
                input(
                    "Press Enter to exit..."
                )

            except EOFError:
                pass

    raise SystemExit(exit_code)
