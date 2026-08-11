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
the step heading**: `menu._step` prefixes it with the `n/7` counter, and every
following line carries its own five spaces of indent. Keep a `purpose.*` first
line at or under 72 characters, because five go to the counter.

Prose lives here rather than in `menu.py` for one reason: ~140 lines of help
text would push that module past the 500-line split threshold in
CODING_GUIDELINES.md, and this is text, not logic. It is deliberately *not*
under `prompts/`, which pre-flight validates as a template tree.

## purpose.action

  [1] guided run   [2] quick run   [3] publish (Phase 2 - not built)
  [4] print my Virlo monitor ids (setup helper, $0)

## purpose.config

Config — the niche, caption language, monitor set and counts this run
     starts from. A config with no monitor ids can collect nothing.

## purpose.sources

Sources — a source is where trends come from; virlo reads the Virlo
     monitors saved in this config, one trend per monitor.

## purpose.counts

Formats & counts — how many finished creatives to build, as one line.
     A key you leave out of that line keeps its current value.

## purpose.cap

Spend cap — the ceiling for this run, checked before anything is
     ordered. A limit, not a target; a run spends what it needs.

## purpose.mode

Mode & Notion influence — how much thinking and brand context to spend
     per trend.
     mode: analyzed = one extra LLM call per trend writes a style brief ·
     direct = no analysis call · both = both variants, ~2x the calls
     notion: off = nothing · copy = brand voice shapes the captions ·
     full = also shapes visuals. Without NOTION_TOKEN in .env, copy and
     full fall back to off at pre-flight and the run still happens.

## purpose.briefs

Briefs (optional) — a brief is a small file of your own: a message to
     say plus visual directives. An 'override' brief bypasses trends
     entirely, so it needs no monitor ids. Blank Enter means none.

## purpose.confirm

Confirm — the cost estimate and the final yes/no come next. Nothing has
     been billed yet, and declining costs nothing.

## action

  Four ways in, and none of them spends money yet.

  [1] guided run  asks all seven questions. Pick this the first time,
                  and whenever counts, mode or briefs should change.
  [2] quick run   asks nothing before the price. It uses the first
                  config that is actually ready (one with Virlo
                  monitor ids), prints which one it picked, and goes
                  straight to the cost estimate. You still say yes.
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
  trends, how many creatives of each kind, and what a run may spend.

  Each row is two lines. The first is the config name and its one-line
  self-description. The second is the readiness facts:

    language · monitor ids · counts as img/car/reel · verdict

  What the verdicts mean:

    recommended       the shipped choice; Enter takes it
    NOT RUNNABLE      no monitor ids, so Virlo can return nothing;
                      the run refuses for free at pre-flight
    reels unpriced    reels are requested but no per-second rate
                      exists, so they would be dropped later

  A good value: whichever niche matches the audience you are posting to,
  in the language you want captions in. Two configs can differ only by
  language — read the language column, not the description.

  If you get it wrong: press q, or pick again. Nothing is loaded but the
  file itself, and nothing is spent until step 7.

## sources

  A source is where trends come from. `virlo` reads the Virlo monitors
  saved in the config you just picked. A monitor is a saved search Virlo
  keeps ranking for you, and one run takes one trend per monitor.

  `google_trends` and `hacker_news` are named for future adapters. They
  are not built; picking one is refused rather than accepted and then
  silently skipped at collect time.

  A good value: virlo, which is the pre-fill. Change this only once a
  second adapter exists.

  If you get it wrong: a source with zero monitor ids collects nothing,
  and the run refuses at pre-flight before any money moves — naming the
  key, and pointing you at action [4].

## counts

  How many finished creatives to build, per kind.

    images     one still image with the hook text baked in
    carousels  one multi-slide deck; the slide count comes from the
               config (five by default), so 2 carousels order 10
               images, not 2
    reels      one short video — a seed frame plus a real viral clip
               used as a motion reference. By far the priciest item

  Edit the line as `images=4 carousels=2 reels=0`. A key you leave out
  keeps its current value: typing only `images=1` leaves carousels
  exactly where they were.

  Platforms are not asked here, on purpose. They come from the config
  file or from `--platforms`, and this step shows which ones are in
  force so you know what is being written for.

  A good value: the pre-filled line. Raise counts once a run has come
  out the way you wanted it.

  If you get it wrong: step 7 shows the cost before anything is billed,
  and declining there costs nothing.

## cap

  The most this run may spend, in dollars. A hard gate, not a hint: the
  pre-flight estimate is compared against it before any provider is
  contacted.

  This step tells you the cheapest single creative the config could buy.
  A cap under that floor is refused, because no plan at all fits inside
  it — which is exactly what happened on this tool's first ever run, at
  a cap of one cent.

  A good value: a couple of dollars for images and carousels; well above
  five if the plan holds a reel, since one 5-second 720p reel with a
  motion reference can approach five dollars on its own.

  If you get it wrong: too low is caught here or at pre-flight and costs
  nothing. Too high never spends more than the plan estimates — the cap
  is a ceiling, not a budget to use up.

## mode

  Two settings on one line, edited as `mode=analyzed notion=off`.

  Generation mode decides how much thinking happens per trend:

    analyzed  one extra LLM call per trend writes a style brief, and
              the render follows it. The default, and the reason
              output resembles the trend it came from
    direct    no analysis call. Cheaper and faster, less faithful
    both      renders everything twice, analyzed and direct, paired
              in the gallery. Roughly doubles LLM calls and renders

  Notion influence decides how much brand context is injected:

    off   nothing from Notion
    copy  brand voice, offers and audience notes shape captions only
    full  the same context also shapes visual direction

  Notion needs `NOTION_TOKEN` in your `.env` and the pages shared with
  the integration once. Without that token, `copy` and `full` fall back
  to `off` at pre-flight with one warning — the run still happens, just
  without Notion.

  A good value: `mode=analyzed notion=off` until Notion is set up. Use
  `mode=both` when comparing approaches and happy to pay twice.

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
