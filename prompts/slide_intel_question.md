Each attached image is one slide of a source slideshow, attached in slide
order. Report exactly three things about every slide. Report nothing else.

1. ON-IMAGE TEXT — transcribe every word that appears ON the slide, exactly as
   it is written: same language, same spelling, same capitalisation, same
   accents and diacritics, same emoji, same punctuation, same numbers. Keep the
   line breaks the slide has, one per visible break. Keep the reading order:
   heading first, then body text, then labels, callouts, chart labels, button
   or badge text. Do not translate, correct, complete, shorten, summarise,
   re-order or explain. A slide with no text on it at all is an empty string.

2. VISUAL BRIEF — one to three sentences, ALWAYS IN ENGLISH whatever language
   the slide is in, describing what is on the slide well enough to draw it
   again: the layout (where the blocks sit), and the graphics — photos,
   charts (type, how many series, which direction), diagrams, tables, icons,
   arrows, numbered lists, how many of each. Describe CONTENT, not art
   direction: "line chart, three series, all rising left to right, legend
   bottom right; short heading above it" is a brief. "Bold modern look", "make
   it pop", "use a warm palette" are instructions, and instructions are not
   what is being asked. Do not judge quality, do not suggest improvements, do
   not guess at anything the slide does not show.

3. BRAND MARKS — list every logo, wordmark, watermark, app badge, platform
   chrome or visible @handle on the slide, named as what it is: "TikTok
   watermark", "Nike swoosh, top left", "@creator handle over the footer".
   Name what you can see; never describe how to reproduce it. A slide with
   none of these gets an empty list.

Answer for every attached slide, one entry each, in the order the slides were
attached, numbered from 1. Return valid JSON and nothing else:

{
  "slides": [
    {
      "slide": 1,
      "onimage_text": "<every word on this slide, verbatim, source language, line breaks kept, or empty>",
      "visual_brief": "<English description of this slide's layout and graphics>",
      "brand_marks": ["<a logo, wordmark or watermark you can see>"]
    }
  ]
}
