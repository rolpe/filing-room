---
name: filing-room
description: A dense, calm research workspace where every finding sits one click from its filing passage.
colors:
  ink: "#14161a"
  ink-2: "#3c424c"
  ink-3: "#5d6470"
  ground: "#ffffff"
  panel: "#f6f6f3"
  panel-2: "#eeeeea"
  line: "#e4e4df"
  line-strong: "#cdcdc7"
  rail: "#15171b"
  rail-2: "#24282f"
  rail-line: "#2c3038"
  rail-text: "#c8ccd3"
  rail-muted: "#8d939d"
  mark: "#ffe680"
  mark-strong: "#ffcf33"
  ok: "#17694a"
  ok-wash: "#e5f2eb"
  warn: "#8a4706"
  warn-wash: "#fbeedb"
  bad: "#9b1c1c"
  bad-wash: "#fbe9e9"
  filing-ink: "#23262c"
  filing-ctx: "#5b616b"
typography:
  ui:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"SF Pro Text\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "13px"
    lineHeight: 1.45
    fontFeature: "\"tnum\""
  small:
    fontSize: "12px"
  lead:
    fontSize: "14px"
    lineHeight: 1.5
  h2:
    fontSize: "17px"
    fontWeight: 650
    letterSpacing: "-0.01em"
  h1:
    fontSize: "20px"
    fontWeight: 650
    letterSpacing: "-0.015em"
  filing:
    fontFamily: "Charter, \"Bitstream Charter\", \"Iowan Old Style\", \"Sitka Text\", Georgia, serif"
    fontSize: "15px"
    lineHeight: 1.62
layout:
  rail: "208px; 52px icon rail below 1240px"
  gutter: "24px; 16px below 1020px"
  radius: "7px controls, 8px panels and menus, 10px dialogs, 4px reference chips"
---

# Design

The approved visual contract is the two mockups in `docs/mockups/` (`coverage.html`, `company.html`). This file records what the built app (`web/`) actually uses. Tokens live in one file, `web/src/styles/tokens.css`; component styles are in `web/src/styles/` (`app.css` for the frame and shared components, then `coverage.css`, `company.css`, `findings.css`, `memo.css`, `pages.css`).

## Principles

- **Dark rail, white work area.** The sidebar is the only dark surface. Everything the user reads sits on white.
- **Black for action and selection.** Primary buttons, the active tab underline, the selected citation chip, and progress fills are `ink`. There is no brand colour.
- **Yellow only for filing text.** `mark` highlights every quote of the current finding in the passage; `mark-strong` is the active one. Yellow is used nowhere else.
- **Serif for filing text, sans for everything else.** Filing passages and the screening memo body are set in the serif stack; numbers in the UI use tabular numerals.
- **Three statuses, always with an icon and a word:** Verified (`ok`, check-circle), To review (`warn`, flag), Not disclosed (`ink-3`, dash-circle). Colour is never the only signal.
- **Negatives in parentheses**, money in $M with one decimal, percentages with one decimal; ratios shown under their line item in a quieter row.

## Frame

- **Rail** (`.rail`): wordmark, Coverage, Recent companies (ticker + name, from the browser), Usage at the foot. Below 1240px it collapses to a 52px icon rail showing tickers only.
- **Top bar** (`.bar`, 52px) on Coverage: find-or-add search (`⌘K`) and the primary Add company button.
- **Page head** (`.page-head`): 20px title, a muted count, a segmented filter (`.seg`) on the right.

## Components

- **Buttons** (`.btn`): 32px; `.primary` is ink on white text; `.ghost` has no border; `.sm` 28px; `.sq` square icon button. Disabled at 50% opacity.
- **Segmented filter** (`.seg`): grey track, the pressed option on white with a 1px shadow, counts in muted `<i>` text.
- **Status** (`.status.ok|warn|none|bad`): 14px icon + 12px label at weight 550.
- **Tables:** coverage (`.cov`, 52px rows, sticky header), findings (`.find`, grouped with group header rows, gist under the label in 12px muted, value column right-aligned in weight 600), financials (`.fin`), plain lists (`table.plain`). Hover is `panel`; the selected row is `panel-2`.
- **Company header** (`.co-head`): breadcrumb, 20px name, ticker chip (`.tick`), actions (Export menu, Ask a question, More menu), a muted meta line, and the figures row (`.figures`): label over a 15px value with an optional muted sub-figure. Figures that open a finding underline on hover only.
- **Tabs** (`.tabs`): muted labels with counts; the current tab is ink with a 2px ink underline.
- **Detail and source panel** (`.detail`): head with position and previous/next/close; label (17px), the question in 12px muted, a lead sentence and up to four bullets each ending in numbered reference chips (`.ref`; dashed warn border for a quote not found in the filing); the facts row (`.facts`: status, period, confidence, SEC data); a reasons box on `warn-wash` (on `panel` once reviewed); actions (copy with citation, note, mark as reviewed, flag); notes on `panel`; quotes not found in the filing on `warn-wash`; then the document (`.doc`): grey head with form, filing date and section, "Passage n of m", previous/next and a sec.gov link, and the serif filing text with marks, numbered superscripts, muted context paragraphs and Earlier/Later text controls. Below 1020px the panel becomes a right-hand drawer with a shadow over the list.
- **Long answer prose** without a presentation pass is clamped to six lines with Show more.
- **Screening memo** (`.memo-doc`): a 720px serif document with a sans kicker and title, sans section headings, footnote chips (`.fn`) that open the same detail and source panel, flagged sentences on `warn-wash` with a dashed underline, and a Sources list. The print stylesheet hides the app chrome, prints footnotes as [n], and expands each source to its quote, filing and sec.gov URL.
- **Q&A** (`.qa`): a question box with the per-question cost and today's spend beside the Ask button; each answer with reference chips, status (with the reason when To review), period, time and actual cost. Citations open the source panel.
- **Dialogs** (`.dialog` on a 32% ink scrim): the add/resume dialog lays out company, industry, fiscal year end, filings to read, estimated cost and today's budget as a definition list, then one primary action naming the cost. Confirm dialogs use the same frame.
- **Menus** (`.menu`): 8px radius, pop shadow, 32px items.
- **Progress** (`.prog`): a 4px track with an ink fill animated by `transform: scaleX()`, plus the stage label ("Answering, 22 of 40").
- **Notices** (`.notice`, `.warn`, `.bad`) for in-context messages; **skeletons** (`.sk`) for loading; **empty and error states** (`.state`) always with a next action.

## Evaluation area (developer tools)

Same frame, tokens and components; sits under a "Developer" group in the rail and uses the company-tab pattern for its sections (Runs, Golden set, Run an eval). Local styles are in `web/src/styles/evals.css`.

- **Accuracy trend** (`.ev-trend`): an inline SVG, no chart library. Ink line and points per full run oldest to newest, the pass bar as a dashed `warn` line, value labels above points, run label and companies below. The held-out run is a hollow point.
- **Run tables** (`table.plain.ev-runs`): label in weight 650 with date and note beneath in 12px muted; ticker chips; metrics right-aligned; the pass-bar column uses the status pattern (Meets / Misses: which). The held-out run's row sits on `panel` with an ink "Held out" chip.
- **Metrics strip** (`.ev-metrics`): a ruled grid of label, 17px value and a one-line plain definition.
- **Graded items** reuse the findings table and the detail panel: expected answer with the golden quote in a serif `panel` block (`.ev-quote`), the answer, the verdict (Correct / Wrong / Not graded with check, x and dash icons), the judge's reason, and the citations opening the same passage viewer, fed from the eval corpus.
- **Run form** (`.ev-form`): fieldsets for companies (the held-out company shown disabled with its reason), scope (spot check with an item picker, or full set), label and note; a cost row with the estimate, today's budget and the per-run stop beside one primary button naming the cost; live progress uses the standard progress bar.

## Responsive

- Above 1240px: full rail, two-column work area (list 1.12fr, panel 1fr).
- 1020–1240px: icon rail; same two columns; coverage drops the Op. margin and Updated columns.
- Below 1020px: one column; the detail panel is a drawer; coverage also drops gross margin and FCF margin.
- Below 720px: coverage drops fiscal year and latest filing; findings drop the source column. Phone layout is not a goal; nothing breaks at 800px.

## Motion

Only colour and background transitions (150ms) on controls, the progress fill transform, and skeleton shimmer. All disabled under `prefers-reduced-motion`.
