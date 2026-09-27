---
name: filing-room
description: A research tool where every answer sits beside its source filing.
colors:
  paper: "#ffffff"
  paper-subtle: "#f6f7f9"
  paper-hover: "#eef1f5"
  filing-paper: "#fafbfc"
  hairline: "#e3e6eb"
  hairline-strong: "#cdd2da"
  graphite-ink: "#15181e"
  graphite-2: "#444c5a"
  graphite-3: "#636b79"
  ocean: "#1b5e8c"
  ocean-deep: "#154a6f"
  ocean-wash: "#e9f1f8"
  ocean-wash-strong: "#cfe1ef"
  marker: "#ffe98a"
  marker-strong: "#ffd23f"
  marker-row: "#fff0b3"
  verified-green: "#1d7a4c"
  verified-green-wash: "#e7f4ec"
  caution-amber: "#a8510a"
  caution-amber-wash: "#fdf1e4"
  error-red: "#b42318"
  error-red-wash: "#fcebe9"
typography:
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  question:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 650
    lineHeight: 1.4
  answer:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "\"tnum\""
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\""
  reading:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 550
    lineHeight: 1.4
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
  filing:
    fontFamily: "Charter, \"Bitstream Charter\", \"Iowan Old Style\", \"Sitka Text\", Georgia, serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  quote:
    fontFamily: "Charter, \"Bitstream Charter\", \"Iowan Old Style\", \"Sitka Text\", Georgia, serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  filing-table:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\""
  mono:
    fontFamily: "ui-monospace, \"SF Mono\", Menlo, Consolas, monospace"
    fontSize: "0.92em"
    fontWeight: 400
rounded:
  marker: "2px"
  chip: "5px"
  sm: "6px"
  control: "7px"
  group: "9px"
  md: "10px"
  pill: "99px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "18px"
  gutter: "20px"
  detail: "28px"
  lg: "36px"
  page: "48px"
components:
  button:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-hover:
    backgroundColor: "{colors.paper-subtle}"
  button-primary:
    backgroundColor: "{colors.ocean}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.ocean-deep}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.graphite-2}"
    rounded: "{rounded.control}"
    height: "32px"
  button-ghost-hover:
    backgroundColor: "{colors.paper-hover}"
  segmented:
    backgroundColor: "{colors.paper-subtle}"
    rounded: "{rounded.group}"
    padding: "3px"
  segmented-option:
    textColor: "{colors.graphite-2}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "5px 10px"
  segmented-option-on:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite-ink}"
  question-row:
    textColor: "{colors.graphite-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "9px 10px"
  question-row-hover:
    backgroundColor: "{colors.paper-hover}"
  question-row-active:
    backgroundColor: "{colors.ocean-wash}"
  source-card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite-ink}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  source-card-active:
    backgroundColor: "{colors.ocean-wash}"
  filing-pane:
    backgroundColor: "{colors.filing-paper}"
    textColor: "#22262d"
    typography: "{typography.filing}"
    rounded: "{rounded.md}"
    padding: "18px 22px 22px"
  quote-mark:
    backgroundColor: "{colors.marker}"
    textColor: "inherit"
    rounded: "{rounded.marker}"
  citation-ref:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ocean}"
    rounded: "{rounded.chip}"
    padding: "2px 5px"
  citation-ref-active:
    backgroundColor: "{colors.ocean}"
    textColor: "{colors.paper}"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    height: "36px"
  tab:
    textColor: "{colors.graphite-2}"
    typography: "{typography.label}"
    padding: "0 11px"
    height: "56px"
  tab-on:
    textColor: "{colors.graphite-ink}"
---

# Design System: filing-room

## Overview

**Creative North Star: "The Annotated Filing"**

filing-room is a research tool in the canon of AlphaSense, Hebbia and S&P Capital IQ: white document ground, graphite ink, hairline gray rules, and a single deep ocean-blue for anything you can act on. Every answer sits beside the SEC passage it came from, and the only warm color in the system is a yellow marker painted over quoted filing text. The viewer should read the page as a well-kept research binder, not a dashboard: dense lists on the left, the answer and its source on the right, measurement shown in plain tables and one line chart.

Density is moderate and legible at shared-screen resolution. The app speaks in the platform's system sans with tabular numerals everywhere; the filing itself speaks in Charter, a document serif, so the reader can always tell the tool's words from the filing's words. Light theme only, chosen from the use scene: a laptop screen shared over video calls in daytime.

The build refuses the AI-dashboard default: no KPI tiles, no chat bubbles, no decorative gradients. Motion is almost absent: a 180ms panel entrance and one highlight sweep across the quote. The only other moving thing is a small spinner marking the running stage of a company run, because it signals work in progress. Nothing else moves.

**Key Characteristics:**
- White ground, graphite ink, 1px hairline rules for structure; tonal gray washes instead of cards.
- One interactive accent (ocean blue); yellow marker reserved for quoted filing text.
- Status as icon+word marks in fixed green / gray / amber, never as color alone.
- System sans for the tool, Charter for the filing's words; tabular numerals throughout.
- Two-pane split: list at roughly 38%, answer and filing pane in the rest.
- Motion limited to a 180ms entrance and one quote sweep; reduced motion disables both.

## Colors

A near-neutral cool-gray document palette with one blue for interaction, one yellow for source text, and a three-tone status set.

### Primary
- **Deep Ocean** (ocean): links, primary buttons, the active tab underline, focus rings (2px outline, 2px offset), the chart line, memo citation numbers, the caret. It marks what is clickable and what is selected; nothing decorative.
- **Ocean Deep** (ocean-deep): hover state of links and primary buttons only.
- **Ocean Wash** (ocean-wash): background of the selected question row, selected citation card, selected search result and selected table row.
- **Ocean Wash Strong** (ocean-wash-strong): text selection background.

### Secondary
- **Marker Yellow** (marker): the resting highlight on quoted filing text wherever a verified quote appears (filing pane, golden quotes).
- **Marker Strong** (marker-strong): the brighter band of the one-time sweep across a quote.
- **Marker Row** (marker-row): the full-row wash on a filing table row that contains a quoted cell.

### Tertiary (status)
- **Verified Green** (verified-green) with **Verified Green Wash** (verified-green-wash): "Verified quote", "Graded correct", a verified golden item.
- **Caution Amber** (caution-amber) with **Caution Amber Wash** (caution-amber-wash): "Unsupported", memo sentences flagged by the claim check (wavy underline), partial citation support.
- **Error Red** (error-red) with **Error Red Wash** (error-red-wash): "Graded wrong", request errors.

### Neutral
- **Paper** (paper): app ground, top bar, button and card fills.
- **Paper Subtle** (paper-subtle): the result strip, the memo side pane, segmented-control troughs, table-row hover.
- **Paper Hover** (paper-hover): hover on list rows, ghost buttons and segment options.
- **Filing Paper** (filing-paper): the filing pane body and golden quote blocks, a hair off-white so the filing reads as a separate sheet.
- **Hairline** (hairline): every structural rule: pane dividers, table rows, the facts band, card borders.
- **Hairline Strong** (hairline-strong): button and input borders, table header rules, scrollbar thumbs, dashed empty-slot borders.
- **Graphite Ink** (graphite-ink): primary text. **Graphite 2** (graphite-2): secondary text, inactive tabs. **Graphite 3** (graphite-3): captions, metadata, and the "Not in filings" mark.

### Named Rules
**The Marker Rule.** Yellow belongs to the filing. It appears only on text quoted from an SEC filing (and the table row holding it); never on UI chrome, never as a status, never for emphasis.

**The One Blue Rule.** Ocean blue means "you can act on this" or "this is selected". It is not used for headings, decoration, or data categories other than the single accuracy line.

## Typography

**Body Font:** System UI sans (-apple-system / SF Pro Text, Segoe UI, system-ui)
**Document Font:** Charter (with Bitstream Charter, Iowan Old Style, Sitka Text, Georgia)
**Mono Font:** ui-monospace (SF Mono, Menlo, Consolas) for run ids, question ids and model names

**Character:** A plain, native-feeling sans for the tool, set against a sturdy book serif for the filing's own words. The pairing is functional: the serif marks provenance.

### Hierarchy
- **Headline** (650, 24px, 1.25): page titles on Evals and Golden set, the memo title.
- **Question** (600, 21px, 1.3): the selected checklist question at the top of the answer panel.
- **Company name** (650, 19px): the company heading above the checklist and the Ask form.
- **Answer** (400, 17px, 1.55, max 70ch): the answer text, at reading size.
- **Title** (650, 16-17px): section heads (memo h2, page blocks), empty-state titles.
- **Reading** (400, 16px, 1.7, max 72ch): memo paragraphs. The lede on pages is 15px/1.6, max 78ch.
- **Body** (400, 14px, 1.5): list rows, tables, general UI.
- **Label** (550, 13-13.5px): tabs, buttons, segment options, status marks, grade marks.
- **Caption** (400, 12-12.5px): metadata, dt labels, column keys (600, 11.5px), chart ticks (11px).
- **Filing** (Charter 400, 16px, 1.6, max 72ch): prose inside the filing pane.
- **Quote** (Charter 400, 14.5-15px, 1.45-1.55): cited-quote cards, search results, golden quotes.
- **Filing table** (sans 400, 13px, tabular): tables inside the filing pane; numeric cells right-aligned.

Headings carry -0.01em tracking and balanced wrapping; the wordmark is 700, 15px, -0.02em. Intermediate weights 550 and 650 are part of the system.

### Named Rules
**The Provenance Rule.** Charter is used for text quoted from a filing, wherever it appears: the filing pane, cited-quote cards, search results, golden quotes. Everything the tool itself says is in the sans. Filing tables are the exception: they use the sans with tabular numerals so columns align.

**The Tabular Rule.** Numerals are tabular everywhere (set on body). Numbers in tables right-align.

**The Title-Case Rule.** SEC headings that arrive in all caps are set in title case (acronyms like GAAP, SEC, MD&A kept). No all-caps labels anywhere in the UI.

## Layout

A full-height app shell: a 56px top bar (wordmark, company switcher, view tabs, spend meter at the right), a slim result strip (min 40px) on a subtle gray band, then one view filling the rest. Panes scroll independently; the body does not.

Checklist, Search and Ask use a two-column split: a list pane of `minmax(340px, 38%)` with a hairline right border, and a detail pane (28px 36px padding) holding the answer panel and filing pane, capped at 900px wide. The memo view flips it: the memo (36px 48px padding, 72ch measure) on the left, a side pane of `minmax(380px, 42%)` on the subtle gray at the right. Full pages (Evals, Golden set) use 36px 48px padding and a 1180px content cap.

The horizontal gutter is 20px throughout the list side and top bar. Vertical rhythm inside the answer panel is an 18px stack; page blocks are separated by 40px.

At 1100px the spend meter and company full names drop. At 860px the shell becomes a scrolling page: tabs move to their own 44px scrolling row (faded at the right edge), the split stacks to one column, the list pane caps at 46vh, the filing body caps at 70vh, and padding tightens to 20px 16px.

## Elevation & Depth

Flat by default. Depth comes from tonal layering (paper, paper-subtle, filing-paper) and 1px hairlines, not shadows. Two shadows exist, both small and functional.

### Shadow Vocabulary
- **Selected segment** (`box-shadow: 0 1px 2px rgb(21 24 30 / 0.1), 0 0 0 1px #e3e6eb`): lifts the chosen option out of a segmented-control trough (company switcher, filters).
- **Floating** (`box-shadow: 0 1px 2px rgb(21 24 30 / 0.06), 0 6px 18px rgb(21 24 30 / 0.08)`): the chart tooltip, the only floating surface.
- **Sticky rule** (`box-shadow: 0 1px 0 #cdd2da`): the pinned column-label row inside a filing table.

### Named Rules
**The Hairline Rule.** Structure is drawn with 1px hairlines and gray washes. Containers do not float; only the tooltip does.

## Shapes

Gentle, small radii that stay out of the way: 6px on list rows and citation cards, 7px on buttons, inputs and segment options, 9px on segmented troughs, 10px on the filing pane, 5px on memo citation numbers, 2px on marker highlights. Borders are 1px; the empty filing slot uses a 1px dashed hairline-strong border. Icons share one stroke family: 24px grid, 1.75 stroke, round caps and joins, drawn at 16px (14-15px inside buttons and the strip).

## Components

### Buttons
Quiet, compact, bordered.
- **Shape:** 7px radius, 32px tall, 12px horizontal padding, 13px/550 label, 6px gap to an optional 15px icon.
- **Default:** paper fill, hairline-strong border, graphite ink; hover to paper-subtle.
- **Primary:** ocean fill and border, white text; hover to ocean-deep. Used for Ask.
- **Ghost / Icon:** transparent, graphite-2; hover to paper-hover. Icon buttons are 32px square (filing prev/next, sec.gov link).
- **Disabled:** 45% opacity, not-allowed cursor.
- **Focus:** 2px ocean outline, 2px offset, on every focusable element.

### Segmented control
The company switcher and checklist filters: a paper-subtle trough with a hairline border and 9px radius holding 7px-radius options; the selected option sits on paper with the selected-segment shadow. Counts sit inside options in muted tabular numerals.

### Navigation
View tabs stretch the full 56px bar height, 13.5px/550 graphite-2; the active tab turns graphite-ink with a 2px ocean underline. A thin vertical hairline separates the company views from the global views (Evals, Golden set).

### Status marks
Icon plus word, 13px/550, in the status tone: check-circle "Verified quote" (green), minus-circle "Not in filings" (graphite-3), alert triangle "Unsupported" (amber). Grade marks follow the same grammar: check "Graded correct", x-circle "Graded wrong", open circle "Support only". In the dense question list they drop to icons only, with a text title and screen-reader word, and a column key reading "Status · Question · Graded" labels the columns.

### Question list
Grouped by category under 12.5px/650 group heads. Rows are a three-column grid (18px mark, question clamped to two lines, grade icon), 6px radius; hover paper-hover, selected ocean-wash with the question at 550. Up/down keys step through questions.

### Answer panel
Question, answer at 17px, then a facts band (Status, Value, Period, Confidence, Eval) between two hairlines with 12px captions over 14px/550 values; a disclosure "Compare with the golden answer" in ocean; then cited-quote cards and the filing pane. Enters with the 180ms panel entrance.

### Citation cards
Full-width buttons, paper fill, hairline border, 6px radius, 10px 12px padding: the quote in Charter 15px clamped to two lines, then 12px document and section metadata. Hover strengthens the border; the selected card takes an ocean border on ocean-wash. Table-row pipes inside quotes render as thin 1px cell dividers at 35% opacity (the literal pipe stays in the DOM for screen readers).

### Filing pane (signature)
A 10px-radius sheet on filing-paper with a hairline border. Its header on paper names the form, period, filing date and title-cased section, with ghost prev/next buttons and a sec.gov link. The body is Charter 16px/1.6; tables inside it use the sans at 13px, tabular, right-aligned numbers, hairline row rules, and a sticky year row. Quoted text carries the marker at rest; a table row containing a quote takes marker-row. On open, the pane scrolls the first quote to a third of the way down and a marker-strong band sweeps across the quote once (700ms, ease-out-expo `cubic-bezier(0.16, 1, 0.3, 1)`) and retracts, leaving the resting marker. Hovering or focusing a citation adds a 2px ocean ring to that quote's marks. When a quote is not in the passage, a footer note says so.

### Memo citations
Bracketed source numbers as small chips: 5px radius, paper fill, hairline-strong border, ocean 12.5px/600 numerals; hover and selected invert to ocean fill with white. Sentences flagged by the claim check carry a 1px wavy amber underline and an amber alert icon button.

### Inputs
Paper fill, hairline-strong border, 7px radius, 14px text; search is 36px tall with a 34px left inset for the search icon. Focus replaces the border with a 2px ocean outline.

### Data tables and chart
Tables are full-width, 13.5px, 12px graphite-2 headers over a hairline-strong rule, hairline row rules, right-aligned tabular numbers; row hover paper-subtle, selected ocean-wash. The eval chart is one ocean line with 5px dots (the single Box test run in graphite ink), hairline grid, a dashed graphite-3 pass-bar line, and the floating tooltip.

## Do's and Don'ts

### Do:
- **Do** put every answer beside its source: the filing pane opens at the quoted passage with the marker painted.
- **Do** set any text quoted from a filing in Charter, and everything the tool says in the system sans.
- **Do** show status as icon plus word in the fixed tones (green verified, graphite-3 not in filings, amber unsupported); in dense lists use the icon with a column key and an accessible word.
- **Do** draw structure with 1px hairlines (#e3e6eb) and gray washes; reserve the floating shadow for the tooltip.
- **Do** keep motion to the 180ms ease-out panel entrance, the single quote sweep, and the run-progress spinner, and disable all three under reduced motion.
- **Do** keep numerals tabular and right-align numeric table columns.
- **Do** title-case SEC all-caps headings and render table pipes in quotes as thin cell dividers.

### Don't:
- **Don't** use marker yellow for anything but quoted filing text and the table row holding it.
- **Don't** use ocean blue for decoration or headings; it means interactive or selected.
- **Don't** build KPI tiles, chat bubbles, or decorative gradient fills; results are shown as sentences, tables and one chart.
- **Don't** add hover lifts, parallax, or animated counters; nothing moves except the entrance and the sweep.
- **Don't** set UI labels in all caps or with wide tracking.
- **Don't** add a dark theme; the system is light-only for daytime screen sharing.
