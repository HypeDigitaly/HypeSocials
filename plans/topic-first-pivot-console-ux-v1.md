# Console UX & Observability — Design Companion (v1, 2026-08-12)

> Companion to `plans/xmasterplan-topic-first-pivot.md` §1.10 (D45, FR-296–300).
> These are the BINDING target mockups for the conductor's W3 console wire-in, T3.1
> (previews), T3.3 (menu/cli) and T3.6 (console-inventory tests). All mockups measured
> ≤ 78 columns (FR-286 kept). No ANSI, no spinners, no `\r` — console bytes ARE run.log
> bytes (`session.say`). Safe glyphs: the `util.fit` set + `->` (never the arrow glyph).

## 1. House rules (verified against code)

1. `session.say(text)` prints AND writes identical bytes to run.log — kills spinners,
   redraws, color. (`runner.py:150-152` → `logwriter.narrative`.)
2. FR-286: every operator line ≤ 78 chars; unbreakable tokens (URLs, ids) alone on
   their own line.
3. Waves are per-creative permit priorities, not run-global barriers → ONE RENDER
   stage; `w1`/`w2` are per-job tags. CHECK is a rollup (vision check runs inside
   each creative), its elapsed prints `-`.
4. Heartbeats are SILENCE-BREAKERS, not tickers: print only when nothing has printed
   for `heartbeat_s` (30 s interactive / 90 s `--yes`; first suppressed 10 s LLM /
   20 s render). Any printed line resets the timer.
5. A number appears in exactly ONE of {stage header, table, funnel, spend row}.
6. The FR-155 funnel prints ONCE, at DONE.

## 2. Stage narration — header grammar

```
[3/9] FILTER    14 topic(s) -> 11 keep, 2 strip, 1 skip             5.2s
^1-5  ^7-14     ^17 (fit 53)                                         ^72-78 right
```

- `N` COMPUTED from the resolved plan (brief-only run: no COLLECT/TOPICS/FILTER/SELECT;
  `vision_check: false`: no CHECK). Never hardcoded.
- Every header states in -> out. Stages with waits print the header twice: an opening
  `... ` form on submit, the closing form with elapsed.

Full default-verbosity run (7 creatives, 2 monitors):

```
[1/9] COLLECT   2 monitor(s) asked -> 64 post(s), 0 failed          6.4s
[2/9] TOPICS    64 post(s) -> 14 topic(s), cap 9/monitor, 0 synth   0.1s
[3/9] FILTER    14 topic(s) -> 11 keep, 2 strip, 1 skip             5.2s
          strip  Vibe coding is over -- removed "Cursor", "Lovable"
          skip   n8n vs Make showdown -- PROMO: post sells n8n Cloud
  ... Topics table (section 3) ...
[4/9] SELECT    11 topic(s) -> 7 eligible, 3 seen lately, 1 thin    0.1s
[5/9] ASSIGN    7 creative(s) <- 5 topic(s), 6 style(s), 4 branded  0.0s
          01 image     AI agents do the work    photoreal-ambient   brand
          02 carousel  AI agents do the work    editorial-voxel     plain
          03 image     Vibe coding is over      ugc-tabletop        brand
          ... 4 more ...
[6/9] COPY      5 call(s) -> 7 creative(s) quoted verbatim         22.8s
[7/9] RENDER    11 job(s) -> 10 ok, 1 failed (7 wave-1, 4 wave-2)  3m41s
[8/9] CHECK     6 checked -> 6 pass, 0 retried, 1 not checked          -
[9/9] DONE      7 delivered, 0 skipped, $1.83 of the $2.50 cap     4m22s
```

Detail-line policy: only where a decision-with-a-cause occurred. FILTER: non-`keep`
only. ASSIGN: one line per creative (the determinism receipt). SELECT: echo
non-eligible verdicts (`<name> [excluded: used 2026-08-10]`). CHECK: failures/retries
only. COLLECT/TOPICS/COPY: header only (detail lives in table/roster/provenance).

Launch block additions (before pre-flight):

```
  styles      registry v1 · 8 styles · sha 4f9c1ab2 · 7 usable here
  branding    hypelead · brand_ratio 0.50 · overlay · bottom-center
```

Collect liveness: `collecting trends from N monitor(s)...` opener; the four virlo
`_warn` sites (monitor failed / digest failed / text-only fallback / reference
shortfall) routed through the existing `say` seam (`sources/__init__.py:117`).
One-time root-logger decision in `__main__.main` so `logger.warning` stops leaking
bare to stderr.

## 3. Topics table (once, after FILTER; shared with previews at limit=None)

```
Topics -- 14 from 2 monitor(s), sorted by strength, strongest first
  strength = 0.45 views + 0.25 median + 0.20 velocity + 0.10 engage,
  min-maxed across all 14 topics; every figure is that topic's own posts
   rk  topic                   mon  posts    views   median  strn  verdict
    1  AI agents do the work    m1      6   12.4M     1.9M  1.000  keep
    2  Vibe coding is over      m1      4    8.1M     1.7M  0.883  strip:2
    3  n8n vs Make showdown     m2      5    6.7M     980K  0.771  skip:PROMO
    4  Cursor tab is all yo...  m1      3    5.2M     1.1M  0.640  keep
   14  Weekend build log        m2      2     41K      19K  0.010  keep
  verdict  keep = usable as-is; strip:N = N competitor name(s) removed;
           skip:CODE = dropped before any spend, CODE says why
  codes    PROMO competitor promo, BLOCK blocklist hit, THIN too few posts
```

Widths: rk 3R · topic 22 (`fit()`) · mon 3 · posts 5R · views 7R · median 7R ·
strn 5 · verdict 10. Compact numbers (`12.4M`, `980K`) — never thousands separators.
The monotonically non-increasing `strn` column IS the sort proof. The caption's
"that topic's own posts" sentence is mandatory (per-topic recompute, §1.6).

## 4. Per-topic post roster (after SELECT; paid topics; top 3×3 default, verbose/preview uncapped)

```
Topic 1 -- AI agents do the work for you      m1 - strn 1.000 - keep
          posts ranked by views; "-> NN" names the creative that quoted it
          P1  @nickfloats      4.9M  2d  9f3c1a17  slideshow  -> 01
          P2  @aivideoschool   3.2M  4d  22ab04e9  video      -> 05
          P3  @promptpilot     1.9M  1d  7c10bb3d  video      unused
          https://virlo.ai/trend/9f3c1a17
```

`P1/P2/P3` are EXACTLY the §1.7 reference ordinals offered to the copy LLM — an
operator reading `headline_ref: P2.hook.1` in events.jsonl finds it here. `-> NN`
makes sibling divergence observable. Permalink alone on its own line.

## 5. Provenance block (at DONE, before the spend table)

```
Provenance -- where each delivered creative came from
   id  format    topic                 style               sig    cost  ok
   01  image     AI agents do the ...  photoreal-ambient   yes  $0.041  yes
       quoted P1 @nickfloats 4.9M 9f3c1a17 "AI agents do the work fo..."
   02  carousel  AI agents do the ...  editorial-voxel     -    $0.180  yes
       quoted P2 @aivideoschool 3.2M 22ab04e9 "Vibe coding is over, w..."
   07  reel      Cursor tab is all...  anime-noir-state..  yes  $0.425  no
       quoted P1 @promptpilot 1.9M 7c10bb3d "Cursor tab is all you n..."
       failed Seedance job timed out after 300s; seed frame kept
```

`id` = the asset id's trailing ordinal (post-pivot `…_07`); `sig` = branded yes/-
(brand itself is run-wide, shown in launch block + DONE header). Line 2 is the
verbatim receipt; line 3 appears only on loss. Exit block additions:

```
  folder    output\20260812_141207_k3xz
  gallery   output\20260812_141207_k3xz\gallery.html
```

Gallery path ALSO printed the moment the first card lands mid-run (FR-76).

## 6. Render/LLM progress

```
[7/9] RENDER    11 job(s) submitted (7 wave-1, 4 wave-2) ...
          ok      01 image     w1  job 1/1   38s  $0.030
          ok      03 image     w1  job 1/1   41s  $0.030
          render 3/11 done, 4 running (2 w1, 2 w2), 4 queued ... 2m14s
          ok      02 carousel  w2  slide 4/5 71s  $0.120  1 slide left
          failed  07 reel      w2  Seedance timed out after 300s
          render 9/11 done, 2 running (0 w1, 2 w2), 0 queued ... 3m10s
[7/9] RENDER    11 job(s) -> 10 ok, 1 failed (7 wave-1, 4 wave-2)  3m41s
```

```
[6/9] COPY      5 call(s) for 7 creative(s) ...
          copy 3/5 done, 2 in flight ... 31s
[6/9] COPY      5 call(s) -> 7 creative(s) quoted verbatim         22.8s
```

Per-job terminal lines are event-driven (`ok/failed/abandoned`; `abandoned` carries
FR-108's grace sentence). Heartbeat running/queued split reads off `RenderGate`
waiter counts. Hook: `generate/__init__.py` `_drain` loop + a `last_printed`
monotonic stamp. Kie poll ticks (`kie_job_polled`, 3 s) stay events.jsonl-only.

## 7. Verbosity scheme

New: `--verbose`/`-v` flag + `output.console_verbosity: normal | verbose` (sibling
of `log_verbosity`). New `_Session.note()` seam (~5 lines): run.log narrative
always, console only when verbose. run.log + events.jsonl are UNCHANGED by
verbosity. NO new menu prompt (NFR-16).

| Content | Console default | --verbose | run.log | events.jsonl |
|---|---|---|---|---|
| Launch/pre-flight/estimate/Confirm | yes | yes | yes | yes |
| Stage headers | yes | yes | yes | stage_complete |
| Topics table (all topics) | yes | yes | yes | topic_ranked |
| Post roster | top 3×3 | all | as console | topic_posts (all) |
| FILTER verdicts | strip+skip | + keeps + reasons | as console | all + LLM reasons |
| ASSIGN per creative | yes | + rejected candidates | yes | full trace |
| COPY per creative (refs offered/chosen) | no | yes | yes | full candidates |
| Style uploads, memo hits | no | yes | yes | per-upload event |
| Branding per-entry predicate | count in header | per-entry | per-entry | per-entry |
| Render heartbeat | 30 s | 15 s | as console | — |
| Render job terminal lines | yes | + job id + ref URLs | yes | full payload |
| Kie poll ticks, HTTP retries | no | no | digests | full |
| Full prompts/payloads | no | no | size note | whole payload |
| Actionable warnings | yes | yes | yes | yes |
| Funnel (once, DONE) | yes | yes | yes | collect_funnel |
| Spend/final/gallery path | yes | yes | yes | yes |

Default healthy-run console ≈ 100 lines; verbose ≈ 3×.

## 8. Menu re-shape (FR-300)

1. DELETE the source picker (step 2) — one real option + two always-refuse stubs.
   With the mode picker already dying: 7 inputs -> 5; NFR-16 re-enumerated once.
2. Step counters DERIVED from an ordered live-step list (literal "1/7"…"7/7" at
   seven call sites today — deleting steps otherwise breaks the count).
3. Config-picker rows: `cs · 2 mon · 4/2/1 · hypelead · 8 styles`; `_runnable()`
   extends to FR-295 → `NO STYLES` badge at pick time instead of exit-2 later.
4. Brand/ratio: display-only line (named future option: editable
   `brand=hypelead ratio=0.50` via `_parse_pairs`).
5. `_say_confirm_ahead` "8-10 minutes" re-derived (yt-dlp chain gone).
6. Keep: 4-key action choice, `?` help, one-line counts editor, fidelity rating.

## 9. New forensic events (FR-298)

- `topic_ranked` — full table rows incl. raw pre-normalization strength components.
- `topic_posts` — per topic, EVERY SourcePost `{post_id, url, author, views}` in
  rank order.
- `topic_filter_verdict` — `{ordinal, topic_key, verdict, brands_to_strip, reason}`.
- `virlo_fields` — per monitor `{fields_present, fields_consumed, fields_ignored}`.
- `stage_complete` — one per stage header.
- meta.yaml += `copy_source_refs` (`{headline: "P1.hook.2", caption: "P1.caption"}`).
- `trend_history.json` post entries gain the post URL beside the date.
