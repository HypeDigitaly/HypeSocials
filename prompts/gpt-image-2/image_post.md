FORMAT: one single social-media post creative, rendered as a finished graphic.
  The output frame is set by the request itself — never write, draw, letter or
  mention an aspect ratio, a resolution, a pixel size or a platform name
  anywhere inside the image.

SUBJECT AND SCENE:
  {{content_sentence}}
  {{render_prompt}}

  The STYLE line fixes how this frame looks. The SUBJECT line fixes what it is
  about. Where the style fixes a scene, the subject enters through the props,
  the artwork on surfaces, the annotation graphics and the words in the TEXT
  block — never by replacing the scene, the setting or the palette. Where the
  style leaves the scene open, build it around the subject.

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — this is the exact content of the creative):
  {{onimage_text}}

  Render every quoted string above exactly as written: same characters, same
  accents, same capitalisation, same punctuation. The string is quoted from a
  real post and is never translated, re-worded, shortened or "corrected". Add
  no words. Repeat no words. Invent no caption, no tagline, no label, no
  signature, no sticker text. Render no text that is not quoted above.
  Where a word is echoed letter by letter (for example "R-y-c-h-l-e-j-š-í"),
  that echo is a spelling aid for you alone: read it, use it to get every
  accent right, and never draw the hyphenated form onto the image.
  Typography, weight, case and placement come from the LAYOUT AND STYLE
  section below; where the two disagree about a word's case, the quoted string
  wins.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words. Any
  string quoted, named or spelled out anywhere else in this instruction — in
  SUBJECT AND SCENE, in LAYOUT AND STYLE, in REFERENCES, in the exclusion
  lines — is a DESCRIPTION of structure, never content to render: do not letter
  it, echo it, shorten it or translate it. A zone described with words in it (a
  kicker, a label, a badge, a sticker, a wordmark) supplies its position, size,
  typeface, weight, colour and alignment only; its words come from the block
  above, or that zone carries no words at all. A named exclusion is a forbidden
  string, not an instruction to draw it.

LAYOUT AND STYLE:
  {{layout_zones}}

  Reproduce these zones in the order given, top of frame to bottom. Keep the
  proportions, the margins and the text treatment of each zone. This is a
  description of STRUCTURE: reproduce each zone's geometry and typography, and
  take its words only from the TEXT block.

  The style description above and these zones are the WHOLE look: no style
  photograph is attached to this job. Build the palette, the grid, the
  lettering character and weight, the surface and lighting of the artwork and
  the spacing rhythm from those words alone, and make a NEW creative in that
  style about the subject above. Where no zones are listed, compose the frame
  yourself from the style description.
  Compose natively for the frame this request sets: re-flow the zones so they
  fill it. Never letterbox, never stretch, never bar-pad, never crop.

  BRANDING (ignore if empty): {{branding_block}}
  These are accent colours, letterform character, a placement hint and colour
  guards, ranked BELOW the style above: substitute the accents inside the
  style's own palette structure and sign the frame where the hint says. They
  never replace the style's palette, its typography, its layout or its medium,
  and they never add a word to the frame — the wordmark, if this creative
  carries one, is quoted in the TEXT block like every other string.

  NICHE VISUAL WORLD (ignore if empty): {{niche_visual_world}}
  When present, that line is standing art direction ranked BELOW the zones
  above: it biases palette, type character and motif vocabulary where they
  leave a choice open, never layout or wording.

REFERENCES:
  {{reference_roles}}

  This job usually carries no attached image at all, and that is correct: the
  look comes from the written style above. When an image IS attached it is a
  campaign brief's own product photo, and the line naming it says so. Such a
  photo gives the identity of the object it shows — shape, colour, finish,
  proportions — and nothing else: not its background, not its lighting, not its
  layout, and never a legible string, wordmark, logo, watermark, label, price
  tag, username, counter, platform UI, or the identity of a person in it.
  Where two attachments disagree, follow the first one listed.

CONSTRAINTS:
  - The ONLY text anywhere in this image is the quoted string or strings in
    the TEXT block above. Every other legible character in the frame is a
    defect, no matter how well it fits the design.
  - Never reproduce platform UI, watermarks, app logos, usernames, handles,
    follower or like or view counters, progress bars or play buttons, whether
    copied from an attachment or invented to make the frame look native.
  - Never reproduce a real company, product or app logo, wordmark, logotype,
    product name, category or section label, button, chip or pill label or
    kicker line. Where the design calls for a mark, draw an unlettered generic
    shape of that kind; a made-up brand name in its place is equally forbidden.
  - A text zone with no string quoted above is left out of the frame — never
    filled with invented words, and never with a bar, rule, block or
    placeholder standing in for words. A repeating device (a row, a card, a
    chip) exists once per quoted line and not at all when none is quoted. A
    kicker slot with nothing quoted for it stays wordless. An interface, chart
    or label group drawn for this frame is greeked into bars and unlettered
    shapes.
  - Every icon, glyph or pictogram depicts what the line beside it says, and
    nothing else. An icon picked for decoration, for rhythm or to fill a slot
    is a defect; a line with nothing depictable in it gets no icon at all.
  - Never invent a human face. Where a real person was shown or named and no
    attached reference supplies them, draw a non-human glyph or leave that
    element out entirely — a synthesized face is a stranger presented as real.
  - A negative marker — an X, a cross, a strike, a "loses" or "before" mark —
    is never drawn in the positive accent colour. Set it in a muted or
    neutral tone: the accent marks what the frame is FOR.
  - This is one standalone image: no navigation or swipe prompt of any kind
    ("SWIPE LEFT", "SWIPE RIGHT", "READ MORE", "TAP", an arrow or a hand
    carrying words), and no brand wordmark, logotype or signature line other
    than one quoted in the TEXT block above; when the TEXT block quotes none,
    this frame is unsigned. Nothing here is swiped.
  - No @handle, no social-platform URL, no emoji in the frame — not in the
    text block, not on a prop, not in a corner, not as decoration. A technical
    URL (code host, docs site, package registry) quoted in the TEXT block is
    content and renders verbatim, byte-exact.
  - The exclusions below are this house style's own forbid-list. They never
    restrict the TEXT block above, whose strings are always rendered.
  - Additional exclusions for this house style — these are strings and marks
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
