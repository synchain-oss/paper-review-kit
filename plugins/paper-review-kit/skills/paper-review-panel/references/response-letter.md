# The authors' response

The response goes to the returning reviewers together with the revised PDF. Its job is to
let each reviewer find, quickly and without trusting the authors, what changed for each of
their points. It is saved as `round-<k>/response.json` (schema in `schemas.md` section 7)
in the folder of the round whose manuscript it accompanies; `ledger.py packets` cuts it
into one table per reviewer.

## Format

One row per point that was open after the previous round, from every reviewer, including
points the coordinator advised against: the reviewer still judges them, and needs the
authors' reason.

| Field | Content |
|---|---|
| `id` | the reviewer's point id, unchanged |
| `action` | `changed`, `partly` or `not-changed` |
| `what` | what was done, in one or two plain sentences |
| `where` | section, table, figure and page in the revised PDF; name the supplement when the change is there |
| `quote` | a short verbatim passage of the new text (for `changed` and `partly`) |
| `why_not` | for `not-changed`, and for the unchanged part of `partly`: the reason |
| `out_of_reach` | true when the request cannot be met this round (it is in the plan's list) |
| `disagree` | optional; true when the authors disagree with the point (the action is then `not-changed`, or `partly` for the part they accept) |

`other_changes` lists changes not tied to any point (shortened sections, moved figures), so
that reviewers can see everything that moved.

Rendered for one reviewer, it reads like this:

| id | action | what was done | where | why not |
|---|---|---|---|---|
| R2.1 | changed | Reported the difference with a 95% interval and replaced "perform equally" by "no difference detected". | Sec. 4.2, Table 3, p. 5 | |
| R2.4 | not-changed | | | The second dataset is not public; the limitation is now stated in Sec. 6. |

## Rules, and why

- **Never claim what the PDF does not show.** Every `changed` or `partly` row quotes the
  new text, and `check_quotes.py` verifies the quote against the revised PDF before the
  response is sent. A response that claims a change the paper lacks is the fastest way to
  win a returning reviewer's "resolved" undeservedly, which is exactly the failure the
  returning brief guards against.
- **One row per point, in the reviewer's own ids.** Merged answers ("R1.2, R2.5 and R3.1:
  see Sec. 4") hide which part of which point was addressed. When one change answers
  several points, repeat it in each row.
- **Say where, precisely.** Section, table or figure, and page. The reviewer checks it; a
  vague place makes the check slow and the judgement unreliable.
- **Promises are not changes.** "We will add this in the final version" is `not-changed`,
  with the promise in `why_not`.
- **Reasons are specific and checkable.** "Outside the scope" is weak; "the paper's claims
  are limited to a single setting (Sec. 1, last paragraph), so a second setting would not
  change any claim" lets the reviewer decide.
- **Do not argue with tone or restate the reviewer's point.** The reviewer knows its point.
  Spend the words on what changed.
- **Disagreeing is an answer.** When the authors think a point is wrong, the row is
  `not-changed` with the reason in `why_not` and `disagree` true; the reviewer then decides
  between `reason-accepted` and `not-resolved`. There is no separate action for it, because
  the paper did not change.
- **Out-of-reach requests** get a row like any other: what was done within reach (a
  narrowed claim, a stated limitation, a plan) and `out_of_reach` true. Mark only requests
  that are in the plan's `out_of_reach` list for this round; the authors' text alone does
  not make a request out of reach, and the ledger warns when the plan lists nothing.
- **Changes in the supplement** count like changes in the paper: give the supplement's
  section and page in `where` and quote its text. The quote check covers the supplement
  when it was extracted with the manuscript, and the report shows where the quote was found.
- **Write it after the revision is final.** A response drafted against a PDF that then
  changes again will quote text that is no longer there; rerun `check_quotes.py` after the
  last edit.
