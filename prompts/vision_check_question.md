Inspect each attached image and answer exactly two objective questions about
it. Answer nothing else.

1. TEXT BROKEN — is any text rendered on the image garbled, misspelled,
   cut off at an edge, overlapping itself, duplicated, unreadable at small
   size, or missing/flattened accent marks (diacritics)?

2. FAKE PLATFORM UI — does the image contain social-media interface chrome,
   watermarks, app logos, usernames or @handles, profile pictures, follower
   or like or view or comment counters, play buttons, or progress bars?

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
      "detail": "<one short phrase naming the defect, or empty when both are false>"
    }
  ]
}
