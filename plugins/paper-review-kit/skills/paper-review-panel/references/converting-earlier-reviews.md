# Converting earlier reviews

Contents: 1 When · 2 Points, ids and severities · 3 Quotes · 4 Scores · 5 The response ·
6 What cannot be converted · 7 Checks after a conversion

## 1. When

A first round was run by hand, before this skill, or with another review form, and the
user wants later rounds to build on it. Conversion moves what the reviewers and the
authors wrote into the skill's formats so that the ledger, the packets and the stopping
rule work. It is bookkeeping: it adds no point, no reason and no search that the originals
do not contain.

Keep the originals unchanged in `<review-dir>/earlier/` (each review, the old response, the
old score sheet). Each converted review points back to its original with
`"converted_from": "earlier/R1-original.md"`; `ledger.py rooms` then puts the original into
the returning reviewer's room next to the converted file, so the reviewer reads its own
words, not only your conversion. Only a file inside `earlier/` is copied; any other path
is skipped with a warning.

## 2. Points, ids and severities

- **Where the points come from.** When the authors answered point by point, take one point
  per response row: those are the points the revision acted on. Otherwise take the
  review's own list (weaknesses, requested changes, questions, experiments). Split a row
  into several points only where the review itself lists them separately.
- **Ids.** Number each reviewer's points `<RID>.1`, `<RID>.2`, ... in the review's own
  order and write an id map, `earlier/id-map.json` (`{"A-3": "R1.3", ...}`). Rewrite every
  old id in the converted files through the map, including cross-references inside the
  response's `what` and `why_not`, by whole-token replacement (`A-1` must not match inside
  `A-12`).
- **Severity by the reviewer's own levels.** A point the reviewer called major, essential
  or required is `must-fix`; recommended or important is `should-fix`; minor, typo or
  presentation is `minor`. Without levels, use the review's own words ("most importantly",
  "a small point"); where nothing says, use `should-fix` and say so in `launch.notes`.
  Never set a severity by your own reading of the point.
- **The other fields** (type, title, where, why, resolution) come from the review's text,
  shortened, never changed in meaning. A point whose review asks for nothing specific keeps
  an empty `resolution`; the ledger will warn, and the warning is true.

## 3. Quotes

- **Only where a passage exists.** If the reviewer quoted the manuscript, cut that passage
  from the text layer. If the point is about a specific passage the reviewer did not quote,
  you may choose the nearest passage and set `"quote_chosen": true` on the finding: the
  packet tells the reviewer the passage was chosen, and the report marks it. If no passage
  fits (a missing experiment, a general request), leave `quote` empty; `check_quotes.py`
  lists it as missing, which is the true record. Converted reviews get no repair pass: the
  original reviewer cannot be asked.
- **Cut, never type.** Do not type a quote or copy it from a PDF viewer. Choose a start
  marker and an end marker of a few words each and cut the text between them from
  `manuscript.txt`; table cells and two-column pages break lines inside a passage, and the
  markers keep the cut exact:

  ```python
  text = open("round-1/manuscript.txt", encoding="utf-8").read()
  start = text.index("Each fold holds")
  end = text.index("items.", start) + len("items.")
  quote = " ".join(text[start:end].split())
  ```

  For a passage that runs through table cells, cut each piece the same way and join the
  pieces with ` ... ` (each at least four words).

## 4. Scores

- **Anchored scores** (`scores`, `overall`, `confidence`) follow the anchors of `schemas.md`
  section 1 from the converted points: `overall` follows the most serious open point and
  `needs_new_work`. Do not translate an old total onto the anchors: a 5 out of 10 is not a
  level 3, and the two cannot be compared.
- **The old sheet stays as it was**, as the extra score sheet: declare it in `plan.json`
  (`extra_score_sheet`, with its name and scales) and copy each reviewer's old values, all
  of them, into `extra_scores` of its converted review, including fields that have no place
  among the anchored scores. Ask every later reviewer, returning and fresh, to fill the same
  sheet; the report then shows its movement, read within the sheet only.

## 5. The response

- One `response.json` for the round, in the folder of the round whose version it came with.
- **Status words.** Done is `changed`; partly done is `partly`; not done is `not-changed`;
  a disagreement is `not-changed` with the authors' reason in `why_not` and `disagree: true`.
  Keep the authors' reasons in their words.
- **Out of reach** only for requests in the plan's `out_of_reach` list for that round,
  agreed with the user; the authors' text alone does not decide it, and the ledger warns
  when a row is marked out of reach but the plan lists nothing.
- **Other changes.** `other_changes` is one list for the whole response. When several
  per-reviewer responses repeat the same change, keep one entry with the general wording
  and drop the reviewer-specific phrasing.
- Quotes of the new text are cut from the revised version's text layer, as above; a change
  in the supplement names the supplement in `where`.

## 6. What cannot be converted

- **Counter-evidence searches**: leave `counter_evidence.looked_at` empty (`outcome`
  `kept`). The ledger does not warn about them for a review marked converted.
- **The reading record**: `pages_read` empty, `page_images` false, `web_used` and
  `searches` only as the original states them (listed searches are still audited).
- **Step-1 criteria**, when the earlier round was itself a re-review; the ledger does not ask
  for them on a converted review.
- **Checks that never ran**: a converted point without a finding check is unchecked; run
  the checker pass on the must-fix points if triage or the stopping rule needs it.

Mark every converted review `"converted": true`, and record in the round's
`synthesis.json` how it was run (`launch.mode` as it really was, `sequential` if one
context wrote all reviews; the model if known) and, in `launch.notes`, that it was
converted and when. The report then says "converted" for that reviewer and round.

## 7. Checks after a conversion

1. `check_quotes.py round-1`: every quote is found; the missing ones are exactly the points
   without a passage.
2. `ledger.py build`: the remaining warnings are ones the originals explain (an empty
   resolution, an unchecked point), not ones you could silence by writing content.
3. Show the user the id map, the severities you could not read from the review, and the
   old score sheet, once, before round 2.
