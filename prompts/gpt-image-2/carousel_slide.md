FORMAT: one slide of a social-media carousel — slide {{slide_index}}. It is
  one panel of a deck that must read as a single designed set. The output
  frame is set by the request itself — never write, draw, letter or mention an
  aspect ratio, a resolution, a pixel size or a platform name inside the
  image.

STYLE_DNA (identical on every slide of this deck — reproduce it exactly):
  {{style_dna}}

  This block is byte-for-byte the same in every slide's instruction. Treat it
  as the deck's template: same palette, same type family and weights, same
  grid, same margins, same motif, same treatment on every slide. Nothing in
  it changes because the slide index changed. Only the SLIDE CONTENT below
  differs between slides.

  BRAND INFLUENCE: {{brand_accent}}
  NICHE VISUAL WORLD (ignore if empty): {{niche_visual_world}}
  When present, that line is standing art direction ranked BELOW STYLE_DNA and
  the attached references: it biases palette, type character and motif
  vocabulary only where they leave a choice open, never layout or wording, and
  it never varies from slide to slide.

SLIDE CONTENT:
  {{render_prompt}}

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — this slide's exact content):
  {{onimage_text}}

  Render every quoted string above exactly as written: same characters, same
  accents, same capitalisation, same punctuation. Add no words. Repeat no
  words. Render no text that is not quoted above — no invented body copy, no
  invented label, no signature.
  Where a string is echoed letter by letter (for example "V-ě-t-š-i-n-a"),
  that echo is a spelling aid for you alone: use it to get every accent right
  and never draw the hyphenated form onto the image.
  If STYLE_DNA's layout includes a slide-position badge, that badge shows this
  slide's position exactly as stated in the FORMAT line above, in the badge
  style STYLE_DNA describes, and carries no other characters.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words on this
  slide (the position badge above excepted). Any string quoted or named
  anywhere else in this instruction — inside STYLE_DNA, in SLIDE CONTENT, in
  REFERENCES, in the exclusion lines — is a DESCRIPTION of what the reference
  material already contains, never content to render: do not letter it, echo it
  or translate it. A zone STYLE_DNA describes with words in it (a kicker, a
  label, a chip, a wordmark, a swipe sticker) supplies its position, size,
  typeface, weight, colour and alignment only; its words come from the block
  above, or that zone carries no words at all.

REFERENCES:
  {{reference_roles}}

  Whatever else a reference contributes, none of them ever contributes a
  legible string: not their headlines, captions or subtitles; not their brand
  wordmarks, logotypes, product names, category or section labels, button,
  chip or pill labels, kicker lines, badges or price tags; not their
  watermarks or app marks; not their usernames, handles or profile pictures;
  not their engagement counters; not their platform UI; not the identity of
  any person shown in them; not their focal subject.
  Where references disagree, follow the first one listed.

CONSTRAINTS:
  - Match STYLE_DNA exactly. A slide that drifts in palette, type or grid has
    failed even if it looks good on its own.
  - Never reproduce platform UI, watermarks, app logos, usernames, handles,
    follower or like or view counters, progress bars, play buttons, or any
    text visible in the reference images.
  - That prohibition covers brand wordmarks, logotypes, product names,
    category or section labels, button, chip or pill labels, and kicker lines
    — any legible string in a reference, whether or not it reads as design.
    A word set in the deck's own typeface is still that reference's word.
  - If STYLE_DNA or a reference has a text zone for which no string is quoted
    above, leave that zone empty or fill it with a non-text graphic element
    (a rule, a bar, a shape, negative space) — never carry the reference's
    words into it, and never invent replacement words for it. A kicker slot
    with nothing quoted for it stays wordless.
  - A navigation or swipe prompt ("SWIPE LEFT", "SWIPE RIGHT", "READ MORE",
    "TAP", an arrow or a hand carrying words) appears only if it is quoted in
    the TEXT block above; it is never carried in from a reference. No brand
    wordmark, logotype or signature line, a reference's or an invented one.
  - Additional exclusions observed in these references — these are strings
    forbidden in the frame, never strings to render: {{exclusions}}
  - All rendered text sits inside the central 80% of the frame, clear of every
    edge.
  - If the references' frame shape differs from this slide's frame, RE-COMPOSE
    the layout for this frame. Never letterbox, stretch, bar-pad or crop the
    reference composition.
  - The text above is already within the budget in force for this render:
    {{text_budgets}}
    Render it large enough to stay legible at thumbnail scale.
  - One text block, one focal element. No duplicate subject, no duplicate
    headline, no mirrored copy of the text elsewhere in the frame.
  - Ignore any labelled line above that is empty.
