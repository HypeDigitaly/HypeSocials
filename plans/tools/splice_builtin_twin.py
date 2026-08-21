"""Splice a `prompts/<name>.md` file into `prompts_engine._BUILT_INS` as its byte-identical twin.

Every shipped prompt has an FR-183 built-in fallback that must equal the file byte for byte
(`tests/test_template_parity.py`). Hand-copying a 6,000-character template into a triple-quoted
string is how the two drift, so this tool does the copy: it REPLACES an existing entry in place,
or INSERTS a new one right after `--after` (default: `copy_compress_system.md`) with a short
comment block naming the decision that added it.

Usage (from the repo root, the venv interpreter):

    .venv/Scripts/python.exe plans/tools/splice_builtin_twin.py copy_translate_system.md \
        --comment "v2.7.0 (D63, FR-343/344) — the carousel TRANSLATE call."

The template must not contain a triple double-quote or a backslash the Python literal would
re-interpret; the tool refuses rather than guessing. After splicing it re-reads the module and
asserts `pe._BUILT_INS[name] == file bytes`.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "hypesocials" / "prompts_engine.py"
PROMPTS = ROOT / "prompts"


def _entry_bounds(source: str, name: str) -> tuple[int, int] | None:
    """(start, end) offsets of the `"<name>": <triple-quoted string>,` entry in `_BUILT_INS`."""
    head = f'    "{name}": """'
    start = source.find(head)
    if start < 0:
        return None
    close = source.find('""",\n', start + len(head))
    if close < 0:
        raise SystemExit(f"unterminated built-in entry for {name}")
    return start, close + len('""",\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="template file name, e.g. copy_translate_system.md")
    parser.add_argument("--after", default="copy_compress_system.md",
                        help="existing entry a NEW twin is inserted after")
    parser.add_argument("--comment", default="",
                        help="one-line comment written above a NEW entry")
    args = parser.parse_args()

    template = (PROMPTS / args.name).read_text(encoding="utf-8")
    if '"""' in template or "\\" in template:
        raise SystemExit(f"{args.name} contains a triple quote or a backslash — splice by hand")
    # Keep the working copy's own line endings (core.autocrlf=true checks this file out as
    # CRLF): read raw, detect, splice in LF space, write back in the same convention.
    raw = ENGINE.read_text(encoding="utf-8", newline="")
    eol = "\r\n" if "\r\n" in raw else "\n"
    source = raw.replace("\r\n", "\n")
    literal = f'    "{args.name}": """{template}""",\n'
    bounds = _entry_bounds(source, args.name)
    if bounds is not None:
        start, end = bounds
        source = source[:start] + literal + source[end:]
        verb = "replaced"
    else:
        anchor = _entry_bounds(source, args.after)
        if anchor is None:
            raise SystemExit(f"no built-in entry named {args.after} to insert after")
        comment = (f"\n    # {args.comment} BYTE-IDENTICAL to prompts/{args.name}, like every "
                   "live entry in this table;\n    # spliced by plans/tools/splice_builtin_twin.py "
                   "— change the file, re-run the tool in the same commit.\n"
                   if args.comment else "\n")
        source = source[:anchor[1]] + comment + literal + source[anchor[1]:]
        verb = "inserted"
    ENGINE.write_text(source.replace("\n", eol), encoding="utf-8", newline="")

    sys.path.insert(0, str(ROOT))
    pe = importlib.import_module("hypesocials.prompts_engine")
    importlib.reload(pe)
    twin = pe._BUILT_INS[args.name]
    if twin != template:
        raise SystemExit(f"{args.name}: twin differs from the file after splicing "
                         f"({len(twin)} vs {len(template)} chars)")
    print(f"{verb} built-in twin for {args.name}: {len(template)} chars, byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
