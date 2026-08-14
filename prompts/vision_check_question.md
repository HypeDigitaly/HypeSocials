Inspect each attached image and answer exactly three objective questions about
it. Answer nothing else.

1. TEXT BROKEN — is any text rendered on the image garbled, misspelled,
   cut off at an edge, overlapping itself, duplicated, unreadable at small
   size, or missing/flattened accent marks (diacritics)? ILLEGIBLE text counts
   as broken even when every letterform is technically well made: lettering
   that disappears into what is behind it (dark type on a dark ground, pale
   type on a pale one, type lost inside a photograph or a busy texture) and
   lettering you cannot read at a glance are both broken text. GHOSTED,
   DOUBLE-EXPOSED or OVERSTRUCK lettering is broken text too: letterforms drawn
   twice at an offset, a faint or shadowed second copy of the same words behind
   or beside the first, doubled or double-outlined strokes, smeared or
   motion-blurred type, and words printed over other words all count — answer
   true for them even when a readable copy of the words also appears on the
   image. Judge legibility by whether the words can be READ cleanly, never by
   whether they look good.

2. FAKE PLATFORM UI — does the image contain social-media interface chrome,
   watermarks, usernames or @handles, profile pictures, follower or like or
   view or comment counters, play buttons, progress bars, or an invented app
   interface dressed up as a real one? A product, tool or company logo is NOT
   fake UI when that tool is named in the EXPECTED TEXT listed for the image,
   or when the request lists it as a sanctioned mark: a sanctioned logo beside
   a list row, on a card, in an icon grid or as an app icon is intended
   content, so answer false for it. Answer true only for the interface chrome
   above.

3. TEXT MISMATCH — do the words rendered on the image differ from the EXPECTED
   TEXT listed for that image in the user message? The expected text is the
   exact wording this image was ordered to carry. Answer true when the image
   shows different words, a paraphrase, a translation, invented extra words,
   or when part of the expected wording is missing. Answer false when every
   expected string appears on the image, same words in the same order —
   differences of capitalisation, line breaks, letter spacing, hyphenation
   and quotation marks are NOT a mismatch, and neither is text set across
   several lines or several blocks. The lettering inside a sanctioned tool
   mark — the logo's own wordmark, drawn as part of the mark — is not extra
   words and never a mismatch. A mark listed in the SANCTIONED MARKS block for
   an image is a REQUIRED element of it: when a listed mark is nowhere on the
   image, answer true and name that missing mark in the detail, spelled as the
   block spells it. An image whose expected text is listed as
   (none) is wordless by design: any readable words on it are a mismatch,
   answer true. When an image has no expected text listed for it, answer
   false — there is nothing to compare against.

Do not judge aesthetics, composition, brand fit, truthfulness, style, or
whether the image is good. Those are not defects here. An image with no text
at all is not broken text — answer false.

Return valid JSON and nothing else, one entry per attached image, in the order
the images were attached:

{
  "verdicts": [
    {
      "image": 1,
      "text_broken": false,
      "fake_ui": false,
      "text_mismatch": false,
      "detail": "<one short phrase naming the defect — the unreadable string, the missing sanctioned mark by name, the chrome you saw — or empty when all three are false>"
    }
  ]
}
