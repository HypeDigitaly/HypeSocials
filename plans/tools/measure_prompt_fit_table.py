"""Re-measure test_prompt_fit.py's tier-A/tier-B table using that module's own helpers.

Columns, defined exactly as the module defines them:
  asm  = len(engine.render(role, context, profile=...))  with NO max_chars -> the filled
         template before any fit pass (what `_fit` receives).
  cut  = trim["chars_cut"] == sum(trim["cuts"].values())  -> the last-resort trio trim.
  over = the hard truncation past the 40% floors, read off the engine's OWN
         `prompt_hard_trimmed` message ("after a hard truncation of N more characters").

Run:  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe <this file>   (cwd = the tree to measure)
"""
import logging
import pathlib
import re
import sys

ROOT = pathlib.Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.CRITICAL)

import test_prompt_fit as t  # noqa: E402
from hypesocials import prompts_engine as pe  # noqa: E402
from hypesocials import styles  # noqa: E402
from hypesocials.generate import carousel as carousel_module  # noqa: E402

_OVER = re.compile(r"after a hard truncation of (\d+) more characters")


class Loud(t.Recorder):
    """`Recorder`, but keeping the message too — `over` is only stated there."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def warn(self, event_type, message="", **data):
        super().warn(event_type, message, **data)
        self.messages.append((event_type, message))

    def over(self):
        for event, message in reversed(self.messages):
            if event == "prompt_hard_trimmed":
                hit = _OVER.search(message)
                return int(hit.group(1)) if hit else 0
        return 0


def measure(key, panel_chars):
    style = styles.style_for(t.REGISTRY, key)
    recorder = Loud()
    engine = pe.PromptEngine(log=recorder)
    panel = t.czech_panel(panel_chars)
    context = t.worst_slide(style, panel, engine)
    asm = len(engine.render(carousel_module.ROLE_SLIDE, context, profile=t.RENDER_PROFILE))
    engine.render(carousel_module.ROLE_SLIDE, context, profile=t.RENDER_PROFILE,
                  max_chars=t.body_budget())
    trim = recorder.trim()
    return asm, trim["chars_cut"], recorder.over(), trim["hard_truncated"]


print(f"    {'style':<34}{'asm@700':>8}{'cut@700':>9} | {'asm@1500':>9}{'cut@1500':>10}{'over':>6}")
worst = ("", 0)
hard_b = 0
for key in t.STYLE_KEYS:
    asm_a, cut_a, over_a, hard_a = measure(key, t.LIVE_WORST_PANEL_CHARS)
    asm_b, cut_b, over_b, hard_b_here = measure(key, t.PANEL_SANITY_CHARS)
    hard_b += 1 if hard_b_here else 0
    if cut_a > worst[1]:
        worst = (key, cut_a)
    assert over_a == 0 and not hard_a, f"{key}: tier A hard-truncated ({over_a})"
    print(f"    {key:<34}{asm_a:>8,}{cut_a:>9,} | {asm_b:>9,}{cut_b:>10,}{over_b:>6,}")
print(f"\nworst tier-A cut: {worst[0]} at {worst[1]:,} (ceiling {t._TRIO_CUT_CEILING:,})")
print(f"tier-B hard-truncating styles: {hard_b} of {len(t.STYLE_KEYS)}")
print(f"body_budget: {t.body_budget():,}  fix_reserve: "
      f"{__import__('hypesocials.gauntlet', fromlist=['x']).fix_reserve(pe.PromptEngine(log=t.Recorder())):,}")
