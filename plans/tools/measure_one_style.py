"""Measure ONE draft style block before it is admitted to `prompts/styles.yaml` (Session L, Wave 3a).

Run from the repo root:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe plans/tools/measure_one_style.py <draft.yaml>

`<draft.yaml>` holds exactly one style block — either a bare mapping (`key: ...` at column 0) or a
one-item list (`- key: ...`). The block is parsed by the REAL parser (`styles._style`), judged by
the REAL validators (`styles._palette_findings` = FR-347, `styles._style_warnings` = M9 + FR-348
+ FR-349 + dead list_mode + missing match_profile) and then assembled into the SAME worst carousel
slide `tests/test_prompt_fit.py` measures, at both tiers. Nothing here edits the registry.

Printed, in order:
  1. ERRORS / WARNINGS exactly as pre-flight would print them (FR-347 is an ERROR since D60).
  2. The born-compliant checklist from plan §3 + FR-350 (each line PASS/FAIL with the number).
  3. owned chars (render_prompt + carousel_slide guidance + style_dna + exclusions + list layout
     + counter zone line; target <= 4,700), style_dna (<= 2,000), counter zone (<= 200).
  4. cutA (tier A trio trim; ceiling 1,600, target <= 1,540), markerB, slackB (target >= 60).
Exit status 1 when anything is outside target, so a loop can stop on it.
"""
from __future__ import annotations

import colorsys
import logging
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]  # plans/tools/ -> repo root
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.CRITICAL)

import test_prompt_fit as t  # noqa: E402
from hypesocials import prompts_engine as pe  # noqa: E402
from hypesocials import styles  # noqa: E402
from hypesocials.generate import carousel as carousel_module  # noqa: E402

MARKER = "Every legible character in this frame"
SAFE_AREA = "inside the central 80% of the 1:1 frame"
CROP_BAND = re.compile(r"4:5|bottom\s+12\s*%", re.I)
GATED = re.compile(r"\b(chip|badge|counter|page number|signature|lockup)\b", re.I)
TOP_LEFT = re.compile(r"top-left|top left|upper-left|upper left", re.I)
CEILING, CUT_TARGET, SLACK_TARGET = 1_600, 1_540, 60
OWNED_CAP, DNA_CAP, COUNTER_CAP, WORDS_CAP = 4_700, 2_000, 200, 120


def load_block(path: pathlib.Path):
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if isinstance(data, list):
        assert len(data) == 1, "one style per draft file"
        data = data[0]
    if isinstance(data, dict) and "styles" in data:
        data = data["styles"][0]
    return raw, styles._style(data, path, 0)


def ground_value(style) -> float | None:
    for line in style.palette:
        if not styles._palette_role(line).startswith("GROUND"):
            continue
        found = styles._HEX.findall(line)
        if found:
            r, g, b = (int(found[0][i:i + 2], 16) / 255 for i in (0, 2, 4))
            return colorsys.rgb_to_hsv(r, g, b)[2]
    return None


def assemble(style, panel_chars: int):
    recorder = t.Recorder()
    engine = pe.PromptEngine(log=recorder)
    panel = t.czech_panel(panel_chars)
    context = t.worst_slide(style, panel, engine)
    prompt = engine.render(carousel_module.ROLE_SLIDE, context, profile=t.RENDER_PROFILE,
                           max_chars=t.body_budget())
    return prompt, recorder.trim(), context


def main(argv: list[str]) -> int:
    path = pathlib.Path(argv[1])
    raw, style = load_block(path)
    where = f"style {style.key!r} (draft)"
    bad = 0

    errors = styles._palette_findings(style, where)
    warnings = styles._style_warnings(style, where)
    print(f"== {style.key}")
    for line in errors:
        print(f"ERROR   {line}")
    for line in warnings:
        print(f"WARNING {line}")
    if not errors and not warnings:
        print("validator: clean (0 errors, 0 warnings)")
    bad += len(errors) + len(warnings)

    counter = next((z for z in style.layout_zones if z.role == "counter_slot"), None)
    guidance = style.per_format_guidance
    checks = [
        ("format_affinity includes carousel", "carousel" in style.format_affinity),
        ("no carousel_role: slides_only", "slides_only" not in " ".join(guidance.values())),
        ("brand_slot false", style.brand_slot is False),
        ("brand_affinity empty", style.brand_affinity == []),
        ("list_mode present", style.list_mode is not None),
        ("match_profile >= 8 words", len(style.match_profile.split()) >= 8),
        (f"render_prompt <= {WORDS_CAP} words ({len(style.render_prompt.split())})",
         len(style.render_prompt.split()) <= WORDS_CAP),
        ("counter_slot zone present", counter is not None),
        ("counter zone position says top-right",
         counter is not None and "top-right" in counter.position),
        (f"counter zone text_treatment <= {COUNTER_CAP} "
         f"({len(counter.text_treatment) if counter else 0})",
         counter is not None and len(counter.text_treatment) <= COUNTER_CAP),
        (f'text_placement carries "{SAFE_AREA}"', SAFE_AREA in style.text_placement),
        ("no 4:5 / bottom 12% band anywhere in the block", not CROP_BAND.search(raw)),
        ("FR-339: no chip/badge/counter/page number/signature/lockup in the three DNA fields",
         not any(GATED.search(text) for text in
                 (style.typography, style.text_placement, style.visual_pacing))),
        ("no top-left counter prose anywhere outside exclusions",
         not any(TOP_LEFT.search(text) and GATED.search(text) for text in
                 (style.render_prompt, style.typography, style.text_placement,
                  style.image_treatment, style.visual_pacing, *guidance.values()))),
        ("carousel_cover + carousel_slide guidance present",
         bool(guidance.get("carousel_cover")) and bool(guidance.get("carousel_slide"))),
        ("no -teal twin naming", not style.key.endswith("-teal")),
    ]
    gv = ground_value(style)
    if style.motion_profile == "graphic":
        checks.append((f"graphic: first GROUND hex at a value extreme (V={gv})",
                       gv is not None and (gv >= 0.85 or gv <= 0.20)))
    else:
        checks.append((f"photographic: first GROUND hex V={gv} (exempt from the extreme rule)",
                       True))
    for label, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}    {label}")
        bad += 0 if ok else 1

    # D65: `style_dna()` prepends a shared `colour_rendering` row that belongs to NO style — every
    # entry in the registry carries the identical text. Charging it to each style's own budget made
    # all 26 read FAIL against a cap written for the five DNA fields, which is a measurement fault
    # rather than an authoring one. The shared prefix is subtracted here so the number answers the
    # question the cap asks: how much DNA does THIS style own? `owned` keeps the full string,
    # because the prompt really does carry it.
    dna = pe.style_dna(style)
    shared = f"colour_rendering: {pe._COLOUR_RENDERING_ROW}\n  "
    own_dna = len(dna) - len(shared) if dna.startswith(shared) else len(dna)
    owned = (len(style.render_prompt) + len(guidance.get("carousel_slide", "")) + len(dna)
             + len("\n".join(style.exclusions))
             + (len(style.list_mode.layout) if style.list_mode else 0)
             + (len(counter.text_treatment) if counter else 0))
    for label, value, cap in (("owned chars", owned, OWNED_CAP),
                              ("style_dna chars (own)", own_dna, DNA_CAP)):
        ok = value <= cap
        print(f"{'PASS' if ok else 'FAIL'}    {label} {value:,} (cap {cap:,})")
        bad += 0 if ok else 1

    _, trim_a, _ = assemble(style, 700)
    prompt_b, _, ctx_b = assemble(style, t.PANEL_SANITY_CHARS)
    cut_a = sum(trim_a["cuts"].values())
    at = prompt_b.find(MARKER)
    slack = len(prompt_b) - (at + len(MARKER)) if at >= 0 else None
    ok_a = cut_a <= CUT_TARGET
    ok_b = slack is not None and slack >= SLACK_TARGET
    print(f"{'PASS' if ok_a else 'FAIL'}    cutA {cut_a} (ceiling {CEILING}, target <= {CUT_TARGET})")
    print(f"{'PASS' if ok_b else 'FAIL'}    markerB {at >= 0}  slackB "
          f"{'CUT' if slack is None else slack} (target >= {SLACK_TARGET})")
    print(f"        uncuttable at tier B: counter_rule {len(ctx_b['counter_rule'])}  "
          f"exclusions {len(ctx_b['exclusions'])}  list_treatment {len(ctx_b['list_treatment'])}")
    bad += (0 if ok_a else 1) + (0 if ok_b else 1)
    print(f"\n{'OK' if not bad else f'{bad} finding(s) outside target'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
