# Wizard help text

Read lazily by `menu._explain()` the first time an operator presses `?`,
and by nothing else. One `## <key>` section per help key; the key is the
one passed to `Console.prompt(..., help_key=...)`.

Body lines are printed **verbatim**, so keep every line at or under 74
characters — the engine promises no printed line exceeds 78 (FR-286), and
the slack absorbs a wide glyph. Everything above the first `## ` heading is
documentation for whoever edits this file and is never printed.

The `purpose.*` sections are the per-step purpose lines FR-284 requires, so
they are printed on every run rather than only on `?`. Their **first line is
the step heading**: `menu._step` prefixes it with an `n/N` counter DERIVED
from the step's position in `menu._live_steps()` (FR-300 — never a number
typed here or at a call site), and every following line carries its own five
spaces of indent. Keep a `purpose.*` first line at or under 72 characters,
because five go to the counter.

One section pair per live step, and the keys ARE the step names in
`menu._WIZARD_STEPS`: config, counts, copy_mode, cap, briefs, confirm — FR-56's
six operator inputs. A step deleted from that list takes its two sections with
it (v2.0.0 deleted the source picker and the mode picker this way). A step that
is only *sometimes* live keeps both sections regardless: copy_mode is skipped on
a run that plans no carousels (v2.3.0/D54/FR-333), which is a question the wizard
does not ask, not prose it stopped owning.

Prose lives here rather than in `menu.py` for one reason: a hundred-odd lines
of help text would push that module past the 500-line split threshold in
CODING_GUIDELINES.md, and this is text, not logic. It is deliberately *not*
under `prompts/`, which pre-flight validates as a template tree.

## purpose.action

  [1] guided run   [2] quick run   [3] publish (Phase 2 - not built)
  [4] print my Virlo monitor ids (setup helper, $0)

## purpose.config

Config — the niche, caption language, monitor set, brand and counts this
     run starts from. No monitor ids or no usable style: it cannot run.

## purpose.counts

Formats & counts — how many finished creatives to build, as one line.
     A key you leave out of that line keeps its current value.

## purpose.copy_mode

Carousel copy mode — the source panel's own words on our slides, only
     the panels that overflow shortened, or every panel compressed to
     the style's budget. Bound decks only.

## purpose.cap

Spend cap — the ceiling for this run, checked before anything is
     ordered. A limit, not a target; a run spends what it needs.

## purpose.briefs

Briefs (optional) — a brief is a small file of your own: a message to
     say plus visual directives. An 'override' brief bypasses trends
     entirely, so it needs no monitor ids. Blank Enter means none.

## purpose.confirm

Confirm — the cost estimate and the final yes/no come next. Nothing has
     been billed yet, and declining costs nothing.

## action

  Four ways in, and none of them spends money yet.

  [1] guided run  asks all six questions — five when the run plans no
                  carousels, since the copy-mode question is theirs
                  alone. Pick this the first time, and whenever
                  counts, copy mode, cap or briefs should change.
  [2] quick run   asks nothing before the price. It uses the first
                  config that is actually ready — Virlo monitor ids
                  AND at least one usable style — prints which one it
                  picked, and goes straight to the cost estimate. You
                  still say yes.
  [3] publish     Phase 2. Not built here. It only tells you so.
  [4] monitor ids opens Virlo, prints every monitor id and name you
                  own, then exits with no model spend.

  [4] is the fix when a config row reads NOT RUNNABLE: copy the ids you
  want into that config's `sources.virlo_monitor_ids` list.

  Never run this tool before? Press [4], paste the ids into
  configs/hypedigitaly.yaml, then come back and press [1].

## config

  A config file is one whole set of choices: which niche you speak to,
  which language captions come out in, which Virlo monitors feed the
  topics, which brand signs the posts, how many creatives of each kind,
  and what a run may spend.

  Each row is two lines. The first is the config name and its one-line
  self-description. The second is the readiness facts:

    language · monitors · counts as img/car/reel · brand · styles

  The last two are what decides whether a run can happen at all: the
  brand this config signs with, and how many of the house styles in
  prompts/styles.yaml can be used under that brand.

  What the verdicts mean:

    recommended       the shipped choice; Enter takes it
    NOT RUNNABLE      no monitor ids, so Virlo can return nothing;
                      the run refuses for free at pre-flight. With
                      '- pick [4]' the monitor-id helper cures it
    NO STYLES         the style registry will not load, or has no
                      style for a format this config asks for under
                      its brand; that is a pre-flight refusal too,
                      and it is shown here instead of three prompts
                      later. Fix prompts/styles.yaml, or the brand
    reels unpriced    reels are requested but no per-second rate
                      exists, so they would be dropped later

  A good value: whichever niche matches the audience you are posting to,
  in the language you want captions in. Two configs can differ only by
  language — read the language column, not the description.

  If you get it wrong: press q, or pick again. Nothing is loaded but the
  file itself, and nothing is spent until the confirm step.

## counts

  How many finished creatives to build, per kind.

    images     one still image with the hook text baked in
    carousels  one multi-slide deck; the slide count comes from the
               config (five by default), so 2 carousels order 10
               images, not 2
    reels      one short video — a still seed frame with the hook
               baked in, then animated. By far the priciest item

  Edit the line as `images=4 carousels=2 reels=0`. A key you leave out
  keeps its current value: typing only `images=1` leaves carousels
  exactly where they were.

  Platforms are not asked here, on purpose. They come from the config
  file or from `--platforms`, and this step shows which ones are in
  force so you know what is being written for.

  A good value: the pre-filled line. Raise counts once a run has come
  out the way you wanted it.

  If you get it wrong: the confirm step shows the cost before anything
  is billed, and declining there costs nothing.

## copy_mode

  What a carousel slide says when the deck is BOUND to a source
  slideshow — one of that post's panels per slide, in the post's own
  order.

    [1] verbatim  the panel's own words, exactly as the post wrote
                  them. Nothing is shortened, so a 1,000-character
                  panel arrives as 1,000 characters on one frame
    [2] auto      the same shortening as [3], but only for the panels
                  that are actually too long for the assigned style.
                  Every panel that already fits is quoted word for
                  word, and a deck where nothing is too long is not
                  sent to the model at all
    [3] compress  every panel, sent back to the model to come out
                  shorter: facts, numbers and tool names kept, padding
                  cut, still in the post's own language, and never
                  longer than the assigned style allows

  Auto is what the shipped configs pin, because the house styles are
  built for one bold statement per slide and a full panel buries it —
  but most panels are not the problem, and auto pays for the ones that
  are. Verbatim is the engine default and the stricter answer: it quotes
  and does nothing else. Compress is the blunt version of auto: it
  shortens every panel, including the ones that were already fine.

  Either way the deck keeps its shape — same number of slides, same
  panel in the same position, and a panel that could not be used still
  leaves its slide wordless rather than moving the others up.

  Nothing else is affected: images, reels, briefs of your own, and decks
  with no source post behind them ignore this answer entirely.

  A good value: the pre-filled one — it is this config's own setting.

  If you get it wrong: the gallery puts every slide beside the source
  panel it came from, so a deck that reads badly is visible before
  anything is published, and the next run can answer differently.

## cap

  The most this run may spend, in dollars. A hard gate, not a hint: the
  pre-flight estimate is compared against it before any provider is
  contacted.

  This step tells you the cheapest single creative the config could buy.
  A cap under that floor is refused, because no plan at all fits inside
  it — which is exactly what happened on this tool's first ever run, at
  a cap of one cent.

  A good value: a couple of dollars for images and carousels. Well above
  that if the plan holds a reel: a reel is billed per output second, at
  whatever your config's price_per_unit.reel_second says, so one clip
  can outweigh every still in the run.

  If you get it wrong: too low is caught here or at pre-flight and costs
  nothing. Too high never spends more than the plan estimates — the cap
  is a ceiling, not a budget to use up.

## briefs

  A brief is a small file of your own — a message you want said, plus
  any visual directives — living in the config's `briefs_dir` folder.
  Briefs are optional and most runs use none: blank Enter is normal.

  Pick them as `<number>:<count>`, e.g. `1:2 3:1`, or by exact name.

  Two kinds behave very differently:

    influence  rides on a real trend: the trend supplies the style,
               the brief supplies the message
    override   bypasses trends entirely. No Virlo call is needed for
               it, which is why a brief-only run works on a config
               with no monitor ids at all

  A good value: none, unless you have something specific to say.

  If you get it wrong: a brief that does not resolve is a pre-flight
  error naming the file, before any spend. An empty or missing briefs
  folder is not an error — the step reports it and moves on.
