Each attached image is one slide of a source slideshow, attached in slide
order. Report exactly five things about every slide. Report nothing else.

1. ON-IMAGE TEXT — transcribe every word that appears ON the slide, exactly as
   it is written: same language, same spelling, same capitalisation, same
   accents and diacritics, same emoji, same punctuation, same numbers. Keep the
   line breaks the slide has, one per visible break. Keep the reading order:
   heading first, then body text, then labels, callouts, chart labels, button
   or badge text. Do not translate, correct, complete, shorten, summarise,
   re-order or explain. This item is the slide's OWN CONTENT ONLY: leave out
   every piece of creator chrome — @handles and account names, URLs and domains,
   watermarks and signature lines, page or slide counters like "3/6" or "2 of
   7", "swipe", "swipe up", "follow for more", "link in bio", and any platform
   interface text (like, comment, share, share counts, sound titles, usernames
   in the app frame). Those belong to item 2 and must not appear here. A slide
   whose only text is chrome has an empty string here, and so does a slide with
   no text on it at all.

2. CHROME TEXT — the words you just left out of item 1, transcribed with the
   same verbatim care: same language, same spelling, same capitalisation, same
   punctuation, line breaks kept. Every @handle, account name, URL, domain,
   watermark or signature line, page or slide counter, swipe or follow call to
   action, and every piece of platform interface text on the slide, in the
   order it appears. Do not clean it up, do not expand it, do not describe it.
   A slide with no chrome on it gets an empty string.

3. VISUAL BRIEF — one to three sentences, ALWAYS IN ENGLISH whatever language
   the slide is in, naming this slide's FOREGROUND CONTENT and nothing else.
   Foreground content is the stuff the slide puts in front of you: charts (type,
   how many series, which direction), tables, code or terminal blocks, icons,
   lists, diagrams, arrows, quantities, and the objects sitting on top of the
   slide — how many of each, and where they sit relative to one another.
   Describe CONTENT, not art direction: "line chart, three series, all rising
   left to right, legend bottom right; short heading above it" is a brief.

   NEVER describe, not in one word and not in twenty:
   - the BACKGROUND — the scenery, room, location, landscape, backdrop, set or
     photograph the content sits on. "Outdoor pool area with a log cabin
     behind it", "office desk by a window", "sunset over mountains" are
     backgrounds, and a background is never content here;
   - ANY colour, gradient, typeface, font weight, texture, lighting, finish or
     mood. "Red-to-orange gradient heading", "bold modern look", "make it pop",
     "warm palette", "clean sans-serif" are art direction, and art direction is
     never what is being asked;
   - platform chrome and interface furniture — pagination dots, page arrows,
     swipe cues, progress bars, watermarks, slide counters, like or view
     counters (item 2 already has those words);
   - creator or account names.
   A slide whose only content is a background photograph gets a MINIMAL brief
   that names the foreground elements sitting on that photograph and nothing
   about the photograph itself — or the exact phrase "no distinct foreground
   content" when there are no foreground elements at all. Do not judge quality,
   do not suggest improvements, do not guess at anything the slide does not
   show.

4. BRAND MARKS — list every logo, wordmark, watermark, app badge, platform
   chrome or visible @handle on the slide, named as what it is: "TikTok
   watermark", "Nike swoosh, top left", "@creator handle over the footer".
   Name what you can see; never describe how to reproduce it. A slide with
   none of these gets an empty list.

5. MARK BOXES — for every visible logo, wordmark or brand badge ON THIS SLIDE
   (the marks from item 4 that are a drawn mark rather than plain typed words),
   give its name, this slide's number, what KIND of mark it is, and where the
   mark sits.

   `kind` is exactly one of these four words:
   - `tool` — the logo of a piece of software, an app, a website, a model or a
     digital product: Notion, Figma, Canva, ChatGPT, CapCut, Slack, Photoshop.
     This is the kind that matters, so classify honestly: a tool logo called
     anything else is lost, and a non-tool called `tool` is drawn onto our own
     slide by mistake.
   - `apparel` — a fashion, clothing, footwear, food, drink, car or other
     physical-goods brand, wherever it appears: a swoosh on a hoodie, GAP or
     Nike across a T-shirt, a logo on a mug, a bottle, a laptop lid, a wall or
     a car. A brand worn or printed on an object is `apparel` even when the
     object is a computer.
   - `chrome` — the host platform's own interface and the creator's own
     identity: a TikTok or Instagram or YouTube watermark, a share, like,
     comment or follow glyph, an app badge, a profile picture, an @handle
     lockup, the creator's personal logo or signature mark.
   - `other` — a real mark you cannot place in the three above, or one you
     cannot identify at all. Use it freely; a guess is worse than `other`.

   One kind per mark, always filled in. If a mark could be read two ways, pick
   the one describing WHERE it is: a software logo printed on a T-shirt is
   `apparel`, a software logo shown as an app icon in a list of tools is
   `tool`.

   The position is a bounding box in FRACTIONS of the image, never pixels:
   [x, y, w, h], each
   number between 0 and 1, measured from the TOP-LEFT corner — x and w along the
   width, y and h down the height (so [0.12, 0.04, 0.09, 0.06] is a small mark
   near the top-left corner). Draw the box TIGHT around the mark itself: the
   logo only, with no surrounding label, card, button or padding. The box is the
   logo and never the panel — a rectangle covering most of the slide, a whole
   screenshot or the background is a misdetection and is thrown away. A slide
   with no logo on it at all gets an empty list, and no more than twenty-four
   marks are wanted across the whole deck — give the most prominent ones, and
   prefer a `tool` mark over any other kind when you have to choose.

Answer for every attached slide, one entry each, in the order the slides were
attached, numbered from 1. Return valid JSON and nothing else (the four numbers
below are only an example of the shape a box takes):

{
  "slides": [
    {
      "slide": 1,
      "onimage_text": "<this slide's own words, verbatim, source language, line breaks kept, no handles or URLs or counters or swipe cues, or empty>",
      "chrome_text": "<the handles, URLs, watermarks, counters and swipe or follow cues on this slide, verbatim, or empty>",
      "visual_brief": "<English description of this slide's foreground content only — no background, no colours, no typefaces, no chrome>",
      "brand_marks": ["<a logo, wordmark or watermark you can see>"],
      "mark_boxes": [
        {
          "name": "<the tool, app, brand or company this mark belongs to>",
          "slide": 1,
          "kind": "tool",
          "box": [0.12, 0.04, 0.09, 0.06]
        }
      ]
    }
  ]
}
