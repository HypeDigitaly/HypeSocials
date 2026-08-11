FORMAT: one single social-media post creative, rendered as a finished graphic.
  The output frame is set by the request itself — never write, draw, letter or
  mention an aspect ratio, a resolution, a pixel size or a platform name
  anywhere inside the image.

SUBJECT AND SCENE:
  {{render_prompt}}

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — this is the exact content of the creative):
  {{onimage_text}}

  Render every quoted string above exactly as written: same characters, same
  accents, same capitalisation, same punctuation. Add no words. Repeat no
  words. Invent no caption, no tagline, no label, no signature, no sticker
  text. Render no text that is not quoted above.
  Where a string is echoed letter by letter (for example "R-y-c-h-l-e-j-š-í"),
  that echo is a spelling aid for you alone: read it, use it to get every
  accent right, and never draw the hyphenated form onto the image.
  Typography, weight, case and placement come from the LAYOUT section below;
  where the two disagree about a word's case, the quoted string wins.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words. Any
  string quoted, named or spelled out anywhere else in this instruction — in
  SUBJECT AND SCENE, in LAYOUT AND STYLE, in REFERENCES, in the exclusion lines
  — is a DESCRIPTION of what the reference images already contain, never
  content to render: do not letter it, echo it, shorten it or translate it. A
  zone described with words in it (a kicker, a label, a badge, a sticker, a
  wordmark) supplies its position, size, typeface, weight, colour and alignment
  only; its words come from the block above, or that zone carries no words at
  all. A named exclusion is a forbidden string, not an instruction to draw it.

LAYOUT AND STYLE:
  {{layout_zones}}

  Reproduce these zones in the order given, top of frame to bottom. Keep the
  proportions, the margins and the text treatment of each zone. This is a
  description of STRUCTURE: reproduce each zone's geometry and typography, and
  take its words only from the TEXT block. If the target
  frame is a different shape from the reference images, RE-COMPOSE the layout
  for this frame — re-flow the zones so they fit natively. Never letterbox,
  never stretch, never bar-pad, never crop the reference composition.

  BRAND INFLUENCE: {{brand_accent}}
  NICHE VISUAL WORLD (ignore if empty): {{niche_visual_world}}
  When present, that line is standing art direction ranked BELOW the zones
  above and the attached references: it biases palette, type character and
  motif vocabulary where they leave a choice open, never layout or wording.

REFERENCES:
  {{reference_roles}}

  Every attached image is a style, layout, palette, typography and treatment
  reference ONLY. Whatever else a reference contributes, none of them ever
  contributes a legible string: not their headlines, captions or subtitles;
  not their brand wordmarks, logotypes, product names, category or section
  labels, button, chip or pill labels, kicker lines, badges or price tags; not
  their watermarks or app marks; not their usernames, handles or profile
  pictures; not their engagement counters; not their platform UI; not the
  identity of any person shown in them.
  Where two references disagree, follow the first one listed.

CONSTRAINTS:
  - Never reproduce platform UI, watermarks, app logos, usernames, handles,
    follower or like or view counters, progress bars, play buttons, or any
    text visible in the reference images.
  - That prohibition covers brand wordmarks, logotypes, product names,
    category or section labels, button, chip or pill labels, and kicker lines
    — any legible string in a reference, whether or not it reads as design.
    A word set in the template's own typeface is still that reference's word.
  - If the reference template has a text zone for which no string is quoted
    above, leave that zone empty or fill it with a non-text graphic element
    (a rule, a bar, a shape, negative space) — never carry the reference's
    words into it, and never invent replacement words for it. A kicker slot
    with nothing quoted for it stays wordless.
  - This is one standalone image: no navigation or swipe prompt of any kind
    ("SWIPE LEFT", "SWIPE RIGHT", "READ MORE", "TAP", an arrow or a hand
    carrying words), and no brand wordmark, logotype or signature line —
    neither a reference's nor an invented one. Nothing here is swiped and
    nothing here is signed.
  - Additional exclusions observed in these references — these are strings
    forbidden in the frame, never strings to render: {{exclusions}}
  - All rendered text sits inside the central 80% of the frame, clear of every
    edge, so a platform crop or a UI overlay can never amputate it.
  - The text block above is already within the budget in force for this
    render: {{text_budgets}}
    Render it at a size that stays legible at thumbnail scale; do not shrink
    type to fit extra words, because there are no extra words.
  - One text block only. No duplicate subject, no duplicate headline, no
    mirrored copy of the text elsewhere in the frame.
  - Ignore any labelled line above that is empty.
