"""Reference checker for Session K's registry contracts (FR-347 / 348 / 349 / 350) — K-SPEC.md rules.

Run from the repo root:  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe <this file> [styles.yaml]
Prints every finding per style and a final count. Zero findings = the prose wave is done.
This is the SPEC in executable form; hypesocials/styles.py must agree with it on the shipped file.
"""
import colorsys
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(r"C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials")
PATH = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "prompts" / "styles.yaml"

HEX = re.compile(r"#([0-9A-Fa-f]{6})\b")
ROLE = re.compile(r"^([A-Z][A-Z +/]*?)(?=\s*(?:[a-z#:]|$))")
BACKGROUND = ("GROUND", "GROUNDS", "SURFACE", "DEPTH", "SHADOW")
COVERAGE = re.compile(
    r"under\s+(\d+)\s*/\s*(\d+)|under\s+(\d+)\s*%|(?:≤|<=|max|at most)\s*1\s*/\s*(\d+)", re.I)
MARKERS = (" or ", "variant ", "either ")
NEGATION = re.compile(
    r"\b(no|not|never|nothing|none|nor|neither|without|rather than)\b", re.I)
FAMILIES = {
    "serif": r"\b(serif|didone|slab)\b",
    "sans": r"\b(sans|grotesque|geometric|humanist|gothic)\b",
    "mono": r"\b(mono|monospace)\b",
    "script": r"\b(script|handwritten|hand-lettered|marker)\b",
    "woodtype": r"\b(woodtype|display face|display type)\b",
}
SAFE_AREA = "central 80% of the 1:1 frame"
CROP_BAND = re.compile(r"4:5|bottom\s+12\s*%", re.I)
MONO_UTILITY = {"build-log-mono", "circuit-atlas-dark", "terminal-mockup-deck"}


def hsv(hex6: str) -> tuple[float, float, float]:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s, v


def saturated(hex6: str) -> bool:
    _, s, v = hsv(hex6)
    return s >= 0.45 and 0.15 <= v <= 0.95


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def role_of(line: str) -> str:
    m = ROLE.match(line.strip())
    return m.group(1).strip() if m else ""


def is_background(line: str) -> bool:
    role = role_of(line)
    return any(role == w or role.startswith(w + " ") or role.startswith(w + "+") for w in BACKGROUND)


def coverage_bound(line: str) -> float | None:
    m = COVERAGE.search(line)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1)) / int(m.group(2))
    if m.group(3):
        return int(m.group(3)) / 100
    return 1 / int(m.group(4))


def clauses(text: str) -> list[str]:
    flat = " ".join(str(text).split())
    return [c for c in re.split(r";\s+|\.\s+|:\s+|\n", flat) if c]


def leaky(clause: str) -> bool:
    low = f" {clause.lower()} "
    return any(m in low for m in MARKERS) and not NEGATION.search(clause)


def fr347(style: dict) -> list[str]:
    out: list[str] = []
    accents: list[tuple[str, float, str]] = []
    grounds: list[tuple[str, float]] = []
    for line in style.get("palette") or []:
        hexes = [h.upper() for h in HEX.findall(line) if saturated(h)]
        if not hexes:
            continue
        if is_background(line):
            grounds.extend((h, hsv(h)[0]) for h in hexes)
            continue
        accents.extend((h, hsv(h)[0], line) for h in hexes)
        bound = coverage_bound(line)
        if bound is None:
            out.append(f"FR-347 no coverage clause on accent line: {line[:70]}")
        elif bound > 0.125 + 1e-9:
            out.append(f"FR-347 coverage {bound:.3f} > 1/8 on accent line: {line[:70]}")
    hues = [a[1] for a in accents]
    if any(hue_distance(a, b) > 30 for a in hues for b in hues):
        out.append("FR-347 accent hexes span more than one hue family: "
                   + ", ".join(f"{h} {round(hh)}°" for h, hh, _ in accents))
    for g, gh in grounds:
        if hues and all(hue_distance(gh, a) <= 30 for a in hues):
            out.append(f"FR-347 saturated ground {g} {round(gh)}° does not contrast with the accent family")
    return out


def dna_fields(style: dict) -> dict[str, str]:
    fields = {k: style.get(k, "") or "" for k in
              ("typography", "text_placement", "image_treatment", "visual_pacing")}
    fields["palette"] = "\n".join(style.get("palette") or [])
    fields["list_mode.layout"] = (style.get("list_mode") or {}).get("layout", "") or ""
    for k, v in (style.get("per_format_guidance") or {}).items():
        fields[f"per_format_guidance.{k}"] = str(v)
    return fields


def fr349(style: dict) -> list[str]:
    return [f"FR-349 {f}: choice left open: {c[:70]}"
            for f, t in dna_fields(style).items() for c in clauses(t) if leaky(c)]


def fr348(style: dict) -> list[str]:
    texts = [style.get("typography", "") or ""] + [
        z.get("text_treatment", "") or "" for z in style.get("layout_zones") or []]
    named: set[str] = set()
    for t in texts:
        for c in clauses(t):
            if NEGATION.search(c):
                continue
            named |= {k for k, p in FAMILIES.items() if re.search(p, c, re.I)}
    extra = named - {"mono"} if "mono" in named else named
    if len(named) > 2 and not (len(named) == 3 and "mono" in named):
        return [f"FR-348 {len(named)} type families named: {sorted(named)}"]
    if len(named) == 3 and style["key"] not in MONO_UTILITY:
        return [f"FR-348 mono utility outside the code/terminal identity: {sorted(named)} (test guard)"]
    return []


def fr350(style: dict) -> list[str]:
    if "carousel" not in [f.lower() for f in style.get("format_affinity") or []]:
        return []
    out: list[str] = []
    for z in style.get("layout_zones") or []:
        if z.get("role") == "counter_slot" and "top-right" not in str(z.get("position", "")).lower():
            out.append(f"FR-350 counter zone not top-right: {z.get('position')}")
    blob = yaml.safe_dump(style, allow_unicode=True)
    if re.search(r"(chip|badge|counter)[^.;]{0,40}top-left|top-left[^.;]{0,40}(chip|badge|counter)", blob, re.I):
        out.append("FR-350 prose still puts a counter/chip top-left")
    if SAFE_AREA not in " ".join(str(style.get("text_placement", "")).split()):
        out.append("FR-350 safe-area sentence missing from text_placement")
    if CROP_BAND.search(blob):
        out.append("FR-350 4:5 / bottom-12% band present")
    if str(style.get("motion_profile", "")).lower() != "photographic":
        grounds = [l for l in style.get("palette") or [] if role_of(l).startswith("GROUND")]
        if grounds:
            for h in HEX.findall(grounds[0]):
                v = hsv(h)[2]
                if not (v >= 0.85 or v <= 0.20):
                    out.append(f"FR-350 graphic ground #{h.upper()} V={v:.2f} is not at a value extreme")
    return out


def main() -> None:
    reg = yaml.safe_load(PATH.read_text(encoding="utf-8"))
    total = 0
    for style in reg["styles"]:
        findings = fr347(style) + fr348(style) + fr349(style) + fr350(style)
        total += len(findings)
        print(f"{style['key']}: {len(findings)} finding(s)")
        for f in findings:
            print(f"    {f}")
    print(f"\nTOTAL {total} finding(s) across {len(reg['styles'])} styles")


if __name__ == "__main__":
    main()
