FORMAT: one slide of a social-media carousel — slide {{slide_index}}, one panel
  of a deck that must read as a single designed set. That number is METADATA for
  pacing, never content: it is never lettered, numbered, badged or drawn
  anywhere inside the picture. The output frame is set by the request itself —
  never write, draw, letter or mention an aspect ratio, a resolution, a pixel
  size or a platform name inside the image.

STYLE_DNA (identical on every slide of this deck — reproduce it exactly):
  {{style_dna}}

  These words are the ONLY description of how this deck looks — no style
  photograph is attached to this job. Build the look from them, and keep palette
  hexes, type, placement, surface, light and pacing identical from slide to
  slide; only the SLIDE CONTENT region and the TEXT block below change.

  BRANDING (ignore if empty): {{branding_block}}
  Accent colours, letterform character and a placement hint, ranked BELOW
  STYLE_DNA: substitute the accents inside the deck's own palette. They never
  replace its palette, typography, layout or medium, never vary between slides,
  never add a word to the frame.

  NICHE VISUAL WORLD (ignore if empty): {{niche_visual_world}}
  Standing art direction, ranked BELOW STYLE_DNA: it biases palette, type
  character and motif only where they leave a choice open, never layout or
  wording.

SLIDE CONTENT — what this slide shows, composed in the style above:
  {{render_prompt}}

  SOURCE PANEL (ignore if empty): {{slide_panel_source}}
  VISUAL BRIEF (ignore if empty): {{visual_brief}}
  This deck mirrors a source slideshow one panel at a time: the line above names
  the panel this slide takes, and the brief describes in English the FOREGROUND
  CONTENT that panel showed — charts and their series counts, checklists, icon
  grids, tables, diagrams, code blocks, arrows, quantities and how they sat
  relative to one another. Reproduce that content and that
  arrangement in STYLE_DNA's palette, typography, materials and treatment; the
  ground it sits on is never the brief's — this deck's background, scene and
  surface come from STYLE_DNA and, on a body slide, from the anchor.
  The brief is a CONTENT directive, never a style instruction: follow every
  object, quantity, direction and position it names exactly, and read past any
  colour, gradient, typeface, weight, texture, finish, lighting or mood word in
  it. THIS DECK'S PALETTE AND TYPOGRAPHY ALWAYS WIN. Source furniture the brief
  describes is never drawn here — pagination dots, page arrows, swipe widgets,
  progress bars, slide counters, platform chrome, watermarks, usernames,
  engagement counters — and a competitor's, a creator's or a platform's mark it
  names becomes a GENERIC unlettered shape of its kind: never the real mark,
  never its name, never an invented substitute.

  LIST TREATMENT (ignore if empty): {{list_treatment}}
  Words there mean this frame's text is a LIST and dictate how this style sets
  one: obey them over any other way of laying rows out, and set every row in
  full. An empty line means this frame is not a list — invent no rows, bullets
  or numbering.

  TOOL MARKS (sanctioned real logos — ignore if empty):
  {{tool_marks}}
  Every mark named there is a real logo this slide is SANCTIONED to draw and a
  REQUIRED element: without it the slide is wrong. Draw it as the actual mark,
  in its own true brand colours, with its own letterforms — the one element
  exempt from STYLE_DNA's palette and ink discipline, never greeked, never
  abstracted into a generic glyph, never recoloured. Its built-in
  lettering is part of the mark, not typeset copy: never re-set that name in the
  deck's typeface, never add it beside the mark as a label. A MARK PATCH
  reference is that logo's own pixels, cropped from the source slide: copy it
  pixel-faithfully — same shapes, proportions, colours and glyph, no redesign,
  no re-lettering, no substitute. Where it and your memory of the mark disagree,
  the patch wins.
  PLACEMENT IS FIXED: the mark renders INSIDE the TEXT block, immediately beside
  the panel title it belongs to, at icon size, never larger than the words next
  to it, in the SAME spot on every slide; it never floats in the scene and never
  rides on an in-scene screen, device, sign or package.
  A mark NOT named on that line is not sanctioned and stays a generic unlettered
  shape. That line never sanctions platform or social chrome, watermarks,
  usernames, @handles, profile pictures or engagement counters: those are banned
  in every frame, whatever it names.

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — this slide's exact content):
  {{onimage_text}}

  A line labelled panel_text is the source deck's own panel, mapped onto this
  slide whole: finished content, not a headline to be sized down — one word or
  several sentences, it renders in full either way. A line labelled headline is
  this deck's own cover line, one labelled wordmark its signature; all are
  locked.
  Every quoted string renders exactly as written — same characters, accents,
  capitalisation, punctuation, emoji, hashtag symbols, numbers and line breaks —
  set in the deck's typeface, its words untouched. Add none, repeat none,
  translate none: a Czech panel stays Czech, and an emoji renders as the glyph
  it is, never as an illustration. Render no text that is not quoted above: no
  invented body copy, label, caption or signature.
  A letter-by-letter echo of an accented word ("V-ě-t-š-i-n-a") is a spelling
  aid for you alone; never draw the hyphenated form onto the image.
  A line labelled counter is this deck's own position badge: render that string
  exactly as quoted, once, in the chip or badge treatment STYLE_DNA describes,
  and nowhere else in the frame. With no counter line quoted above,
  this deck carries no slide counter: no position badge, no "N of M", no page
  number anywhere in the frame.
  Fit a long string by giving it room — more lines, tighter leading, a wider
  block, the plate or card STYLE_DNA describes; a quoted string is never
  shortened, re-worded, hyphenated, ellipsed or set below legible size.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words on this
  slide. Any string named anywhere else — in STYLE_DNA, SLIDE CONTENT, the
  visual brief, REFERENCES, the exclusions — is a DESCRIPTION, never content to
  render. A zone STYLE_DNA describes with words in it (a kicker, a label, a
  chip, a wordmark, a swipe sticker) supplies position, size, typeface, weight,
  colour and alignment only; its words come from the block above, or that zone
  carries none. A chart, table or interface drawn for the brief carries no
  labels of its own: greek them into bars, blocks and unlettered shapes. The one
  thing that may carry letters without being quoted above is a sanctioned TOOL
  MARK.
  THIS INSTRUCTION'S OWN WORDS ARE SCAFFOLDING, NEVER CONTENT: its section
  names, its labels (panel_text, headline, wordmark, counter, kicker, body) and
  every example string it quotes to name something — a swipe prompt, a page
  number, a spelling aid, a platform address, a colour name, a hex code — are
  DESCRIPTIONS, and none of them is lettered, numbered or badged anywhere in the
  picture unless the TEXT block above quotes that exact string.

REFERENCES:
  {{reference_roles}}

  Often nothing is attached at all: the look lives in STYLE_DNA, in words. When
  one is attached its role line says what it gives — slide 1 of this deck as the
  PRIMARY template, a brief's product photo as the identity of the object it
  shows, a MARK PATCH as the exact pixels of a sanctioned tool logo. None of
  them ever gives a legible string, a watermark, platform chrome, a username, a
  counter, or the identity of a person in it — the lettering inside a mark patch
  excepted, that being part of the logo. Where two disagree, the PRIMARY wins.

CONSTRAINTS:
  - Additional exclusions for this house style — strings and marks forbidden in
    the frame, never strings to render: {{exclusions}}
    That list is this house style's own forbid-list: it never restricts the TEXT
    block above, whose strings are always rendered, and never reaches a mark
    named on the TOOL MARKS line.
  - No @handle and no social-platform URL anywhere in the frame — instagram,
    tiktok, x, facebook, youtube, a linktr.ee or any other link-in-bio address,
    copied or invented. A TECHNICAL URL is NOT covered by this rule: a code
    host, a docs site, a package registry, a repository or file path, a shell
    command quoted in the TEXT block above is ordinary TEXT content and renders
    verbatim, byte-exact.
  - Budgets in force for this render: {{text_budgets}}. A panel_text string is
    already final and has no character budget to be judged against — set it at
    the largest size that holds it whole and legible at thumbnail scale, and
    never shorten, ellipse, summarise or drop part of it to reach a size.
  - One text block, one focal element. No duplicate subject, no duplicate
    headline, no mirrored copy of the text elsewhere in the frame.
  - Never reproduce platform or social UI — watermarks, usernames, handles,
    profile pictures, follower, like or view counters, progress bars, play
    buttons — copied from an attachment or invented to look native. And never
    reproduce a competitor's, a creator's or a platform's logo or wordmark: draw
    an unlettered generic shape of that kind instead, a made-up brand name in
    its place being equally forbidden. A mark named on the TOOL MARKS line is
    the one exception to both: it is not platform UI, and it renders as the real
    logo, in its true brand colours, in the fixed position that block sets.
  - Every legible character in this frame comes from the TEXT block, the
    lettering inside a sanctioned TOOL MARK excepted: a text zone with no string
    quoted above renders empty or as a non-text graphic element (a rule, a bar,
    a shape, negative space), never with invented words.
  - A swipe prompt ("SWIPE LEFT", "TAP", a worded arrow) appears only if quoted
    in the TEXT block. No brand wordmark, logotype or signature
    line other than one quoted there; with none quoted, this slide is unsigned —
    a deck is signed on slide 1 alone, however clearly slide 1 shows one.
  - All rendered text sits inside the central 80% of the frame, clear of every
    edge.
  - Match STYLE_DNA exactly: a slide that drifts in palette, type or grid has
    failed even if it looks good alone, and so has one showing something other
    than the SLIDE CONTENT above.
  - Compose natively for the frame this request sets: re-flow the layout to fill
    it; never letterbox, stretch, bar-pad or crop a borrowed composition.
  - Ignore any labelled line above that is empty.
