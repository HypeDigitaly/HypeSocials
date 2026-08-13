FORMAT: the opening still frame of a short vertical video — a tall upright
  hook frame with the hook text already burnt into the picture. It is a
  finished image, not a storyboard and not a title card over black. The output
  frame is set by the request itself — never write, draw, letter or mention an
  aspect ratio, a resolution, a pixel size or a platform name inside the
  image.

SUBJECT AND SCENE:
  {{render_prompt}}

  That description is the whole look of this frame: no style photograph is
  attached to this job. Build the palette, the light, the surface of the
  artwork and the lettering character from those words, and compose a new
  scene in that style.

  BRIEF OVERLAY: {{brief_directives}}

TEXT (locked asset — the hook, burnt into the frame):
  {{onimage_text}}

  Render the quoted string exactly as written: same characters, same accents,
  same capitalisation, same punctuation. It is quoted from a real post and is
  never translated, re-worded or shortened. Add no words. Repeat no words.
  Render no other text anywhere in the frame — no subtitle, no caption bar, no
  watermark, no call to action, no sticker.
  Where the string is echoed letter by letter (for example "T-o-t-o"), that
  echo is a spelling aid for you alone: use it to get every accent right and
  never draw the hyphenated form onto the image.
  Set the hook as ONE static block in the upper third, on a clear background
  area, at the largest size the character count allows, with enough weight and
  contrast (or a solid backing plate) to stay readable on a phone in
  daylight. Keep it clear of the subject and clear of every frame edge.
  If the block above also quotes a wordmark, that is the frame's only other
  lettering: set it small, in one weight and one colour, at the placement the
  BRANDING line names, well clear of the hook and of the subject, flat against
  the frame like the hook itself. It is a signature, never a second headline.

  TEXT PRECEDENCE — this block is the ONLY source of renderable words. Any
  string quoted or named anywhere else in this instruction — in SUBJECT AND
  SCENE, in LAYOUT AND STYLE, in the reference roles, in the exclusion lines —
  is a DESCRIPTION of structure, never content to render: do not letter it,
  echo it or translate it. A described zone that holds words (a kicker, a
  label, a badge, a sticker, a wordmark) supplies its position, size, typeface,
  weight, colour and alignment only; here every such zone stays wordless,
  because the block above is the frame's only source of words.

LAYOUT AND STYLE:
  {{layout_zones}}

  These zones describe STRUCTURE — geometry, proportion and typography. Take
  the frame's only words from the TEXT block above; a zone the hook does not
  fill is rendered as picture, shape or negative space, never as invented
  wording.

  BRANDING (ignore if empty): {{branding_block}}
  These are accent colours, letterform character, a placement hint and colour
  guards, ranked BELOW the zones above and below the animation rules that
  follow: substitute the accents inside the style's own palette structure.
  They never replace the style's palette, typography, layout or medium, and
  they never add a word to the frame — a wordmark, when this frame carries
  one, is quoted in the TEXT block like every other string and is set as part
  of the same flat graphic layer as the hook, so the video model can hold it
  still.

  NICHE VISUAL WORLD (ignore if empty): {{niche_visual_world}}
  When present, that line is standing art direction ranked BELOW the zones
  above and the animation rules underneath: it biases palette, type character
  and motif vocabulary where they leave a choice open, never layout or wording.

BUILT TO BE ANIMATED — composition rules that outrank stylistic flourish:
  - One clear focal subject, centred or slightly low, with headroom above it
    and empty space around it for movement.
  - Nothing important touches or crosses a frame edge; no element is cut off
    by the border.
  - Background simple, continuous and extendable — a plain wall, a plain
    surface, an even gradient. No busy pattern, no crowd, no dense collage
    behind the text.
  - The text zone and the subject do not overlap and never will if the subject
    shifts slightly.
  - Sharp throughout: no motion blur, no long-exposure streaks, no lens
    flares, no heavy vignette. The video model adds motion; the frame must not
    pretend to have any.
  - Even, natural, single-source lighting that a following shot could plausibly
    continue.
  - No collage, no split screen, no picture-in-picture, no framed insets.

CONSTRAINTS:
  - Never reproduce platform UI, watermarks, app logos, usernames, handles,
    follower or like or view counters, progress bars or play buttons, whether
    copied from an attachment or invented to make the frame look native.
  - Never reproduce a real company, product or app logo, wordmark, logotype,
    product name, category or section label, button, chip or pill label or
    kicker line. Where the scene calls for a mark, draw an unlettered generic
    shape of that kind.
  - This is the first frame of one clip: no navigation or swipe prompt
    ("SWIPE LEFT", "SWIPE RIGHT", "READ MORE", "TAP", an arrow or a hand
    carrying words), and no brand wordmark, logotype or signature line other
    than one quoted in the TEXT block above; when the TEXT block quotes none,
    this frame is unsigned.
  - The exclusions below are this house style's own forbid-list. They never
    restrict the TEXT block above, whose strings are always rendered.
  - Additional exclusions for this house style — these are strings and marks
    forbidden in the frame, never strings to render: {{exclusions}}
  - Attachments, in the order attached (this job usually has none — the style
    above is written, not photographed):
    {{reference_roles}}
    An attachment here is a brief's own product photo: it gives the identity of
    the object it shows and nothing else — never its background, its lighting,
    its layout, its text, wordmarks, logos, chrome, counters, or the identity
    of anyone in it.
  - The hook sits inside the central 80% of the frame, well clear of the top
    and bottom bands where a player's controls and captions land.
  - The hook is already within the budget in force for this render:
    {{text_budgets}}
    It is read at thumb size on a phone — render it big.
  - Compose natively for the upright frame this request sets: re-flow the
    layout so it fills the frame. Never letterbox, stretch, bar-pad or crop.
  - Ignore any labelled line above that is empty.
