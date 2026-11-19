# Schemas and score anchors

Contents: 1 Score anchors · 2 Building blocks · 3 Review (fresh reviewer) · 4 Re-review
(returning reviewer) · 5 Quote repair · 6 Checks · 7 Response · 8 Synthesis · 9 Plan ·
10 Files the scripts read and write (page map, queries, rooms, quotes, ledger)

The JSON Schemas use only `type`, `properties`, `required`, `enum`, `items`, `minimum` and
`maximum`, so they work as structured-output schemas in most hosts. Sections 3 and 4 are
built from the blocks in section 2: in a workflow script, define each block once as a
constant and reference it; in a sub-agent brief, paste the expanded object.

The scripts tolerate missing optional fields, but a review that leaves out `quote`,
`resolution` or `counter_evidence` will draw warnings and lose standing in the ledger.

## 1. Score anchors

Scores are ordinal and exist to show movement between rounds. Each level has the meaning
below; use it literally. `"not-assessed"` means the reviewer has no basis for the score; it
is not zero and is never averaged. Model reviewers tend to score high and to separate
strong from weak papers poorly, which is why the anchors tie levels to concrete open
points rather than to impressions.

**Soundness, evidence, clarity, reproducibility** (1 to 5, or `"not-assessed"`):

| Level | Meaning in this respect |
|---|---|
| 5 | Checked; nothing to change |
| 4 | Only minor points |
| 3 | Should-fix points, no must-fix |
| 2 | A must-fix point that rewriting, or re-analysing results the paper already has, can resolve |
| 1 | A must-fix point that needs new work, or the paper's own evidence contradicts a claim |

- soundness: are the method and the analysis correct?
- evidence: do the results shown support the claims as worded?
- clarity: can a reader of the venue follow what was done and why?
- reproducibility: could someone redo the main result from the paper and what is released?

**Novelty** (1 to 5, or `"not-assessed"`); every level from 1 to 4 names the closest work
in `basis`:

| Level | Meaning |
|---|---|
| 5 | New in a way that matters to the field, beyond the closest work the reviewer knows |
| 4 | Clearly new in a useful respect |
| 3 | A real but small step beyond the closest work |
| 2 | Largely covered by the named prior work |
| 1 | Already done in the named prior work |

**Overall** (1 to 5) follows the most serious point still open, not an average of the
dimensions. Take the highest level whose description holds, and list the ids that set it in
`driven_by`:

| Level | Meaning |
|---|---|
| 5 | No open must-fix or should-fix point |
| 4 | No open must-fix point; should-fix points remain |
| 3 | Open must-fix points, all resolvable by rewriting or by re-analysing existing results |
| 2 | An open must-fix point needs new experiments or data, or a main claim has to change |
| 1 | A main claim is contradicted by the paper's own evidence, or the core method is unsound |

**Confidence** (1 to 4), separate from every score:

| Level | Meaning |
|---|---|
| 4 | Checked the details; knows the area closely |
| 3 | Checked the main points; knows the area |
| 2 | Read everything but could not check key parts (figures not inspected, outside own expertise) |
| 1 | An informed guess |

## 2. Building blocks

`SCORE` (one per dimension):

```json
{"type": "object", "required": ["level", "basis"],
 "properties": {
   "level": {"enum": [1, 2, 3, 4, 5, "not-assessed"]},
   "basis": {"type": "string", "description": "where in the paper the score comes from; for novelty, the closest work"}}}
```

`SCORES`, `OVERALL`, `CONFIDENCE`:

```json
{"type": "object", "required": ["novelty", "soundness", "evidence", "clarity", "reproducibility"],
 "properties": {"novelty": SCORE, "soundness": SCORE, "evidence": SCORE, "clarity": SCORE, "reproducibility": SCORE}}
```

```json
{"type": "object", "required": ["level", "driven_by"],
 "properties": {"level": {"type": "integer", "minimum": 1, "maximum": 5},
                "driven_by": {"type": "array", "items": {"type": "string"}}}}
```

```json
{"type": "object", "required": ["level", "basis"],
 "properties": {"level": {"type": "integer", "minimum": 1, "maximum": 4}, "basis": {"type": "string"}}}
```

`READING` (what the reviewer actually did; add `"compared_with_previous": {"type": "boolean"}`
for returning reviewers):

```json
{"type": "object", "required": ["pages_read", "page_images", "not_inspected", "web_used", "searches"],
 "properties": {
   "pages_read": {"type": "string", "description": "for example 1-9"},
   "page_images": {"type": "boolean", "description": "true if pages were viewed as images"},
   "not_inspected": {"type": "array", "items": {"type": "string"}, "description": "figures or tables that could not be inspected"},
   "web_used": {"type": "boolean"},
   "searches": {"type": "array", "items": {"type": "string"}, "description": "every web query, verbatim"}}}
```

`FINDING` (one point). `FINDING_WITH_ORIGIN` is the same object with `"origin"` added to
`required`; returning reviewers use it for their new points.

```json
{"type": "object",
 "required": ["id", "type", "severity", "title", "where", "quote", "why", "resolution",
              "needs_new_work", "counter_evidence", "looked_for", "literature", "status"],
 "properties": {
   "id": {"type": "string", "description": "<reviewer>.<n>, for example R2.3; never reused"},
   "type": {"enum": ["defect", "unsupported-claim", "clarification"]},
   "severity": {"enum": ["must-fix", "should-fix", "minor"]},
   "title": {"type": "string", "description": "one line"},
   "where": {"type": "string", "description": "section, table, figure, page"},
   "quote": {"type": "string", "description": "verbatim from the manuscript; '...' joins fragments"},
   "why": {"type": "string", "description": "why it matters"},
   "resolution": {"type": "string", "description": "what change would resolve it"},
   "needs_new_work": {"type": "boolean", "description": "true if resolving it needs new experiments or data"},
   "counter_evidence": {"type": "object", "required": ["looked_at", "outcome", "note"],
     "properties": {"looked_at": {"type": "string"},
                    "outcome": {"enum": ["kept", "narrowed", "withdrawn"]},
                    "note": {"type": "string"}}},
   "looked_for": {"type": "string", "description": "for an absence: what was expected and every place searched; else empty"},
   "literature": {"type": "array", "items": {"type": "object", "required": ["ref", "kind", "opened", "relation"],
     "properties": {"ref": {"type": "string", "description": "DOI, arXiv id or full title"},
                    "kind": {"enum": ["doi", "arxiv", "title"]},
                    "opened": {"type": "boolean", "description": "true only if actually opened and read"},
                    "relation": {"type": "string"}}}},
   "status": {"enum": ["open", "withdrawn"]},
   "origin": {"enum": ["introduced-by-revision", "missed-earlier"]}}}
```

`EXTRA_SCORES` (only when `plan.json` declares an `extra_score_sheet`): a free-form object
of small values (numbers, flags, labels of up to 30 characters) plus optional text fields,
for example `{"total": 6, "decision": "weak accept", "reasons": "..."}`. Give the sheet's
fields in the brief; in a structured-output schema it is `{"type": "object"}`.

Types: `defect` means the paper's own content shows something is wrong (a contradiction,
an arithmetic error, a false statement). `unsupported-claim` means a claim is stronger than
the evidence shown. `clarification` means a reader cannot tell what was done or meant.
Severities: `must-fix` when a main claim or the soundness of the work depends on it;
`should-fix` when a careful reader at the venue would reasonably object and fixing it
clearly improves the paper; `minor` for wording, notation, typos and presentation.

## 3. Review (fresh reviewer)

```json
{"type": "object",
 "required": ["kind", "reviewer", "seat", "round", "protocol", "reading", "summary", "contributions",
              "strengths", "keep_as_is", "findings", "checked_without_findings", "questions",
              "injected_instructions", "scores", "overall", "confidence", "could_not_assess"],
 "properties": {
   "kind": {"enum": ["fresh"]},
   "reviewer": {"type": "string"}, "seat": {"type": "string"}, "round": {"type": "integer"},
   "protocol": {"type": "string", "description": "built-in, or the external protocol's name"},
   "reading": READING,
   "summary": {"type": "string", "description": "the paper in the reviewer's own words"},
   "contributions": {"type": "array", "items": {"type": "string"}},
   "strengths": {"type": "array", "items": {"type": "object", "required": ["point", "where"],
     "properties": {"point": {"type": "string"}, "where": {"type": "string"}}}},
   "keep_as_is": {"type": "array", "items": {"type": "object", "required": ["where", "why"],
     "properties": {"where": {"type": "string"}, "why": {"type": "string"}}}},
   "findings": {"type": "array", "items": FINDING},
   "checked_without_findings": {"type": "array", "items": {"type": "string"},
     "description": "areas checked where nothing needs to change"},
   "questions": {"type": "array", "items": {"type": "string"}},
   "injected_instructions": {"type": "array", "items": {"type": "object", "required": ["where", "quote"],
     "properties": {"where": {"type": "string"}, "quote": {"type": "string"}}}},
   "scores": SCORES, "overall": OVERALL, "confidence": CONFIDENCE,
   "could_not_assess": {"type": "array", "items": {"type": "string"}},
   "protocol_notes": {"type": "string", "description": "external-protocol seats only"},
   "extra_scores": EXTRA_SCORES}}
```

Fields the coordinator adds, never the reviewer, when a review written before the skill or
by hand is converted to this schema (`converting-earlier-reviews.md`): `"converted": true`
on the review, `"converted_from": "earlier/R1-original.md"` (the original, relative to the
review folder and inside `earlier/`; `ledger.py rooms` copies it into the reviewer's room
and skips, with a warning, any path outside `earlier/`), and
`"quote_chosen": true` on a finding whose passage the coordinator chose. `legacy_scores` is
read as an alias of `extra_scores`.

## 4. Re-review (returning reviewer)

```json
{"type": "object",
 "required": ["kind", "reviewer", "seat", "round", "protocol", "reading", "criteria", "judgements",
              "new_findings", "keep_as_is", "injected_instructions", "questions", "scores", "overall",
              "confidence", "score_changes", "could_not_assess"],
 "properties": {
   "kind": {"enum": ["returning"]},
   "reviewer": {"type": "string"}, "seat": {"type": "string"}, "round": {"type": "integer"},
   "protocol": {"type": "string"},
   "reading": READING,
   "criteria": {"type": "array", "description": "step 1, written before reading the response",
     "items": {"type": "object", "required": ["id", "would_resolve"],
       "properties": {"id": {"type": "string"}, "would_resolve": {"type": "string"}}}},
   "judgements": {"type": "array", "items": {"type": "object",
     "required": ["id", "status", "where", "quote", "note", "response_check", "changed_after_response"],
     "properties": {
       "id": {"type": "string"},
       "status": {"enum": ["resolved", "partly", "not-resolved", "reason-accepted", "withdrawn"]},
       "where": {"type": "string", "description": "place in the revised PDF"},
       "quote": {"type": "string", "description": "verbatim from the revised PDF; required for resolved, partly and withdrawn"},
       "note": {"type": "string"},
       "remaining_severity": {"enum": ["must-fix", "should-fix", "minor"], "description": "partly only: the severity of what remains"},
       "response_check": {"type": "string", "description": "what the response claimed and whether the PDF shows it"},
       "changed_after_response": {"type": "boolean"}}}},
   "new_findings": {"type": "array", "items": FINDING_WITH_ORIGIN},
   "keep_as_is": {"type": "array", "items": {"type": "object", "required": ["where", "why"],
     "properties": {"where": {"type": "string"}, "why": {"type": "string"}}}},
   "injected_instructions": {"type": "array", "items": {"type": "object", "required": ["where", "quote"],
     "properties": {"where": {"type": "string"}, "quote": {"type": "string"}}}},
   "questions": {"type": "array", "items": {"type": "string"}},
   "scores": SCORES, "overall": OVERALL, "confidence": CONFIDENCE,
   "score_changes": {"type": "array", "items": {"type": "object", "required": ["score", "from", "to", "because"],
     "properties": {"score": {"type": "string", "description": "overall, confidence or a dimension"},
                    "from": {"enum": [1, 2, 3, 4, 5, "not-assessed"]},
                    "to": {"enum": [1, 2, 3, 4, 5, "not-assessed"]},
                    "because": {"type": "array", "items": {"type": "string"},
                                "description": "the status changes behind it, for example 'R2.3 resolved'"}}}},
   "could_not_assess": {"type": "array", "items": {"type": "string"}},
   "protocol_notes": {"type": "string"},
   "extra_scores": EXTRA_SCORES}}
```

Statuses: `resolved` when the reviewer's own criterion is met (quote required);
`partly` when some of it is (quote required; `note` says what remains, and
`remaining_severity` how serious it is: from then on the ledger, the stopping rule and the
report count the point at that level, shown as "was must-fix; what remains: should-fix";
it is never above the severity raised); `not-resolved`;
`reason-accepted` when the authors did not change it and the reviewer accepts their reason;
`withdrawn` when the reviewer now thinks the point was wrong because the paper already
answered it (quote of that passage in the revised PDF required; counted apart from
resolutions).

## 5. Quote repair

Saved as `round-<k>/repairs/<RID>.json`. The scripts apply it in memory; the review file
stays untouched.

```json
{"type": "object", "required": ["reviewer", "round", "repairs"],
 "properties": {
   "reviewer": {"type": "string"}, "round": {"type": "integer"},
   "repairs": {"type": "array", "items": {"type": "object", "required": ["id", "action", "quote", "why"],
     "properties": {"id": {"type": "string"},
                    "action": {"enum": ["replace", "withdraw"]},
                    "quote": {"type": "string", "description": "the verbatim replacement; empty when withdrawing"},
                    "why": {"type": "string"}}}}}}
```

`withdraw` on a finding sets it to withdrawn, counted as "withdrawn on quote repair" and
never as the reviewer's own self-check; on a judgement it sets the judgement to
`not-resolved`.

## 6. Checks

Saved as `round-<k>/checks.json` from the checker's output.

```json
{"type": "object", "required": ["round", "model", "checks"],
 "properties": {
   "round": {"type": "integer"}, "model": {"type": "string"},
   "checks": {"type": "array", "items": {"type": "object", "required": ["id", "kind", "verdict", "where", "quote", "note"],
     "properties": {"id": {"type": "string"},
                    "kind": {"enum": ["finding", "resolution", "literature"]},
                    "verdict": {"enum": ["upheld", "not-upheld", "unclear"]},
                    "where": {"type": "string"},
                    "quote": {"type": "string", "description": "verbatim passage that answers the point, when not upheld"},
                    "note": {"type": "string"}}}}}}
```

`finding`: upheld means nothing in the manuscript answers the point. `resolution`: upheld
means the quoted revised text meets the reviewer's criterion. `literature`: upheld means
the identifier exists and matches the work described. A `not-upheld` finding or
resolution check counts only when its quote is found by `check_quotes.py`; otherwise the
ledger reads it as `unclear`. A point "survives checking" when its finding check is
`upheld` or `unclear`: only a refutation with a found quote removes it.

## 7. Response

Saved as `round-<k>/response.json` with the revised manuscript of round k; rules in
`response-letter.md`.

```json
{"round": 2,
 "answers": [
   {"id": "R2.3", "action": "changed", "what": "Stated the number of held-out items per fold.",
    "where": "Sec. 3.1, p. 4", "quote": "Each fold holds out 9 of the 45 items.",
    "why_not": "", "out_of_reach": false},
   {"id": "R1.4", "action": "not-changed", "what": "", "where": "Sec. 1, p. 1", "quote": "",
    "why_not": "The claims are limited to one setting (Sec. 1); the second setting would not change any of them.",
    "out_of_reach": false, "disagree": true}],
 "other_changes": [{"what": "Shortened the conclusion", "where": "Sec. 6"}]}
```

`action` is `changed`, `partly` or `not-changed`. `quote` is verbatim from the revised PDF
(or its supplement) and required for `changed` and `partly`. `why_not` is required for
`not-changed` and for the unchanged part of `partly`. An author's disagreement is
`not-changed` with the reason in `why_not`; the optional `disagree: true` says so, and the
packet and the report show it. `out_of_reach` marks a request that cannot be met this round
and is listed in `plan.json` for this round; the ledger warns when a row is marked out of
reach but the plan lists nothing for the round. A `where` in the supplement names it
("Supplement S2, p. 3"); with a page map the report also shows where the quote was found.

## 8. Synthesis

Written by the coordinator as `round-<k>/synthesis.json` after the round's reviews, checks
and quote check.

```json
{"round": 1,
 "launch": {"mode": "workflow", "reviewer_model": "<model id>", "checker_model": "<model id>",
            "notes": "R3 relaunched once after a malformed answer"},
 "statement": "First reading; nothing revised yet.",
 "items": [
   {"id": "R2.1", "group": "change"},
   {"id": "R3.4", "same_as": "R2.1"},
   {"id": "R1.2", "group": "author-decision", "reason": "Needs a new experiment or a narrower claim."},
   {"id": "R1.5", "group": "not-recommended", "reason": "Asks for a second dataset the venue's scope does not need."}],
 "stop": {"decision": "continue", "note": "two must-fix points open"}}
```

- `launch.mode`: `workflow`, `subagents` or `sequential`.
- `group`: `change` (worth making, not yet made), `author-decision` (a trade-off, scope
  question or disagreement for the authors; reason required), `done` (made, or confirmed
  resolved), `not-recommended` (reason required). Points a reviewer confirmed as resolved,
  accepted the reason for, or withdrew, move to `done` / `not-recommended` / withdrawn
  automatically when no newer triage says otherwise.
- `same_as` joins duplicates, open or closed, across reviewers and rounds; the report shows
  them as one item raised by several reviewers. Triage the first point of a group and mark
  the others `same_as` it; an item with `same_as` and no `group` inherits the group's
  triage. The marks come first and the groups second (`rounds.md` section 5).
- Only ids that a reviewer raised are allowed; `ledger.py` warns about any other. There is
  no field for the coordinator's own criticism or for changing a score, on purpose. A
  factual note of the coordinator's (a reviewer's inference is wrong in size although its
  request is right) goes into `reason`, says where the fact comes from ("Table 2 of the
  revised version gives 4.1, not 41"), and is not a new criticism.
- `statement`: in plain words, what this round's revision actually changed in the paper.

## 9. Plan

`plan.json` at the top of the review folder, written before round 1. Reviewers never see it.

```json
{"label": "short label for the report",
 "language": "en",
 "venue": "kind of venue, page limit",
 "unpublished": true,
 "reviewer_model": "<model id chosen by the user>",
 "checker_model": "<cheaper model id, or scripts only>",
 "web": true,
 "max_rounds": 3,
 "budget": "free text",
 "stopping_rule": "Stop when no must-fix point is open, or when a round's fresh reviewers raise nothing new at must-fix or should-fix that survives checking, or after 3 rounds.",
 "private_terms": ["the title", "names coined in the paper", "author and project names"],
 "out_of_reach": {"2": ["a new user study"]},
 "extra_score_sheet": {"name": "the venue's form", "description": "1-10 total and a decision, as on the venue's form"},
 "seat_names": {"subfield-expert": "领域专家", "methods-statistics": "方法与统计", "general-reader": "一般读者"}}
```

`extra_score_sheet` (optional) declares a second score sheet that every reviewer fills in
`extra_scores` next to the anchored scores: the venue's own form, or the form of a round run
before the skill. The report prints it per reviewer and round, with the movement for
returning reviewers; levels are compared within the sheet only, never with the anchors.
`seat_names` (optional) gives each seat id a display name in the report's language.

`private_terms` feeds the search audit only; `ledger.json` and the report do not copy the
list, and audit flags name a term by its number. A flagged query is shown as it was sent,
because the user needs to see what left the machine. `out_of_reach` lists, per round,
requests the authors cannot meet in that round, agreed with the user before the revision;
returning reviewers see the list in their packet.

## 10. Files the scripts read and write

- `manuscript.pages.json` (by `extract_text.py` when given several PDFs):
  `{"text": "manuscript.txt", "pages": 17, "documents": [{"name": "manuscript", "file":
  "manuscript.pdf", "first_page": 1, "pages": 12}, {"name": "supplement", ...,
  "first_page": 13, "pages": 5}]}`. A document is named after its file.
- `queries.json` (optional, per round, written by the coordinator from the host's
  transcripts; read by `check_quotes.py`, or given with `--queries`): reviewer id to the
  list of web requests actually sent, each a string (a query) or an object such as
  `{"tool": "fetch", "url": "https://...", "prompt": "..."}`, for example
  `{"R4": ["topic words of a query", {"tool": "fetch", "url": "https://...", "prompt": "..."}]}`.
  Copy every search query, fetched URL and fetch prompt verbatim; leave out nothing that
  left the machine.
- `rooms.json` (per round, by `ledger.py rooms`): each reviewer's room, kind, seat and files.
- `quotes.json` (per round, by `check_quotes.py`): one entry per quote with `source`
  (reviewer id, `response` or `checks`), `id`, `field` (`finding`, `judgement`, `injected`,
  `response`, `check:<kind>`), `status` (`found`, `found-loose`, `not-found`, `missing`),
  `page` (in the joined text), with a page map also `document`, `document_index` and
  `document_page`, and flags `short`, `stitched`, `repaired` and `withdrawn`; plus
  `search_flags` (every flagged search, listed or from the transcripts) and, with
  `queries.json`, `transcript_audit` (`requests`, and `unlisted`: the requests whose text
  is not one of the reviewer's listed searches, each with its flags).
- `ledger.json` (by `ledger.py build`; derived, never edited): `rounds` (per-round counts,
  withdrawals on self-check and on quote repair, open must-fix before and after, fresh
  points that survived checking, churn flags, whether quotes were checked, the statement),
  `issues` (one entry per point: the finding fields, `raised_in`, `origin`, `history` of
  `{round, event, status, quote_check, check, remaining_severity}`, `response` rows,
  `triage`, `same_as`, `check_downgraded`, `quote_location` where a page map exists,
  current `status`, `current_severity` and `open`), `groups` (duplicates joined, with
  `severity` now and `raised_severity`, `disposition`, `reason`, `pending`), `seats`
  (per-reviewer counts for comparing methods), `fresh_vs_returning` (with one verdict per
  group of new fresh points, the head's, and `check_differs` for members whose verdict
  differs), `stopping`, `warnings`.
- A point is open when its latest status is `open`, `partly` or `not-resolved`, or when it
  is `resolved` or `withdrawn` by its reviewer's judgement but the quote of the revised
  text was not found (`resolved-unverified`, `withdrawn-unverified`).
