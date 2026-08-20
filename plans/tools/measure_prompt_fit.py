"""Per-style prompt-fit headroom, using tests/test_prompt_fit.py's own fixtures (no edits there).

Run from the repo root:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe <this file>

Columns:
  cutA      tier A (700-char panel): chars the last-resort trim took off the style trio.
            The ceiling is 1,600 (`_TRIO_CUT_CEILING`); target <= 1,540 (60 of slack).
  markerB   tier B (1,500-char panel): does the marker "Every legible character in this frame"
            survive the hard truncation? (`_SAFETY_RULES`, must be True)
  slackB    chars of prompt remaining AFTER the marker's last character at tier B. Negative or
            "CUT" = the marker itself was eaten. Target >= 60.
  ctr/excl/list  lengths of the three UNCUTTABLE per-style context values at tier B.
"""
import logging
import pathlib
import sys

ROOT = pathlib.Path(r"C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.CRITICAL)  # silence the prompt_hard_trimmed warnings

import test_prompt_fit as t  # noqa: E402

MARKER = "Every legible character in this frame"
CEILING = 1_600
print(f"{'style':34} {'cutA':>5} {'markerB':>7} {'slackB':>6} {'ctr':>4} {'excl':>5} {'list':>5}")
bad = 0
for key in t.STYLE_KEYS:
    _, trim_a, _, _ = t.assemble(key, 700)
    prompt_b, trim_b, ctx_b, _ = t.assemble(key, t.PANEL_SANITY_CHARS)
    cut_a = sum(trim_a["cuts"].values())
    at = prompt_b.find(MARKER)
    slack = len(prompt_b) - (at + len(MARKER)) if at >= 0 else None
    flag = ""
    if cut_a > CEILING - 60 or slack is None or slack < 60:
        flag = "  <-- over target" if (cut_a <= CEILING and slack is not None) else "  <-- FAILS TEST"
        bad += 1
    print(f"{key:34} {cut_a:>5} {str(at >= 0):>7} {('CUT' if slack is None else slack):>6} "
          f"{len(ctx_b['counter_rule']):>4} {len(ctx_b['exclusions']):>5} "
          f"{len(ctx_b['list_treatment']):>5}{flag}")
print(f"\n{bad} of {len(t.STYLE_KEYS)} styles outside target (cutA <= {CEILING - 60}, slackB >= 60)")
