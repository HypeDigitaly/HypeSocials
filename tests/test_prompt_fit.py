"""F1-D — does a worst realistic carousel slide still FIT, style by style, in the bytes we ship?

This is the standing guarantee behind Session 5.5's F1 repair, and the only test in the suite that
deliberately pins SHIPPED bytes: it loads the real `prompts/styles.yaml`, the real
`prompts/gpt-image-2/carousel_slide.md`, the real `carousel_anchor_instruction.md` and the real
`gauntlet_fix.md`, and assembles through the real engine. Every other prompt test builds a
synthetic style so a registry edit cannot break it. This one is the opposite by design — a style
that grows its `style_dna`, a template that grows a paragraph and an anchor block that grows a
sentence are exactly the edits that put the 2026-08-14 acceptance run's decks over the provider's
wall, and nothing in the suite noticed. `test_prompts_engine.py`'s budget tests pass with the
production failure standing, because they measure a synthetic context against a synthetic limit.

**What went wrong, in one paragraph.** A carousel slide is assembled against Kie's 19,800-character
wall. The pieces that CANNOT be cut are the template's own prose, the locked TEXT block (with
FR-186's letter-by-letter echo of every accented word), the reference role lines (the ~1,400-byte
anchor instruction among them), the style's exclusions, FR-304b's list treatment and the style
trio. In the live run those summed past the wall, the assembler dropped the assembled TAIL — the
back half of CONSTRAINTS: the @handle/URL ban, the exclusions, the text budgets, the no-duplicate
rule — and the critics then judged every slide against rules the renderer had never been sent.
F1-B compressed the template, the anchor block and every `style_dna`; F1-C stopped the fix suffix
from stealing a second helping of the same budget; F1-E moved the safety rules to the TOP of
CONSTRAINTS so that whatever a truncation does eat is decorative. This file measures the result.

**The two tiers, and why there are two.** A single bar is unreachable:
`copywrite.PANEL_SANITY_CHARS` admits a mapped panel of 1,500 characters, and a 1,500-character
Czech panel plus its FR-186 echo is ~2,700 uncuttable characters of TEXT block on its own.

* **Tier A — the live-shaped worst** (~700-character panel, the re-render reference stack): the
  prompt is never HARD-TRUNCATED. Every constraint in the rulebook arrives, the panel arrives
  byte-verbatim, and the style trio's last-resort trim stays inside its own 40% floors.
* **Tier B — the sanity extreme** (a 1,500-character panel): the prompt still never exceeds the
  budget, the panel and every SAFETY rule still arrive, and what a hard truncation eats is
  confined to the droppable tail prose F1-E demoted. That is the property the reorder was for.

**RE-measured on the shipped bytes, 2026-08-21, after v2.9.0/D65 (SESSION P waves 1 and 3).**
Two edits moved every row in the table below, in opposite directions, and the second one paid for
the first:

* **Wave 1 PREPENDED FR-364's `colour_rendering` row to `style_dna`** — 251 characters of
  uncuttable-in-practice colour instruction on all twenty-six styles at once (it is trio prose, so
  the trim CAN reach it, but it sits at the head where only the hard-truncation backstop does).
  On its own that put twenty-two styles over `_TRIO_CUT_CEILING` — the worst at 2,054 — and it
  stripped the FR-340 empty-zone rule off four styles' 1,500-character panels at tier B
  (`letterpress-print-carousel` and its teal twin, `social-quote-card`, `terminal-mockup-deck`),
  which is exactly the failure mode this file was written to catch. It caught it.
* **Wave 3's empty-element purge (FR-368) took 9,146 characters back out of the registry**, and
  took them out of the prose that had gone redundant rather than out of anything the frame needs:
  the positive greeking instructions (a mock-up interior is now an allowance two styles have, not
  a registry-wide rule), the FR-340 empty-zone restatements the D61 styles each spelled out three
  or four times (`carousel_slide.md`'s CONSTRAINTS now states that rule once, to every render),
  the platform-UI and watermark exclusion lines that every render template already bans
  unconditionally in its own CONSTRAINTS block, and the cover-only hero-object paragraphs that
  `carousel_cover` guidance already carried in full.

The net is a registry that is 4.2% smaller and a worst case 24 characters BETTER than the one D61
left behind: the tightest style in the file is now `hypelead-brand-card` at 1,540, against
`icon-ledger-carousel`'s 1,516 before Wave 1 — and `icon-ledger-carousel` itself came down to
1,528. `_TRIO_CUT_CEILING` stays 1,600, untouched, with 60 characters of headroom on the worst
style. `plans/tools/measure_prompt_fit.py` reads
**`0 of 26 styles outside target (cutA <= 1540, slackB >= 60)`**, and tier B's marker survives on
all twenty-six again (the thinnest is `neon-glass-dark` at 303 characters of slack, the widest
`meme-caricature-panels-teal` at 1,049).

    style                              cut@700  cut@1500  slackB
    photoreal-ambient-caption            1,430     1,830     473
    editorial-voxel-carousel             1,487     1,742     326
    letterpress-print-carousel           1,535     1,814     351
    meme-caricature-panels                 881     1,846   1,046
    anime-noir-statement                 1,528     1,951     499
    ugc-tabletop-statement               1,468     1,815     418
    platform-showcase-card               1,532     1,792     337
    hypelead-brand-card                  1,540     1,834     371
    quiet-luxury-night-photoreal         1,518     2,006     559
    build-log-mono                       1,435     1,761     394
    icon-ledger-carousel                 1,528     1,827     373
    circuit-atlas-dark                   1,532     1,845     380
    social-quote-card                    1,521     1,769     319
    terminal-mockup-deck                 1,528     1,781     326
    letterpress-print-carousel-teal      1,535     1,814     351
    meme-caricature-panels-teal            862     1,835   1,049
    quiet-luxury-night-photoreal-teal    1,529     2,010     555
    photoreal-ambient-caption-teal       1,499     1,870     448
    ugc-tabletop-statement-teal          1,491     1,829     409
    big-number-editorial                 1,533     1,842     382
    contrast-verdict-deck                1,500     1,818     388
    photo-poster-statement               1,518     1,867     424
    mono-cutout-editorial                1,538     1,788     320
    neon-glass-dark                      1,538     1,767     303
    paper-editorial-carousel             1,527     1,807     351
    aurora-white-deck                    1,528     1,816     361

`slackB` is the characters left AFTER the every-legible-character marker at tier B — the quantity
the four Wave-1 failures had driven negative. It is measured here rather than asserted because the
assertion that matters is the marker's PRESENCE, which the tier-B test makes by name.

**The D61 table and its narrative, kept below because the reasoning still reads true.** The
absolute numbers in it are superseded by the table above; what it explains — why a safe-area
sentence or a coverage clause lands 1:1 on the trim, and why an uncuttable slot's growth always
comes out of the trio — is why the two D65 edits behaved the way they did.

**Measured on the shipped bytes, 2026-08-20, after v2.5.2/D61** (`assembled` = the filled
template before any fit pass; `cut` = the last-resort trio trim; `over` = characters hard-truncated
past the floors). D61 touched NO template, NO engine code on this path and no slot the fit pass
reads — and this time it did not re-author a single existing style either. Every one of the
nineteen rows that were already here is byte-identical to the number D60 left behind it. What
changed is that SEVEN ROWS WERE ADDED at the foot, one per style D61 appended to
`prompts/styles.yaml`, and they were measured the same way every other row was: the
parametrisation reads `STYLE_KEYS`, so a style that enters the registry enters these three tiers
with it and nobody has to remember to add it.

**Why the other nineteen rows sit where they do — D60, kept because it still reads true.** Those
numbers moved last session because `prompts/styles.yaml` was re-authored under FR-347/348/349/350,
and they moved almost entirely in one direction:

* **The safe-area sentence reached the other twelve styles.** J left "inside the central 80% of
  the 1:1 frame" on seven of the nineteen; FR-350 item 4 requires it on every carousel-affine
  style, so twelve more gained it at ~55 characters each. It lands in `text_placement`, which IS
  one of the five DNA rows, so it is CUTTABLE trio and grows tier-A cut very nearly 1:1.
* **FR-347's coverage clauses cost a few characters on eleven palette lines** across ten styles
  (`under 1/8`, `under 8%` — an accent the model is not held to spreads over the frame). Also
  `style_dna`, also charged straight against the trim.
* **The retirements paid part of it back, and paid it back unevenly.** `icon-ledger-carousel` lost
  its solid teal footer strip from `render_prompt` (-23) plus four more places that described it;
  both `letterpress` styles lost the terracotta body ground and the whole cover/body split that
  went with it; `editorial-voxel-carousel` lost the orange CONTRAST hex and its script family
  ("3 families max" -> "Two families"); `anime-noir-statement` lost the amber COUNTERLIGHT hex;
  `platform-showcase-card` gave back 12 characters of `render_prompt`.
* **Registry-wide the cuttable trio grew +947 characters** while the eight `counter_slot` slots
  grew +39 and F1-A's `{{list_treatment}}` +253 — the last two UNCUTTABLE, which is why sixteen of
  the nineteen moved further at tier A than their own trio did (the trim has to find an uncuttable
  slot's growth somewhere, and the trio is the only place it can look).

    style                              asm@700  cut@700 |  asm@1500  cut@1500  over
    photoreal-ambient-caption           20,491    1,185 |    21,898     1,727   861
    editorial-voxel-carousel            20,756    1,451 |    22,163     1,800 1,053
    letterpress-print-carousel          20,771    1,468 |    22,178     1,775 1,093
    meme-caricature-panels              19,618      314 |    21,025     1,695    20
    anime-noir-statement                20,794    1,487 |    22,201     1,992   899
    ugc-tabletop-statement              20,306    1,005 |    21,713     1,665   738
    platform-showcase-card              20,644    1,346 |    22,051     1,709 1,032
    hypelead-brand-card                 20,694    1,393 |    22,101     1,853   938
    quiet-luxury-night-photoreal        20,673    1,371 |    22,080     1,973   797
    build-log-mono                      20,741    1,445 |    22,148     1,865   973
    icon-ledger-carousel                20,816    1,516 |    22,223     1,903 1,010
    circuit-atlas-dark                  20,740    1,431 |    22,147     1,867   970
    social-quote-card                   20,699    1,394 |    22,106     1,707 1,089
    terminal-mockup-deck                20,740    1,433 |    22,147     1,761 1,076
    letterpress-print-carousel-teal     20,771    1,468 |    22,178     1,775 1,093
    meme-caricature-panels-teal         19,604      297 |    21,011     1,685    16
    quiet-luxury-night-photoreal-teal   20,681    1,381 |    22,088     1,977   801
    photoreal-ambient-caption-teal      20,556    1,251 |    21,963     1,766   887
    ugc-tabletop-statement-teal         20,329    1,036 |    21,736     1,679   747
    big-number-editorial                20,680    1,375 |    22,087     1,842   935
    contrast-verdict-deck               20,693    1,387 |    22,100     1,838   952
    photo-poster-statement              20,718    1,410 |    22,125     1,877   938
    mono-cutout-editorial               20,681    1,378 |    22,088     1,844   934
    neon-glass-dark                     20,772    1,469 |    22,179     1,854 1,015
    paper-editorial-carousel            20,706    1,402 |    22,113     1,862   941
    aurora-white-deck                   20,740    1,439 |    22,147     1,845   992

**The worst case did not change hands and did not move at all.** `icon-ledger-carousel` is still
the tightest style in the file at 1,516, exactly where D60 left it, and `anime-noir-statement` is
still the runner-up at 1,487. `_TRIO_CUT_CEILING` below therefore stays 1,600 with the same 84
characters of headroom on the worst style — thin, meant to be read that way, and the next session
that wants a paragraph should take it out of the template rather than out of this number.

**The seven newcomers landed inside the pack, which is the point.** They were authored one at a
time against `plans/tools/measure_one_style.py` rather than written first and measured afterwards,
and it shows in how narrow the band is: every one of them sits between 1,375 (`big-number-
editorial`) and 1,469 (`neon-glass-dark`) at tier A, against a registry median of 1,394. The worst
of them, `neon-glass-dark` at 1,469, is still 47 characters clear of `icon-ledger-carousel` and it
is the only newcomer inside the top five — so D61 added a quarter more styles to the registry
without moving the number this file exists to watch. `plans/tools/measure_prompt_fit.py` says the
same thing in one line: **`0 of 26 styles outside target (cutA <= 1540, slackB >= 60)`**.

**Tier B is now 26 of 26**, up from D60's 19 of 19 — every style in the registry hard-truncates on
a 1,500-character panel, and the seven newcomers went over from their first measurement rather
than crossing a line they used to be under. What matters is what the truncation EATS, and that is
unchanged: the marker assertions below still pass on every one of the twenty-six, so the panel and
every SAFETY rule still arrive and what gets dropped is the droppable tail prose F1-E demoted.
Their `over` figures (934-1,015) sit squarely inside the range the nineteen already occupied
(16-1,093), so this is a wider registry rather than a heavier one. **The five D57 variants still
track their originals** to within ~95 characters at tier A (`letterpress` 1,468 -> 1,468,
`ugc-tabletop` 1,005 -> 1,036, `photoreal-ambient` 1,185 -> 1,251, `quiet-luxury` 1,371 -> 1,381,
`meme-caricature` 314 -> 297), so the teal spine is still an accent re-role rather than a rewrite.

**The finding this table carries, stated rather than asserted away.** Session 5.5's plan expected
`chars_cut == 0` at tier A. It is not 0, and since D59 it is not 0 for ANYBODY: all TWENTY-SIX
shipped styles spend part of their style trio to fit a 700-character Czech list panel under the
full re-render reference stack. The two exceptions this file used to name are gone for the reason
in the D60 bullets above — the house-default counter line reaches the styles that never described
a counter, which is the point of FR-338 and not a regression in them.

Nothing is LOST at this tier — the trim is proportional, floored at 40%, logged as
`prompt_hard_trimmed`, and the whole rulebook survives — but the headroom F1-B was aiming for is
still not there and D59, then D60, each spent a little more of it. The template's fixed prose came
down 11,838 -> 10,576 under F1-B, went back to 10,699 under D59's empty-zone rule and is UNTOUCHED
by D60 and by D61, while F1-A's `{{list_treatment}}` slot adds 692-955 uncuttable characters on
twenty-four of the twenty-six styles — exactly the slides that were already the tightest (the
`meme-caricature` pair declare no `list_mode` and pay 0, which is most of why they sit 1,100
characters clear of everybody else; all seven D61 styles declare one and pay it). Every one of
D61's seven paid that slot from its own trio at authoring time instead of asking the file for
room, which is why the worst case is unchanged. `_TRIO_CUT_CEILING` below is where that headroom
is watched, and it is UNCHANGED at 1,600: the worst case did not move this session and there are
still 84 characters left, which is a reason to compress something, not a reason to move the bar.
Raising it is a decision about the deck's look, never a fix.

**The known limitation, past both tiers.** A PATHOLOGICAL 1,500-character panel — every single word
accented — doubles the FR-186 echo instead of adding a quarter to it, and the raw assembly runs
2.8-4.0k past the 19,800-character wall (`assembled - MAX_PROMPT_CHARS`: 2,762 for
`meme-caricature-panels-teal`, 3,974 for `icon-ledger-carousel`, with `anime-noir-statement` a
hair behind it at 3,952 — re-measurable exactly as the table above is). There the
truncation reaches THROUGH the droppable tail and into the safety rules: only the exclusions and
the @handle ban survive. That boundary is measured and pinned by the last
test in this file rather than hidden, because closing it is a change to FR-186's echo policy or to
`PANEL_SANITY_CHARS` — no style and no template has 2k to give.

**No network, no spend.** Pure string assembly over files already on disk.
"""

from __future__ import annotations

import pytest

from hypesocials import gauntlet, styles
from hypesocials import prompts_engine as pe
from hypesocials.config import BrandingConfig, TextBudgets
from hypesocials.copywrite import PANEL_SANITY_CHARS
from hypesocials.generate import carousel as carousel_module
from hypesocials.generate.refs import Reference, role_lines
from hypesocials.models import CopySet
from hypesocials.prompts_engine import PROMPTS_DIR
from hypesocials.render.profiles import MAX_PROMPT_CHARS

RENDER_PROFILE = "gpt-image-2"

#: The live-shaped worst panel. The 2026-08-14 acceptance decks mapped panels in this range; it is
#: the length a real slideshow's densest page actually carries, as opposed to the sanity fence.
LIVE_WORST_PANEL_CHARS = 700

#: The most the last-resort trim may take out of the style trio at tier A before this stops being
#: headroom and starts being a slide that renders in a different look than its neighbours. The
#: measured worst on the shipped bytes is 1,540 (`hypelead-brand-card`) after v2.9.0/D65, DOWN
#: from the 1,516 (`icon-ledger-carousel`) D60 left once Wave 1's colour row and Wave 3's registry
#: purge are both counted; the runner-up pair is `mono-cutout-editorial` and `neon-glass-dark` at
#: 1,538. The number stays 1,600 across every one of those moves — a ceiling that follows the
#: measurement is not a ceiling. D59 bought its headroom with an exclusions dedup, D60 spent a
#: little of it back on the FR-350 safe-area sentence, D65 spent 251 characters of it on the
#: FR-364 colour row and then bought 9,146 back by deleting registry prose that had gone redundant
#: (FR-368). It sits just above the worst so an edit that costs the deck another paragraph shows up
#: HERE, loudly, instead of showing up three weeks later as a blocked deck. If this trips: compress
#: the template, the anchor block or that style's `style_dna` — do not raise the number.
_TRIO_CUT_CEILING = 1_600

#: The rules F1-E moved to the TOP of CONSTRAINTS, each identified by a phrase that appears
#: nowhere else in the assembled prompt. These are the ones the 2026-08-14 run was losing to
#: truncation and judging its slides against anyway; they must survive at BOTH tiers.
_SAFETY_RULES = (
    ("the style's own exclusions", "Additional exclusions for this house style"),
    ("the @handle / social-URL ban", "No @handle and no social-platform URL"),
    ("the panel-has-no-budget rule", "already final and has no character budget"),
    ("the no-duplicate-headline rule", "No duplicate subject, no duplicate"),
    ("the platform-UI and foreign-mark ban", "Never reproduce platform or social UI"),
    ("the every-legible-character rule", "Every legible character in this frame"),
)

#: The tail F1-E demoted: real instructions, but the ones a slide can lose and still be the slide
#: that was ordered — the anchor reference carries composition and look on a body page. A hard
#: truncation is allowed to eat into these and nothing above them.
_DROPPABLE_TAIL = (
    ("the swipe-prompt rule", "A swipe prompt ("),
    ("the central-80% rule", "central 80% of the frame"),
    ("the match-STYLE_DNA rule", "Match STYLE_DNA exactly"),
    ("the compose-natively rule", "Compose natively for the frame"),
    ("the ignore-empty-lines rule", "Ignore any labelled line above that is empty"),
)

#: Every CONSTRAINTS bullet, in the order `carousel_slide.md` states them after F1-E's reorder.
#: Truncation removes a SUFFIX of the assembled string, so a prompt's surviving rules must always
#: be a PREFIX of this tuple — that equivalence is what makes "the reorder holds" checkable rather
#: than merely arguable, and it is the one assertion that stays meaningful at every panel length.
_CONSTRAINT_ORDER = (*_SAFETY_RULES, *_DROPPABLE_TAIL)

#: A Czech source panel at natural accent density — roughly one word in four carries a diacritic,
#: which is what a real Virlo panel in this language looks like. Density is the whole point of the
#: fixture: FR-186's `_spell` echo is emitted per ACCENTED word, so an all-ASCII panel would
#: measure a prompt this pipeline never assembles and an all-accented one would measure a
#: pathological string no creator writes (`test_...an_all_accented_panel...` below states where
#: that boundary sits). `_accent_density` guards the band so the fixture cannot drift either way.
_CZECH_LINES = (
    "Nastavil jsem to jednou a od té doby to běží samo.",
    "Klient platí za data, ne za hodiny strávené v tabulkách.",
    "Tady je ten rozdíl, který nikdo nahlas neřekne.",
    "První verze byla hotová za dvacet minut a stále běží.",
    "Nikdo ti neřekne, kolik práce ušetří jedna dobrá šablona.",
    "Stačí jeden krok navíc a celý proces se zrychlí o polovinu.",
)

#: D-A's sanctioned marks line at its cap — 21 real tool names is what a dense "my stack" panel
#: transcribes to, and every one of them is uncuttable prose in the assembled prompt.
_TOOL_MARKS = ", ".join((
    "Notion", "Figma", "Linear", "Claude", "Slack", "Zapier", "Airtable", "Make", "Retool",
    "Vercel", "Supabase", "Stripe", "HubSpot", "Intercom", "Loom", "Miro", "Asana", "Canva",
    "Webflow", "Framer", "Descript"))

_NICHE_WORLD = ("Ambient art direction for a Czech B2B automation studio: daylight interiors, "
                "matte paper surfaces, no stock-photo gloss, no screens showing fake dashboards, "
                "and a restrained palette that lets the typography carry the page.")

_VISUAL_BRIEF = ("The slide shows a three-step flow diagram: an inbox on the left, a processing "
                 "block in the middle and a spreadsheet on the right, joined by two arrows. The "
                 "middle block is the emphasis and carries the tool mark. No people, no hands.")


class Recorder:
    """`outputs.LogWriter`'s `.warn()`, which is the only surface the engine's fit path uses."""

    def __init__(self) -> None:
        self.data: list[tuple[str, dict[str, object]]] = []

    def warn(self, event_type: str, message: str = "", **data: object) -> None:
        self.data.append((event_type, dict(data)))

    def trim(self) -> dict[str, object]:
        """The LAST `prompt_hard_trimmed` payload, or the shape of "nothing was trimmed".

        Returning a zeroed payload rather than `None` is what lets every assertion below read the
        same three keys whether or not the last resort fired — an absent event and an event that
        cut nothing are the same fact about the prompt.
        """
        fired = [fields for event, fields in self.data if event == "prompt_hard_trimmed"]
        return fired[-1] if fired else {"chars_cut": 0, "cuts": {}, "hard_truncated": False,
                                        "final_chars": 0}


#: Loaded ONCE, at import, exactly as a run loads it — and deliberately not through a fixture: the
#: parametrisation below needs the style keys before any test executes, and a registry that cannot
#: be read is an FR-295 exit-2 fact that should stop collection rather than fail every one of
#: them.
REGISTRY = styles.load_registry([PROMPTS_DIR])
STYLE_KEYS = [style.key for style in REGISTRY.styles]


def body_budget() -> int:
    """The character room a carousel slide's BODY actually gets (F1-C), from the real accessors.

    `MAX_PROMPT_CHARS` is the provider's wall and `gauntlet.fix_reserve` is what `_prompt_cap`
    holds back from it on EVERY pass so a re-render's fix suffix rides in space that was already
    reserved. Derived here rather than written down, because a longer `gauntlet_fix.md` is an
    operator's prerogative (FR-183) and a hard-coded 18,395 would describe the sheet we happen to
    ship while silently over-stating the room an edited one leaves.
    """
    return MAX_PROMPT_CHARS - gauntlet.fix_reserve(pe.PromptEngine(log=Recorder()))


def czech_panel(length: int) -> str:
    """`length` characters of realistic Czech panel copy, cut at a word boundary."""
    lines: list[str] = []
    size = 0
    while size < length:
        line = _CZECH_LINES[len(lines) % len(_CZECH_LINES)]
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines)[:length].rsplit(" ", 1)[0]


def accent_density(text: str) -> float:
    """The share of words carrying a non-ASCII character — what FR-186's echo is billed per."""
    words = text.split()
    return sum(1 for word in words if not word.isascii()) / len(words)


def worst_slide(style, panel: str, engine: pe.PromptEngine) -> dict[str, str]:
    """The heaviest context `generate.carousel._prompt` can hand this role, for THIS style.

    Every value is the production one, taken from the production constant where there is one, so
    the fixture tracks the code instead of quoting it from memory:

    * the reference stack of a gauntlet RE-RENDER, which is the heaviest one that exists — the
      chained anchor with `carousel_anchor_instruction.md` rendered over its role line (FR-190),
      FR-323's nearest-delivered-neighbour, and two FR-315 mark patches;
    * a mapped panel that trips every shipped style's `list_mode` trigger, so `{{list_treatment}}`
      is filled (F1-A) — the slot that is uncuttable and fires on precisely the densest slides;
    * D-A's 21-mark sanctioned line and D-D's position badge — which since D59/FR-338 also fills
      `{{counter_rule}}`, straight out of `build_context` and with no stamp of its own (unlike
      `style_dna` and `render_prompt` below, `generate.carousel._prompt` passes `slide_counter`
      and takes the built value). A COUNTED deck is the heavier arm on all twenty-six shipped
      styles — every `counter_slot` zone line is longer than `_NO_COUNTER_LINE`, and the house
      line beats the empty string — so the fixture stays a strict upper bound;
    * the operator's standing art direction, FR-316's visual brief and FR-292's branding block.

    The branding block is the one deliberate overshoot: a body slide of an ANCHORED deck carries no
    signature (M12), so no live slide has both it and the anchor instruction. It is cuttable — the
    shrink pass empties it before the trio gives anything — so it raises the assembly's size
    without moving its uncuttable core, and keeping it makes this fixture a strict upper bound on
    every shape a deck can actually order.
    """
    refs = [
        Reference("https://kie.test/anchor.png", carousel_module._ANCHOR_ROLE),
        Reference("https://kie.test/slide-06.png",
                  carousel_module._NEIGHBOUR_ROLE.format(number=6)),
        Reference("https://kie.test/marks/notion.png",
                  carousel_module._MARK_PATCH_ROLE.format(name="Notion")),
        Reference("https://kie.test/marks/figma.png",
                  carousel_module._MARK_PATCH_ROLE.format(name="Figma")),
    ]
    roles = role_lines(refs)
    roles[0] = engine.render(carousel_module.ROLE_ANCHOR, {}, profile=RENDER_PROFILE)
    context = pe.build_context(
        style=style,
        copy=CopySet("0007_carousel_linkedin", "cs", slide_texts=[panel],
                     headline="Sedm nástrojů, které používá každý"),
        creative_format="carousel", text_budgets=TextBudgets(),
        slide_index="7 of 12", slide_text=panel, slide_panel_source="source panel 7 of 12",
        niche_visual_world=_NICHE_WORLD, visual_brief=_VISUAL_BRIEF,
        branding_block=pe.branding_block(
            BrandingConfig(enabled=True, brand="hypedigitaly"), style),
        reference_roles=roles, tool_marks=_TOOL_MARKS, slide_counter="07 / 12")
    # The two stamps `_Deck._prompt` makes over the built context: FR-189's one-per-deck DNA, and
    # M9's body-slide guidance appended to the style's own render prompt.
    context["style_dna"] = pe.style_dna(style)
    guidance = style.per_format_guidance.get(carousel_module.GUIDANCE_SLIDE, "").strip()
    if guidance:
        context["render_prompt"] = f"{context['render_prompt']} {guidance}".strip()
    return context


def assemble(style_key: str,
             panel_chars: int) -> tuple[str, dict[str, object], dict[str, str], str]:
    """Assemble one worst slide for `style_key`; returns (prompt, trim payload, context, panel)."""
    style = styles.style_for(REGISTRY, style_key)
    assert style is not None, f"{style_key} left the shipped registry"
    recorder = Recorder()
    engine = pe.PromptEngine(log=recorder)
    panel = czech_panel(panel_chars)
    context = worst_slide(style, panel, engine)
    prompt = engine.render(carousel_module.ROLE_SLIDE, context, profile=RENDER_PROFILE,
                           max_chars=body_budget())
    return prompt, recorder.trim(), context, panel


def surviving_rules(prompt: str) -> list[str]:
    """The CONSTRAINTS bullets this prompt still carries, in template order.

    Also enforces the ordering invariant on the way past, because it is true of every prompt this
    file assembles and there is no test that would want it false: the engine truncates the END of
    the assembled string, so the rules that survive are a PREFIX of `_CONSTRAINT_ORDER`. A gap —
    a rule present after one that is missing — means a marker phrase moved or the template's own
    order changed, and either way the F1-E ranking below it is no longer what this file claims.
    """
    present = [marker in prompt for _, marker in _CONSTRAINT_ORDER]
    assert present == sorted(present, reverse=True), \
        f"the surviving rules are not a prefix of CONSTRAINTS: {present}"
    return [name for (name, _), here in zip(_CONSTRAINT_ORDER, present) if here]


def trio_floor_room(context: dict[str, str]) -> int:
    """How many characters the trio could give before hitting `_TRIO_FLOOR` on both its slots.

    `carousel_slide.md` resolves two of the three trio names (`render_prompt`, `style_dna`); it
    names no `{{layout_zones}}`, which is the whole reason F1-A had to give the list treatment a
    slot of its own. Computed off the CONTEXT rather than off a constant, so a style with a longer
    render prompt is measured against its own floor.
    """
    return sum(int((1 - pe._TRIO_FLOOR) * len(context[name]))
               for name in ("render_prompt", "style_dna"))


# ------------------------------------------------------------------------- the fixture itself


#: The registry this file measures, in full. TWENTY-SIX since v2.5.2 (D56 added `build-log-mono`
#: plus the four census-driven archetype styles; D57 added the five `-teal` spine variants; D61
#: added the seven carousel-derived styles). The number lives here rather than inline because
#: three assertions read it and because bumping it is the deliberate act that admits a new style
#: to the measurements below — see the test.
SHIPPED_STYLES = 26


def test_the_shipped_registry_is_the_twenty_six_styles_this_file_measures() -> None:
    """A guard on the parametrisation, not on the registry: a TWENTY-SEVENTH style must be
    MEASURED, and a style silently removed must not quietly shrink this file's coverage.

    The rule this pin has always encoded is unchanged and is the reason the number is bumped rather
    than the test deleted: a style that ships without passing through the fit measurements is a
    style whose slides can blow the 19,800-character wall on a Czech list panel, and nobody would
    know until a render call returned HTTP 500. Raising the count is how a new style is ADMITTED to
    the three parametrised tiers below — the parametrisation reads `STYLE_KEYS`, so the measurement
    follows the registry automatically and this assertion is what makes that automatic step
    conscious. D61's seven were measured by that mechanism alone: nothing below was re-parametrised
    by hand, and the only edits this file took were this number, this test's name and the table in
    the module docstring.

    Three membership assertions, not one, and all three on purpose: `quiet-luxury-night-photoreal`
    is D55's entry and the tightest of the pre-D56 nine, `circuit-atlas-dark` is the densest of
    D56's archetype four (its DNA carries the diagram node cap; the greeking rule that used to sit
    beside it was retired by D65/FR-368 — an unlabelled chip is not drawn rather than barred), and
    `neon-glass-dark` is the tightest of D61's seven. A registry edit that dropped any of them
    would leave the count intact only by adding something else, which is exactly the substitution
    a bare count cannot see.
    """
    assert len(REGISTRY.styles) == SHIPPED_STYLES, STYLE_KEYS
    assert REGISTRY.origin.endswith("styles.yaml")
    assert len(set(STYLE_KEYS)) == SHIPPED_STYLES, f"duplicate style key: {STYLE_KEYS}"
    assert "quiet-luxury-night-photoreal" in STYLE_KEYS, "D55's style, measured like the rest"
    assert "circuit-atlas-dark" in STYLE_KEYS, \
        "D56's densest archetype style, measured like the rest"
    assert "neon-glass-dark" in STYLE_KEYS, "D61's tightest style, measured like the rest"


def test_the_body_budget_is_the_provider_wall_minus_this_runs_fix_reservation() -> None:
    """F1-C's arithmetic, from the accessors both halves of the code read (never a literal).

    `_prompt_cap` holds `fix_reserve` back on every pass, so THIS is the room a slide's body has —
    on its first render and on its gauntlet re-render alike. The shipped `gauntlet_fix.md` makes
    it 18,272 (Session 5.6/F7-C put the collateral-loss guard in the precedence block, which is
    emitted verbatim and therefore reserved: 1,405 -> 1,523; D59/SESSION J narrowed that guard to
    "a quoted position badge", five characters more: 1,523 -> 1,528); an operator who writes a
    longer precedence block moves it down again, and the fit assertions below move with it because
    they ask rather than assume.
    """
    reserve = gauntlet.fix_reserve(pe.PromptEngine(log=Recorder()))

    assert MAX_PROMPT_CHARS == 19_800, "the wall is 200 under Kie's measured hard limit (glz0)"
    assert 0 < reserve < MAX_PROMPT_CHARS
    assert body_budget() == MAX_PROMPT_CHARS - reserve == 18_272


def test_the_worst_case_panel_carries_czech_accents_at_a_natural_density() -> None:
    """The fixture's own calibration, asserted so it cannot drift into either useless extreme.

    Every accented WORD costs a letter-by-letter echo in the uncuttable TEXT block (FR-186), so the
    density IS the budget. Pure ASCII would measure a prompt no Czech deck assembles; every word
    accented would measure a string no creator writes — and the tests below would then be about a
    fixture rather than about the product.
    """
    panel = czech_panel(LIVE_WORST_PANEL_CHARS)

    assert 0.20 <= accent_density(panel) <= 0.40, accent_density(panel)
    assert len(panel) <= LIVE_WORST_PANEL_CHARS
    assert "\n" in panel, "a mapped panel is several lines, which is what trips `max_rows` too"


# ------------------------------------------------------------------------ tier A: the live worst


@pytest.mark.parametrize("style_key", STYLE_KEYS)
def test_a_live_shaped_worst_slide_is_never_hard_truncated_in_any_shipped_style(
    style_key: str,
) -> None:
    """TIER A. The guarantee F1 exists to hold: at the panel length a real deck actually maps,
    every shipped style assembles inside the body budget with its whole rulebook attached.

    Hard truncation is the defect, not the trim. A truncation drops the assembled TAIL blind — the
    2026-08-14 run lost the @handle ban, the exclusions, the budgets and the no-duplicate rule that
    way, then had three critics judge the result against them. The last-resort trio trim is the
    opposite: proportional, floored at 40%, announced in `prompt_hard_trimmed`, and it costs
    ELABORATION in a style instruction whose grammar is in its opening words.
    """
    prompt, trim, _, panel = assemble(style_key, LIVE_WORST_PANEL_CHARS)

    assert len(prompt) <= body_budget()
    assert trim["hard_truncated"] is False, \
        f"{style_key}: the tail of CONSTRAINTS was dropped blind — this is the F1 defect itself"
    assert surviving_rules(prompt) == [name for name, _ in _CONSTRAINT_ORDER], \
        f"{style_key}: a rule the critics judge this slide against never reached the renderer"
    assert panel in prompt, "FR-304: the mapped panel is quoted byte for byte or it is not verbatim"


@pytest.mark.parametrize("style_key", STYLE_KEYS)
def test_a_live_shaped_worst_slide_keeps_its_look_inside_the_trio_floors(style_key: str) -> None:
    """TIER A, the other half: what the trim DOES take stays inside the 40% floors and inside the
    headroom budget this file watches.

    The floor assertion is the correctness one — a trio field cut below 40% stops being a
    shortened instruction and becomes a fragment, which misleads a render model more than a
    missing block. `_TRIO_CUT_CEILING` is the WATCH: since D59 moved the counter spec into an
    uncuttable slot, ALL TWENTY-SIX shipped styles spend part of their trio here (the table in
    this module's docstring), so the day a template paragraph or a `style_dna` rewrite eats the
    rest of that room, this is where it says so.
    """
    _, trim, context, _ = assemble(style_key, LIVE_WORST_PANEL_CHARS)
    cuts: dict[str, int] = trim["cuts"]  # type: ignore[assignment]

    assert trim["chars_cut"] == sum(cuts.values())
    assert set(cuts) <= {"render_prompt", "style_dna"}, \
        "carousel_slide.md resolves two trio slots; a third means the template gained a name"
    for name, removed in cuts.items():
        assert 0 < removed <= (1 - pe._TRIO_FLOOR) * len(context[name]) + 1, \
            f"{style_key}: {name} was cut below its 40% floor"
    assert trim["chars_cut"] <= _TRIO_CUT_CEILING, (
        f"{style_key}: the last-resort trim took {trim['chars_cut']} characters of style out of a "
        f"live-shaped slide. Compress the template, the anchor block or this style's style_dna — "
        f"raising _TRIO_CUT_CEILING is a decision about the deck's look, not a fix")
    assert trim["chars_cut"] <= trio_floor_room(context)


# --------------------------------------------------------------------- tier B: the sanity extreme


@pytest.mark.parametrize("style_key", STYLE_KEYS)
def test_at_the_panel_sanity_extreme_a_truncation_can_only_eat_the_droppable_tail(
    style_key: str,
) -> None:
    """TIER B. `PANEL_SANITY_CHARS` is what `copywrite` admits, so 1,500 characters of panel is a
    shape the pipeline must survive — and at that length the uncuttable TEXT block alone is ~2,700
    characters, so ALL TWENTY-SIX shipped styles hard-truncate here (measured after v2.5.2/D61,
    which added seven that were over from their first measurement; it was nineteen of nineteen
    under D60 and seventeen of nineteen under D59, and the two that used to fit were the
    `meme-caricature-panels` pair, whose terse panel grammar is still the shortest DNA in the file
    — they now go over by 20 and 16 characters. See the table above).

    What this pins is that F1-E's reorder holds when it does. The prompt still lands inside the
    budget (never a guaranteed HTTP 500), the panel is still quoted verbatim, every SAFETY rule
    still arrives, and everything a truncation removed came from the droppable tail — the swipe
    prompt, the safe-area rule, the match-the-DNA reminder, the compose-natively line, the
    ignore-empty-lines footer. A slide that loses those still renders the job that was ordered;
    the anchor reference it carries is the deck's look (FR-241).
    """
    prompt, trim, _, panel = assemble(style_key, PANEL_SANITY_CHARS)

    assert PANEL_SANITY_CHARS == 1_500, "the fence `copywrite` admits a mapped panel under"
    assert len(prompt) <= body_budget(), "over the wall is a deterministic HTTP 500 (glz0)"
    assert panel in prompt, "FR-304 holds at the extreme too: the panel is never shortened"
    survivors = surviving_rules(prompt)
    for name, _ in _SAFETY_RULES:
        assert name in survivors, f"{style_key}: {name} was truncated away — F1-E's order failed"
    if not trim["hard_truncated"]:
        assert survivors == [name for name, _ in _CONSTRAINT_ORDER], \
            f"{style_key}: nothing was truncated, so nothing may be missing"
        return
    lost = [name for name, _ in _DROPPABLE_TAIL if name not in survivors]
    assert lost, "a truncation that removed nothing nameable means the tail markers moved"


def test_a_panel_of_nothing_but_accented_words_is_the_boundary_this_fit_does_not_cover() -> None:
    """The KNOWN LIMITATION, written down where a future reader will hit it (F1-D, Session 5.5).

    FR-186 echoes every accented word letter by letter into the TEXT block, and the TEXT block is
    uncuttable by contract. At natural Czech density (~1 word in 4) that echo costs ~600 characters
    on a 700-character panel and ~1,100 on a 1,500-character one. On a PATHOLOGICAL panel — 1,500
    characters where every single word carries a diacritic — the echo roughly doubles the panel
    instead, and the assembly runs ~2.8-4.0k past the wall: no reference stack, no style and no
    template compression closes that, because the overrun is the locked words restating themselves.

    This is asserted as a MEASUREMENT rather than as a bar to clear, and the measurement is worse
    than tier B: on `REGISTRY.styles[0]` (`photoreal-ambient-caption`, the style this test happens
    to reach for) a 2,412-character truncation eats the whole droppable tail AND reaches up into
    the safety rules — on the shipped bytes only the exclusions and the @handle/URL ban survive it,
    and seventeen of the other eighteen styles land in the same place.
    That is the honest boundary of what F1's repair covers. Two things still hold and are what
    make the case survivable rather than silent: the prompt is inside the wall (so it submits at
    all), and the loss is a clean SUFFIX of the declared order, so the two rules that outrank
    everything else are the two that live. Tightening this is a change to FR-186's echo policy
    (which F1-B already narrowed once, from every word to accented words alone) or to
    `PANEL_SANITY_CHARS` — never a change to a style or a template, neither of which has 2k to give.
    """
    accented = " ".join(["Většinář"] * 170)[:PANEL_SANITY_CHARS].rsplit(" ", 1)[0]
    style = REGISTRY.styles[0]
    recorder = Recorder()
    engine = pe.PromptEngine(log=recorder)

    prompt = engine.render(carousel_module.ROLE_SLIDE,
                           worst_slide(style, accented, engine),
                           profile=RENDER_PROFILE, max_chars=body_budget())
    trim = recorder.trim()

    assert accent_density(accented) == 1.0, "the pathological end of the band, by construction"
    assert len(prompt) <= body_budget(), "even here the engine never ships over the wall"
    assert trim["hard_truncated"] is True, \
        "if this ever goes False the echo policy improved — re-measure and re-base the docstring"
    assert accented in prompt, "the locked words are what everything else gives way to"
    # The boundary itself, pinned by NAME so a future reader sees exactly how far the loss reaches.
    assert surviving_rules(prompt) == ["the style's own exclusions", "the @handle / social-URL ban"]
