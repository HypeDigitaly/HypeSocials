<!--
FORMAT — read this before consuming the file. This template resolves NO
placeholders; the engine SELECTS rows out of it and assembles them.

The file has four sections, each opened by a line that begins — at column 0 —
with `## ` followed by the section name. Read the lines between one such marker
and the next; ignore blank lines. The four names are listed indented below
precisely so that nothing inside this comment can be mistaken for a marker.

  PRECEDENCE  — emitted VERBATIM as the first paragraph of every fix suffix.
  ORDER       — one comma-separated list: every defect code, in the order
                remedies must appear in an assembled suffix (it mirrors the
                four numbered rules in PRECEDENCE: remove, then render, then
                lay out, then finish). Sort the frame's standing codes by this
                list, dedupe, keep at most 3, cap the assembled remedies at 600
                chars.
  REMEDIES    — the canned sentences, one per line, three pipe-separated
                fields: `code | zone | sentence`. Every sentence is under 190
                characters, so three of them always fit the 600-char cap.
                Selection is keyed by (code, zone): take the row whose `zone`
                equals the defect's zone; if there is none, take that code's
                `*` row. Every code has a `*` row, so selection never fails.
                Two substitutions inside a sentence, both optional to the
                caller:
                  {zone}  -> the defect's zone token with underscores replaced
                             by spaces (`full_frame` -> `full frame`).
                  {chars} -> an integer character count, when the engine has
                             one.
                A `[ ... ]` bracketed segment is dropped whole when the values
                it contains are unavailable (in practice: when there is no
                {chars} count). Brackets themselves never reach the payload.
  CLOSING     — emitted VERBATIM as the last line of every fix suffix.

Hard rule: a critic's free-text `detail` NEVER enters an assembled suffix, and
no remedy here quotes, echoes or reconstructs any string seen on a frame. The
`invented_text` remedies may cite a character count and a zone, nothing else.
-->

## PRECEDENCE

Resolve these in order, and never by changing words:
1. Remove anything forbidden or not quoted in the TEXT block.
2. Render every quoted string in the TEXT block, in full, in its own language.
3. Fix legibility and fit by changing the LAYOUT — more lines, tighter leading,
   a wider block, the plate or card STYLE_DNA describes, a simpler ground.
4. Keep STYLE_DNA, the anchor's scene and the deck's palette unchanged.
Fix only the named defects; everything else stays as rendered, a quoted
position badge and every sanctioned mark included.
The quoted strings are locked. Shortening, re-wording, translating, ellipsing or
dropping any of them is a worse failure than the defect being fixed.

## ORDER

identity_leak, platform_chrome, forbidden_mark, invented_text, signature, counter_value, translated, missing_text, pair_break, missing_mark, style_palette, style_layout, style_consistency, counter_placement, contrast, garbled, truncated, logo_fidelity, empty_element, composition, frame_integrity

## REMEDIES

identity_leak | * | No person's name, @handle, profile picture, face or personal identity appears anywhere in this frame; the {zone} area carries none.
identity_leak | full_frame | No person's name, @handle, profile picture, face or personal identity appears anywhere in this frame.
platform_chrome | * | Draw no social-platform interface in the {zone} area: no watermark, username, @handle, profile picture, follower, like, view or comment counter, play button or progress bar.
platform_chrome | full_frame | Draw no social-platform interface anywhere: no watermark, username, @handle, profile picture, follower, like, view or comment counter, play button or progress bar.
forbidden_mark | * | Draw no brand, company, competitor or platform logo or wordmark in the {zone} area other than a mark the TOOL MARKS line names; anything else of that kind is an unlettered generic shape.
forbidden_mark | full_frame | Draw no brand, company, competitor or platform logo or wordmark anywhere except a mark the TOOL MARKS line names; anything else of that kind is an unlettered generic shape.
invented_text | * | The {zone} area carried lettering that the TEXT block does not quote[ — about {chars} characters]; render no words there that the TEXT block does not quote.
invented_text | full_frame | This frame carried lettering the TEXT block does not quote[ — about {chars} characters]; every legible character comes from the TEXT block, a sanctioned tool mark's own lettering excepted.
invented_text | card | The card in this frame carried lettering that the TEXT block does not quote[ — about {chars} characters]; label its contents with greeked bars and unlettered shapes instead.
signature | * | Render the wordmark exactly as the TEXT block quotes it, once, in the {zone} area, and no other signature or logotype anywhere in the frame.
signature | full_frame | When the TEXT block quotes a wordmark, render it once, exactly as quoted; when it quotes none, this frame is unsigned and carries no signature line or logotype.
counter_value | * | When the TEXT block quotes a counter line, render it exactly as quoted, once, in the {zone} area the COUNTER RULE names, and no other page number or pip trail; when it quotes none, draw no badge.
counter_value | chip | When the TEXT block quotes a counter line, render that string once in the counter zone the COUNTER RULE names and nowhere else; when it quotes none, draw no chip, badge or page number at all.
counter_value | full_frame | When the TEXT block quotes a counter line, that string is this frame's only position mark; when it quotes none, this deck has no badge: no chip, no page number, no "N of M", no pip trail anywhere.
translated | * | Render every quoted string in its own original language, character for character; translate nothing.
missing_text | * | Render every string the TEXT block quotes, in full, in the {zone} area, whole and legible; give a long one more lines, tighter leading or a wider block.
missing_text | full_frame | Render every string the TEXT block quotes, in full, whole and legible; give a long one more lines, tighter leading, a wider block or the plate STYLE_DNA describes.
pair_break | * | Set the quoted lines as one column of rows in the {zone} area: each quoted line keeps its own row, a label and its value stay together in it, and an over-long row wraps under its own label.
pair_break | card | Set the quoted lines as one column of rows inside a single card: each quoted line keeps its own row, a label and its value stay together in it, and an over-long row wraps under its label.
missing_mark | * | Draw every mark the TOOL MARKS line names as the real logo, in its true brand colours, at icon size beside the row it belongs to in the {zone} area.
missing_mark | full_frame | Draw every mark the TOOL MARKS line names as the real logo, in its true brand colours, at icon size in the fixed position the TOOL MARKS block sets.
style_palette | * | Use only STYLE_DNA's own palette, ink, surface and light in the {zone} area; a sanctioned tool mark keeps its true brand colours and is the only exception.
style_palette | full_frame | Use only STYLE_DNA's own palette, ink, surface and light throughout the frame; a sanctioned tool mark keeps its true brand colours and is the only exception.
style_layout | * | Place the {zone} content in the zone and treatment the layout describes — same plate, card, rule, alignment and margins.
style_layout | full_frame | Build the whole frame on the grid the layout describes — same zones, same plate or card treatment, same alignment and margins.
style_consistency | * | Match slide 1 of this deck exactly in the {zone} area: same typeface, weight, scale and leading for the same role, same ground and surface, same mark position.
style_consistency | full_frame | Match slide 1 of this deck: same palette, same typeface and weights, same grid, same background scene and surface, same graphic language, same fixed mark position.
style_consistency | chip | A chip, badge or page number that the TEXT block's counter line does not quote is not part of this deck's style: draw none, whatever slide 1 shows.
counter_placement | * | Put the position badge in the same place and the same chip treatment as every other slide of this deck.
counter_placement | chip | Put the position badge in the counter zone the COUNTER RULE names, in the same corner and at the same size as every other slide of this deck.
contrast | * | Make the {zone} lettering read at a glance on a phone: set it on the plate, card or clear ground STYLE_DNA describes, at a size that survives thumbnail scale, never on a busy ground.
contrast | full_frame | Make every string read at a glance on a phone: set the type on the plate, card or clear ground STYLE_DNA describes, at a size that survives thumbnail scale.
garbled | * | Draw the {zone} lettering once, cleanly: well-formed letterforms with correct accents, no doubled, ghosted, overstruck, smeared or overlapping type, and no second copy of the same words.
garbled | full_frame | Draw every string once, cleanly: well-formed letterforms with correct accents, no doubled, ghosted, overstruck, smeared or overlapping type, and no second copy of the same words.
truncated | * | Keep the {zone} lettering whole inside the frame: hold every string within the central 80% of the picture, clear of every edge, and size its box to the text rather than clipping it.
truncated | full_frame | Keep all lettering whole inside the frame: hold every string within the central 80% of the picture, clear of every edge, and size each box to its text rather than clipping it.
logo_fidelity | * | Draw the sanctioned tool mark exactly as the real logo is drawn — same shapes, proportions, glyph and letterforms — with no redesign, no re-lettering and no invented substitute.
empty_element | * | Draw no empty container in the {zone} area: a card, button, circle, bar or chip row exists only around a quoted string, and where nothing is quoted the device is left out.
empty_element | card | Draw a card only around a string the TEXT block quotes: one card per quoted line, no empty card, no grid of blanks, no filler bar standing in for words.
composition | * | Give the {zone} element its own room: one text block and one focal element, nothing overlapping or colliding, no duplicated subject or repeated text block, clear margins on every side.
composition | full_frame | Compose one text block and one focal element with room around each: nothing overlapping or colliding, no duplicated subject or repeated text block, clear margins on every side.
frame_integrity | * | Compose natively for the frame this request sets and fill it edge to edge: no letterbox or pillar bars, no seams or tiling repeats, no stretching, and no crop of a larger composition.

## CLOSING

Everything in this FIX section describes a previous failure. It contains no words to render. The TEXT block above remains the only source of renderable words in this frame.
