"""Campaign briefs — one named file (or folder) in, one fully validated `Brief` out (FR-172, D26).

Public API: `load(name, briefs_dir) -> Brief` · `list_briefs(briefs_dir)` · `BriefError`.

A brief resolves from the active config's `briefs_dir` ONLY — no search path, no cross-folder
collision rules (30 §2, v1.6.1). Two shapes, one meaning: `<name>.yaml`, or `<name>/brief.yaml`
when the brief ships its own images beside it (reference paths then resolve against that folder).
The file/folder name IS the brief name, the value `--brief <name>:<count>` takes.

Invariants: missing or malformed raises `BriefError` NAMING THE EXACT FILE in the malformed-config
shape (file, field, value, expected form), which pre-flight prints as one line before any billable
call — refusing interactively, dropping only that brief's creatives under `--yes`. Validation is
total, so nothing downstream re-checks a brief: `influence` is already one of FR-144/145's two
modes, `formats` a non-empty canonical subset of image/carousel/reel, every directive non-empty
text, every reference an existing image file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

import yaml

from .models import Brief, CreativeFormat, InfluenceMode
from .util import read_text

#: The brief file inside a folder-shaped brief (the shape used when it ships its own images).
BRIEF_FILENAMES: tuple[str, ...] = ("brief.yaml", "brief.yml")
_YAML_SUFFIXES = (".yaml", ".yml")
_FORMATS: tuple[CreativeFormat, ...] = ("image", "carousel", "reel")  # canonical order, 10 FR-1
_MODES: tuple[InfluenceMode, ...] = ("override", "blend")  # 10 FR-144/145
_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})


class BriefError(Exception):
    """One unresolvable or malformed brief. `str(e)` is the whole operator-facing line."""


def load(name: str, briefs_dir: Path) -> Brief:
    """Resolve and validate one campaign brief — the pinned `models.BriefLoader` signature.

    `name` is what `--brief <name>:<count>` (or the menu's Briefs step) asked for; `briefs_dir` is
    the active config's key and the only folder consulted. Raises `BriefError` — one line naming
    the exact file — when the brief is missing, unreadable, invalid YAML, or fails FR-172's shape.
    """
    path = _resolve(name, Path(briefs_dir))
    try:
        raw: Any = yaml.safe_load(read_text(path))
    except OSError as exc:
        raise BriefError(f"brief {path} could not be read: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        detail = " ".join(str(getattr(exc, "problem", None) or exc).split())
        raise BriefError(f"brief {path} is not valid YAML — {detail}") from exc
    if not isinstance(raw, Mapping):
        raise BriefError(f"brief {path}: expected a mapping of brief fields at the top level")
    declared = str(raw.get("name") or name).strip()  # the in-file name is optional, but must agree
    if declared != name:
        _fail(path, "name", declared, f"{name!r} — the file/folder name is the brief name")
    return Brief(
        name=name,
        description=_description(raw, path),
        influence=_influence(raw, path),
        formats=_formats(raw, path),
        copy_directives=_directives(raw, "copy_directives", path),
        visual_directives=_directives(raw, "visual_directives", path),
        reference_image_paths=_references(raw, path),
    )


def list_briefs(briefs_dir: Path) -> list[tuple[str, str]]:
    """`(name, description)` for every brief in `briefs_dir`, sorted — the menu's Briefs step.

    Never raises: a `briefs_dir` that does not exist yet lists nothing (30 §8) and a malformed
    sibling shows with an empty description instead of blanking the picker — the error an operator
    needs still arrives at `load()` time, naming that file.
    """
    folder, found = Path(briefs_dir), {}
    for entry in sorted(folder.glob("*")) if folder.is_dir() else []:
        name, shapes = (entry.name, [entry / n for n in BRIEF_FILENAMES]) if entry.is_dir() \
            else (entry.stem, [entry] if entry.suffix.lower() in _YAML_SUFFIXES else [])
        path = next((shape for shape in shapes if shape.is_file()), None)
        if path is None or name in found:
            continue
        try:
            raw = yaml.safe_load(read_text(path))
            found[name] = _description(raw, path) if isinstance(raw, Mapping) else ""
        except (OSError, yaml.YAMLError, BriefError):
            found[name] = ""
    return sorted(found.items())


def _fail(path: Path, field: str, value: Any, expected: str) -> NoReturn:
    """The one error shape: the offending file, the field, the value found, the expected form."""
    raise BriefError(f"brief {path}: {field}: {value!r} — expected {expected}")


def _resolve(name: str, folder: Path) -> Path:
    clean = name.strip()
    if not clean or clean != Path(clean).name:  # `briefs_dir` ONLY — no traversal, no subpaths
        raise BriefError(f"brief name {name!r} — expected a plain name with no path separators, "
                         "e.g. --brief ai-audit-cta:2")
    shapes = [folder / clean / n for n in BRIEF_FILENAMES]
    shapes += [folder / f"{clean}{suffix}" for suffix in _YAML_SUFFIXES]
    for candidate in shapes:
        if candidate.is_file():
            return candidate
    available = ", ".join(n for n, _ in list_briefs(folder)) or "none"
    raise BriefError(f"brief {clean!r} not found: looked for {shapes[0]} and {shapes[2]} — "
                     f"briefs available in {folder}: {available}")


def _description(raw: Mapping[str, Any], path: Path) -> str:
    value = raw.get("description")
    if not isinstance(value, str) or not value.strip():
        _fail(path, "description", value, "one line of text describing the brief (it is shown "
                                          "wherever briefs are listed)")
    return " ".join(value.split())


def _influence(raw: Mapping[str, Any], path: Path) -> InfluenceMode:
    value = raw.get("influence")
    if value not in _MODES:
        _fail(path, "influence", value, "'override' (the brief replaces the trend inputs) or "
                                        "'blend' (the trend wins visuals, the brief wins message)")
    return value  # type: ignore[return-value]  # membership in _MODES IS the Literal check


def _formats(raw: Mapping[str, Any], path: Path) -> list[CreativeFormat]:
    value = raw.get("formats")
    requested = [value] if isinstance(value, str) else value
    if not isinstance(requested, list) or not requested:
        _fail(path, "formats", value, f"a non-empty list drawn from {', '.join(_FORMATS)}")
    unknown = [item for item in requested if item not in _FORMATS]
    if unknown:
        _fail(path, "formats", unknown, f"only {', '.join(_FORMATS)}")
    return [fmt for fmt in _FORMATS if fmt in requested]  # canonical order, deduped


def _directives(raw: Mapping[str, Any], key: str, path: Path) -> dict[str, str]:
    """FR-172's copy/visual directive blocks: directive name -> one block of instruction text."""
    value = raw.get(key)
    if not isinstance(value, Mapping) or not value:
        _fail(path, key, value, "a non-empty mapping of directive name to text "
                                "(e.g. message, cta, structure)")
    directives = {}
    for field, text in value.items():
        if not isinstance(text, str) or not text.strip():
            _fail(path, f"{key}.{field}", text, "a line of text")
        directives[str(field)] = " ".join(text.split())  # one directive, one prompt line
    return directives


def _references(raw: Mapping[str, Any], path: Path) -> list[Path]:
    """Optional brief-supplied images, resolved against the brief's own folder (D32/FR-200)."""
    value = raw.get("reference_image_paths") or []
    listed = [value] if isinstance(value, str) else value
    if not isinstance(listed, list):
        _fail(path, "reference_image_paths", value,
              "a list of image paths, relative to the brief's folder or absolute")
    references = []
    for item in listed:
        ref = Path(str(item)).expanduser()
        ref = ref if ref.is_absolute() else path.parent / ref
        if not ref.is_file():
            _fail(path, "reference_image_paths", item, f"an existing file (looked at {ref})")
        if ref.suffix.lower() not in _IMAGE_SUFFIXES:
            _fail(path, "reference_image_paths", item,
                  f"an image file ({', '.join(sorted(_IMAGE_SUFFIXES))})")
        references.append(ref)
    return references


__all__ = ["BRIEF_FILENAMES", "BriefError", "list_briefs", "load"]
