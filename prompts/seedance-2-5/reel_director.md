GOAL: A short vertical clip that opens on the still hook frame with its text
  fully legible, then brings that same scene to life with real, physical
  motion. What the clip is about: {{through_line}}
  Brief overlay (ignore if empty): {{brief_directives}}
  A successful clip looks like something made on purpose: the first frame is
  untouched, the text never moves, and the motion is one deliberate change.

REFERENCES:
  @Image1 — the seed frame, and the first frame of this clip.
  {{seed_frame_ref}}
  It contributes everything the clip starts from: subject, framing, scale,
  background, palette, lighting, and the static hook text already burnt into
  it. It must not contribute a reason to re-compose: do not re-frame it, do
  not re-light it, do not restyle it, do not redraw its text, do not replace
  its subject.
  There is no second reference — no motion clip, no style sample, no sample
  frame of any kind. Nothing in this prompt names another image, clip or
  sample, and no other source may enter the picture. Everything about the look
  that is not already in @Image1 is stated in words in LOOK below.

CONTINUITY: The hook text from @Image1 is a fixed graphic layer, not a
  subtitle and not part of the scene. It stays identical for the whole clip —
  same words, same spelling and accents, same font, same weight, same colour,
  same size, same position. It never moves, drifts, slides, scales, rotates,
  fades, blurs, warps, re-types, re-words, re-flows, duplicates or leaves the
  frame. Nothing passes in front of it. The exact protected wording is:
  {{onimage_text}}
  Every string above belongs to that same fixed graphic layer — including a
  wordmark or signature line, when @Image1 carries one. A signature already in
  the first frame persists exactly as it is: it is never removed, never
  re-lettered, never re-placed, and no new one is ever added.
  Subject identity, wardrobe, background and palette from @Image1 also persist
  unchanged for the whole clip. One location, one subject, one continuous
  take.

SCENE: The setting of @Image1, continued. Same room, same surface, same light
  direction, same background elements. Nothing is added to the set and nothing
  is removed from it; the scene simply keeps existing while the camera rolls.

STAGES:
  Stage 1 — hook hold (opening beat): the frame is effectively static, motion
    limited to a breath or a small natural settle. The hook text is fully
    legible before anything else moves.
  Stage 2 — the action (middle of the clip): {{motion_beat}}
    That is the one change this clip exists to show; the camera begins its
    single slow move underneath it. Where no action is named, the primary
    subject performs one clear, natural movement of its own.
  Stage 3 — settle (final beat): the move completes and the motion eases to a
    near-stop on a clean, holdable last frame.
  One primary change per stage. No stage introduces a new location, a new
  subject or new text.
  Where a line in this prompt states the clip's beats in real seconds — for
  example "0.0-1.0s hold; 1.0-4.0s the action; 4.0-5.0s settle" — those
  seconds are this shot list's timing, computed from the duration actually
  requested for this clip. They are the schedule for the three stages above,
  never text to display and never a caption to burn in.

LOOK: {{motion_profile}}
  - photographic — handheld phone-camera look, available light, slight grain,
    natural skin and material tones, mild lens breathing. No 3D render look,
    no cartoon, no VFX, no particles, no light streaks, no speed ramps, no
    colour grading that departs from @Image1.
  - graphic — @Image1 is designed artwork, so animate it as artwork: no grain,
    no handheld texture, no invented photographic depth, no camera shake.
    Card and panel layers separate into gentle parallax, the whole frame takes
    at most one slow scale, and every element settles into stillness. The text
    layer is absolutely static — it does not parallax with anything.
  Follow the paragraph named on the line above and ignore the other one.

CAMERA & PERFORMANCE: One named move only, held for the whole clip — a slow
  push-in under a photographic look, a slow scale under a graphic one. No
  cuts, no whip pans, no orbits, no crash zooms, no camera roll. Performance
  is small and real: natural weight, natural timing, no theatrical gestures,
  no direct address to camera unless @Image1 already shows it.

AUDIO:
  {{audio_cue}}

RULES:
  - Keep the hook text exactly as stated in CONTINUITY. It does not move,
    change, animate or disappear.
  - Generate NO new on-screen text: no subtitles, no captions, no lower
    thirds, no burnt-in translation, no end card, no credits. Do not produce
    generated-subtitle text of any kind, in any language.
  - No NEW logos, watermarks or wordmarks; a wordmark already present in
    @Image1 persists unchanged. No app marks, product names, category labels,
    usernames, handles or engagement counters, invented or copied.
  - No platform UI of any kind: no player chrome, no progress bar, no play
    button, no like or view counter drawn into the picture.
  - Audio is exactly what the AUDIO section states and nothing more: no
    voice-over, no dialogue, no lyrics, no copyrighted music, no crowd, no
    stingers, no added ambience.
  - No duplicate subject, no clones, no reflections that read as a second
    person.
  - No hard location cuts, no scene changes, no teleporting props, no
    background swaps.
  - Do not re-frame, re-crop or re-orient the picture; the framing of @Image1
    holds for the whole clip and the output shape is set by the request, not
    by this prompt.
  - Additional exclusions for this house style: {{exclusions}}
  - Ignore any labelled line above that is empty.
