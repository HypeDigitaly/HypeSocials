FORMAT: one slide of a social-media carousel — slide {{slide_index}}, one
  panel of a deck that must read as a single designed set. The output frame is
  set by the request itself — never write, draw, letter or mention an aspect
  ratio, a resolution, a pixel size or a platform name inside the image.

STYLE_DNA (identical on every slide of this deck — reproduce it exactly):
  {{style_dna}}

  This block is byte-for-byte the same on every slide and it is the ONLY
  description of how this deck looks: no style photograph is attached to this
  job. Build the look from these words — palette hexes, type, placement,
  surface, light, pacing — and keep every one of them identical from slide to
  slide. Only SLIDE CONTENT and TEXT below change.

  BRANDING (ignore if empty): {{branding_block}}
  Accent colours, letterform character and a placement hint, ranked BELOW
  STYLE_DNA: substitute the accents inside the deck's own palette. They never
  replace its palette, typography, layout or medium, never vary between
  slides, and never add a word to the frame.

  NICHE VISUAL WORLD (ignore if empty): {{niche_visual_world}}
  Standing art direction, ranked BELOW STYLE_DNA: it biases palette, type
  character and motif only where they leave a choice open, never layout or
  wording.

SLIDE CONTENT — what this slide shows, composed in the style above:
  {{render_prompt}}

  SOURCE PANEL (ignore if empty): {{slide_panel_source}}
  VISUAL BRIEF (ignore if empty): {{visual_brief}}
  This deck mirrors a source slideshow one slide at a time. The line above
  names which of its panels this slide corresponds to, and the brief describes
  in English WHAT that panel showed — a chart and how many series, a
  checklist, an icon grid, a table, a diagram, a photograph, and where the
  blocks sat. Reproduce that content and that arrangement, drawn entirely in
  STYLE_DNA's palette, typography, materials and treatment.
  The brief is a CONTENT directive, never a style instruction: where it names
  a colour, a typeface, a texture or a mood, ignore that word and use the
  deck's own; where it names an object, a quantity, a direction or a position,
  follow it exactly. A company, product or app mark it names is drawn as a
  GENERIC unlettered shape of its kind — never the real mark, never its name,
  never an invented substitute — and platform chrome, watermarks, usernames
  and counters it describes are dropped outright.

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — this slide's exact content):
  {{onimage_text}}

  Every quoted string comes from the source deck's own panel and renders
  exactly as written: same characters, accents, capitalisation, punctuation,
  emoji, hashtag symbols, numbers and line breaks. Set it in the deck's
  typeface; do not touch the words. Add none, repeat none, translate none — a
  Czech panel stays Czech. An emoji renders as the glyph it is, never as an
  illustration. Render no text that is not quoted above: no invented body
  copy, no label, no caption, no signature.
  A letter-by-letter echo ("V-ě-t-š-i-n-a") is a spelling aid for you alone;
  never draw the hyphenated form onto the image.
  If STYLE_DNA's layout includes a slide-position badge, it shows this slide's
  position exactly as the FORMAT line states, in that badge style, and carries
  no other characters.
  Fit a long string by giving it room — more lines, tighter leading, a wider
  block, the plate or card STYLE_DNA describes. A quoted string is never
  shortened, re-worded, hyphenated, ellipsed or set below legible size.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words on this
  slide (the position badge excepted). Any string named anywhere else in this
  instruction — in STYLE_DNA, in SLIDE CONTENT, in the visual brief, in
  REFERENCES, in the exclusions — is a DESCRIPTION, never content to render. A
  zone STYLE_DNA describes with words in it (a kicker, a label, a chip, a
  wordmark, a swipe sticker) supplies its position, size, typeface, weight,
  colour and alignment only; its words come from the block above, or that zone
  carries none. A chart, table or interface drawn for the brief carries no
  labels of its own: greek them into bars, blocks and unlettered shapes.

REFERENCES:
  {{reference_roles}}

  Often there is no attachment at all, and that is normal: the look lives in
  STYLE_DNA, in words. When one is attached its role line says what it gives —
  slide 1 of this deck as the PRIMARY template, or a brief's product photo as
  the identity of the object it shows. None of them ever gives a legible
  string, a logo, a watermark, platform chrome, a username, a counter, or the
  identity of a person in it. Where two disagree, the PRIMARY one wins.

CONSTRAINTS:
  - Match STYLE_DNA exactly. A slide that drifts in palette, type or grid has
    failed even if it looks good alone — and so has a slide that looks right
    but shows something other than the SLIDE CONTENT above.
  - Never reproduce platform UI, watermarks, app logos, usernames, handles,
    follower or like or view counters, progress bars or play buttons, whether
    copied from an attachment or invented to look native.
  - Never reproduce a real company, product or app logo or wordmark: draw an
    unlettered generic shape of that kind instead. A made-up brand name in its
    place is equally forbidden.
  - Every legible character in this frame comes from the TEXT block. Charts,
    cards, interfaces and icon grids are labelled with greeked bars and
    unlettered shapes, never with words. A text zone with no string quoted
    above renders empty or as a non-text graphic element (a rule, a bar, a
    shape, negative space), never with invented words.
  - A swipe prompt ("SWIPE LEFT", "READ MORE", "TAP", a worded arrow) appears
    only if it is quoted in the TEXT block. No brand wordmark, logotype or
    signature line other than one quoted there; when none is quoted, this slide
    is unsigned. A deck is signed on slide 1 alone, however clearly slide 1
    shows a signature.
  - The exclusions below are this house style's own forbid-list. They never
    restrict the TEXT block above, whose strings are always rendered.
  - Additional exclusions for this house style — strings and marks forbidden in
    the frame, never strings to render: {{exclusions}}
  - No @handle and no URL anywhere in the frame.
  - All rendered text sits inside the central 80% of the frame, clear of every
    edge.
  - Compose natively for the frame this request sets: re-flow the layout to
    fill it. Never letterbox, stretch, bar-pad or crop a borrowed composition.
  - The text above is already within the budget in force for this render:
    {{text_budgets}}. Render it large enough to stay legible at thumbnail size.
  - One text block, one focal element. No duplicate subject, no duplicate
    headline, no mirrored copy of the text elsewhere in the frame.
  - Ignore any labelled line above that is empty.
