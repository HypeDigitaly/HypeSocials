FORMAT: one slide of a social-media carousel — slide {{slide_index}}, one
  panel of a deck that must read as a single designed set. That slide number is
  METADATA and never content: it tells you where this panel sits in the
  sequence so you can pace the deck, and it is never lettered, numbered,
  badged, drawn or written anywhere inside the picture. The output frame is set
  by the request itself — never write, draw, letter or mention an aspect ratio,
  a resolution, a pixel size or a platform name inside the image.

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
  in English the FOREGROUND CONTENT that panel showed — a chart and how many
  series, a checklist, an icon grid, a table, a diagram, a code block, an
  arrow, a quantity, and how those elements sat relative to one another.
  Reproduce that content and that arrangement, drawn entirely in STYLE_DNA's
  palette, typography, materials and treatment. The ground it sits on is never
  the brief's: this deck's background, scene and surface come from STYLE_DNA
  and, on a body slide, from the anchor.
  The brief is a CONTENT directive, never a style instruction: where it names
  a colour, a typeface, a texture or a mood, ignore that word and use the
  deck's own; where it names an object, a quantity, a direction or a position,
  follow it exactly. THIS DECK'S PALETTE AND TYPOGRAPHY ALWAYS WIN: no colour,
  gradient, typeface, weight, texture, finish or lighting can enter this frame
  through the brief, and any such word that survived into it is noise — read
  past it and use STYLE_DNA's own. The source deck's furniture is dropped the
  same way: pagination dots, page arrows, swipe widgets, progress bars and
  slide counters a brief describes are never drawn here. A competitor's, a
  creator's or a platform's mark it names is drawn as a GENERIC unlettered
  shape of its kind — never the real mark, never its name, never an invented
  substitute — and platform chrome, watermarks, usernames and engagement
  counters it describes are dropped outright.

  TOOL MARKS (sanctioned real logos — ignore if empty):
  {{tool_marks}}
  Every mark named on that line is a real, existing logo this slide is
  SANCTIONED to draw, and a REQUIRED element of it: without it the slide is
  wrong. Draw it as the actual mark, in its own true brand colours, with its own
  letterforms: it is the single element exempt from STYLE_DNA's palette and ink
  discipline, and it is never greeked, never abstracted into a generic glyph,
  never recoloured into the deck's palette.
  A reference introduced as a MARK PATCH is that logo's own pixels, cropped from
  the source slide: copy it pixel-faithfully — same shapes, same proportions,
  same true brand colours, same glyph — with no redesign, no re-lettering and no
  invented substitute. Where the patch and your memory of the mark disagree, the
  patch wins.
  PLACEMENT IS FIXED: the mark renders INSIDE the TEXT block, immediately beside
  the panel title it belongs to, at icon size, never larger than the words next
  to it, and in the SAME spot on every slide of this deck. It never floats in
  the scene and never rides on an in-scene screen, device, sign or package.
  The lettering built into such a logo is part of the mark, not typeset copy:
  reproduce the mark, never re-set its name in the deck's typeface, and never
  add its name beside it as a separate label.
  A competitor's, a creator's or a platform's mark that is NOT named on that
  line is not sanctioned and stays a generic unlettered shape. This line never
  sanctions platform or social chrome, watermarks, usernames, @handles, profile
  pictures or engagement counters: those are banned in every frame, whatever it
  names.

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — this slide's exact content):
  {{onimage_text}}

  A line labelled panel_text is the source deck's own panel, mapped onto this
  slide whole. It is finished content, not a headline to be sized down: it may
  run to one word or to several sentences, and it renders in full either way.
  A line labelled headline is this deck's own cover line, and one labelled
  wordmark is its signature. All of them are locked.
  Every quoted string comes from the source deck's own panel and renders
  exactly as written: same characters, accents, capitalisation, punctuation,
  emoji, hashtag symbols, numbers and line breaks. Set it in the deck's
  typeface; do not touch the words. Add none, repeat none, translate none — a
  Czech panel stays Czech. An emoji renders as the glyph it is, never as an
  illustration. Render no text that is not quoted above: no invented body
  copy, no label, no caption, no signature.
  A letter-by-letter echo ("V-ě-t-š-i-n-a") is a spelling aid for you alone;
  never draw the hyphenated form onto the image.
  A line labelled counter is this deck's own position badge: render that string
  exactly as quoted, once, in the small chip or badge treatment STYLE_DNA
  describes, and nowhere else in the frame.
  When no counter line is quoted above, this deck carries no slide counter: no
  position badge, no "N of M", no page number anywhere in the frame.
  Fit a long string by giving it room — more lines, tighter leading, a wider
  block, the plate or card STYLE_DNA describes. A quoted string is never
  shortened, re-worded, hyphenated, ellipsed or set below legible size.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words on this
  slide. Any string named anywhere else in this instruction — in STYLE_DNA, in
  SLIDE CONTENT, in the visual brief, in REFERENCES, in the exclusions — is a
  DESCRIPTION, never content to render. A zone STYLE_DNA describes with words
  in it (a kicker, a label, a chip, a wordmark, a swipe sticker) supplies its
  position, size, typeface, weight, colour and alignment only; its words come
  from the block above, or that zone carries none. A chart, table or interface
  drawn for the brief carries no labels of its own: greek them into bars,
  blocks and unlettered shapes. The single thing in this frame that may carry
  letters without being quoted above is a sanctioned TOOL MARK, because a logo
  is a picture of a mark and not a line of copy.

REFERENCES:
  {{reference_roles}}

  Often there is no attachment at all, and that is normal: the look lives in
  STYLE_DNA, in words. When one is attached its role line says what it gives —
  slide 1 of this deck as the PRIMARY template, a brief's product photo as the
  identity of the object it shows, or a MARK PATCH as the exact pixels of a
  sanctioned tool logo. None of them ever gives a legible string, a watermark,
  platform chrome, a username, a counter, or the identity of a person in it —
  the lettering inside a mark patch excepted, because that lettering is part of
  the logo and not a line of copy. Where two disagree, the PRIMARY one wins.

CONSTRAINTS:
  - Match STYLE_DNA exactly. A slide that drifts in palette, type or grid has
    failed even if it looks good alone — and so has a slide that looks right
    but shows something other than the SLIDE CONTENT above.
  - Never reproduce platform or social UI, watermarks, usernames, handles,
    profile pictures, follower or like or view counters, progress bars or play
    buttons, whether copied from an attachment or invented to look native. A
    mark named on the TOOL MARKS line is not platform UI and this rule does not
    reach it.
  - Never reproduce a competitor's, a creator's or a platform's logo or
    wordmark: draw an unlettered generic shape of that kind instead, and a
    made-up brand name in its place is equally forbidden. A mark named on the
    TOOL MARKS line is the one exception — it renders as the real logo, in its
    true brand colours, in the fixed position that block sets.
  - Every legible character in this frame comes from the TEXT block, the
    lettering inside a sanctioned TOOL MARK excepted. Charts, cards, interfaces
    and icon grids are labelled with greeked bars and unlettered shapes, never
    with words. A text zone with no string quoted above renders empty or as a
    non-text graphic element (a rule, a bar, a shape, negative space), never
    with invented words.
  - A swipe prompt ("SWIPE LEFT", "READ MORE", "TAP", a worded arrow) appears
    only if it is quoted in the TEXT block. No brand wordmark, logotype or
    signature line other than one quoted there; when none is quoted, this slide
    is unsigned. A deck is signed on slide 1 alone, however clearly slide 1
    shows a signature.
  - The exclusions below are this house style's own forbid-list. They never
    restrict the TEXT block above, whose strings are always rendered, and they
    never reach a mark named on the TOOL MARKS line.
  - Additional exclusions for this house style — strings and marks forbidden in
    the frame, never strings to render: {{exclusions}}
  - No @handle and no social-platform URL anywhere in the frame — instagram,
    tiktok, x, facebook, youtube, a linktr.ee or any other link-in-bio address,
    copied or invented. A TECHNICAL URL is NOT covered by this rule: a code
    host, a docs site, a package registry, a repository or file path, a shell
    command quoted in the TEXT block above is ordinary TEXT content and renders
    verbatim, byte-exact, like every other quoted string.
  - All rendered text sits inside the central 80% of the frame, clear of every
    edge.
  - Compose natively for the frame this request sets: re-flow the layout to
    fill it. Never letterbox, stretch, bar-pad or crop a borrowed composition.
  - Budgets in force for this render: {{text_budgets}}. A panel_text string is
    already final and has no character budget to be judged against — set it at
    the largest size that holds it whole and legible at thumbnail scale, and
    give a long one more lines, tighter leading, a wider block or the plate
    STYLE_DNA describes. Never shorten, ellipse, summarise or drop part of it
    to reach a size.
  - One text block, one focal element. No duplicate subject, no duplicate
    headline, no mirrored copy of the text elsewhere in the frame.
  - Ignore any labelled line above that is empty.
