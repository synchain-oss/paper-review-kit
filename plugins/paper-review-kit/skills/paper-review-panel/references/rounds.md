# Rounds: the multi-round protocol

Contents: 1 What a round is · 2 Who reviews in round k · 3 What returning reviewers may add
· 4 The ledger · 5 Triage and the fix plan · 6 Reading fresh against returning reviewers ·
7 The per-round change statement · 8 Stopping · 9 Comparing seats and methods ·
10 Checklist for round k

## 1. What a round is

A round is one version of the manuscript and the reviews of that version. Round 1 reviews
the first version. Round k (k ≥ 2) reviews the version revised after round k-1, and its
folder also holds the authors' response that came with that version. Everything a round's
reviewers receive and produce lives in its folder, so a round can be audited on its own.

## 2. Who reviews in round k

- **Returning reviewers**: every earlier reviewer with at least one open point. A reviewer
  whose points are all closed does not return; that saves a strong-model run and changes
  nothing. A fresh reviewer of round 2 who left open points returns in round 3, like anyone
  else. `ledger.py packets DIR --round K` lists them and writes their packets.
- **Fresh reviewers**: new ids, new contexts, and only the current PDF, in every round. By
  default one per round-1 seat, so that each seat has a fresh and a returning reading to
  compare. When the budget is tight, keep at least one fresh reviewer: without one,
  anchoring and capitulation cannot be detected (the report says so).
- **Inputs of a returning reviewer in round k**: its own reviews from every earlier round
  (for a converted round, also the original), its points packet (open points with title,
  why, quote, resolution and its own earlier statuses, its latest scores, the out-of-reach
  list), its response packet (the authors' rows for its points, plus the changes they list
  as unrelated to any point), the round k-1 and round k versions with any supplement, and
  the round k text layer for copying quotes. `ledger.py rooms` puts exactly these into the
  reviewer's room. Not the other reviewers' points, the checks, the triage or the report:
  those carry the coordinator's and other reviewers' views.
- **Inputs of a fresh reviewer**: the current version with any supplement and its text
  layer, as `manuscript.pdf` and `supplement.pdf`, in a room whose path says nothing about
  rounds or versions and whose parent holds no returning room (`--fresh-out`).
- **A returning external-protocol seat** returns like any other seat, without the protocol
  files: judging one's own points against a revision is the panel's task, not the method's.

## 3. What returning reviewers may add

Only two kinds of new point:

- `introduced-by-revision`: the new text causes the problem. These are the revision's
  cost, and the per-round statement counts them.
- `missed-earlier`: the problem was already in the earlier version. Allowed, because hiding
  a real problem helps nobody, but labelled, so that the user can see the reviewer
  extending its list. A rising count of these across rounds is a sign of goalposts moving.

Everything else is ruled out: new requests on a point already resolved, raising the bar on
an open point beyond the step-1 criterion, and general wishes. Fresh reviewers, who have no
earlier list, may raise anything; that is their job.

## 4. The ledger

`ledger.py build DIR` rebuilds `ledger.json` from the round folders each time. Nobody edits
it, so it cannot disagree with the files.

- **Ids** are the reviewers' own (`R2.3`) and never change. Duplicates across reviewers are
  joined by the coordinator's `same_as`, not by renumbering.
- **Status per round**: a point starts `open` (or `withdrawn` if the reviewer's own
  counter-evidence step, or the quote repair, dropped it; the two are counted apart). Each
  round its reviewer returns, it gets `resolved`, `partly`, `not-resolved`,
  `reason-accepted` or `withdrawn` (the reviewer concedes the paper already answered it).
  In rounds where the reviewer does not return, the status carries forward.
- **Open** means the latest status is `open`, `partly` or `not-resolved`, or `resolved` or
  `withdrawn` without a found quote of the revised text (`resolved-unverified`,
  `withdrawn-unverified`): closing a point needs verbatim support.
- **Severity now**: a point counts at the severity it was raised with, until its reviewer
  judges it `partly` with a `remaining_severity`; from then on it counts at that level
  (never higher than raised). The report shows both ("was must-fix; what remains:
  should-fix"). Without the field nothing changes.
- **Pending** (what the stopping rule counts) means open and not set aside by the
  coordinator, or kept on the change list by the coordinator in the latest triage (for
  example when the resolution check disputes a `resolved`).
- **Warnings** to act on before triage: response rows missing for open points, response
  quotes not found in the revised PDF, open points a returning reviewer did not judge, new
  points without a valid origin, scores that moved without naming status changes, must-fix
  points without a counter-evidence search (not for reviews marked `converted`), quotes
  matched only loosely or stitched from fragments, checker refutations without a found
  quote, response rows marked out of reach when the plan lists nothing for the round, rows
  that say `changed` and `disagree` at once, and triage of ids no reviewer raised.
- **The search audit.** `check_quotes.py` audits the queries each reviewer lists. Where the
  host keeps transcripts, the coordinator reads every web request each reviewer actually
  sent (search queries, fetched URLs and a fetch tool's prompts, which leave the machine
  too) and writes them to `round-k/queries.json` (`schemas.md` section 10). The script then
  audits every one of them, listed or not, and lists the requests a reviewer did not report
  (only the same text counts as reported; a listed search with a word added is a different
  request); the report shows them. Read the transcripts for file reads too: a reviewer that opened a file outside its
  room is named in `launch.notes`.

## 5. Triage and the fix plan

Triage is your only contribution, and it is bookkeeping with reasons, not review. It
takes two passes, because the check on capitulation (section 6) can only see duplicates
that are already linked:

- **Pass 1, links.** In `synthesis.json`, mark `same_as` for every point that repeats
  another: within the round, and every fresh point that repeats an earlier point, open or
  closed. No groups yet. Run `ledger.py build` and `render_report.py`, and read the
  fresh-against-returning section.
- **Pass 2, groups.** Triage the first point of each group (the others inherit it). Put
  each new or still-open point in one group: `change`, `author-decision` (trade-offs,
  scope, disagreements between reviewers, anything needing new work), or `not-recommended`
  (with a reason the user can check: the manuscript already answers it, as the checker
  quoted; it asks for something outside the paper's claims; it conflicts with another
  point; its quote could not be found even after the repair pass). A point the checker did
  not uphold is not dropped silently: it goes to `not-recommended` with the checker's quote
  as the reason, and the user can overrule. A `not-upheld` verdict counts only with a quote
  that `check_quotes.py` found; without one the ledger reads it as `unclear`, and it is no
  reason to set the point aside.
- After a revision, the triage is the fix plan: each point ends as `done` (made, or
  confirmed resolved by its reviewer), `author-decision`, or `not-recommended`; `change`
  holds only what is still to do. Points confirmed resolved, or whose reason was accepted,
  move automatically when your latest triage does not mention them.
- Keep the change list short. Minor points can stay in the appendix unless they are cheap.
- A factual note of yours on a point (a reviewer's inference is wrong in size though its
  request is right) goes into `reason`. It says where the fact comes from (a table of the
  revised version, a stored result the user showed you) and is not a new criticism: it
  does not add a request, raise a severity or change a score.

## 6. Reading fresh against returning reviewers

Fresh reviewers saw only the revised PDF; returning reviewers saw their own history and the
response. Differences between them are the panel's check on itself. After pass 1 of the
triage and before pass 2, look at the report's "Fresh against returning reviewers" section:

| What you see | Likely cause | What to do |
|---|---|---|
| A fresh reviewer re-raises a point a returning reviewer marked resolved or withdrew | capitulation: the resolution was accepted on the response's word, or is partial | move the point back to `change` with the fresh quote as reason; mention it in the report |
| Returning reviewers' overall rises well above fresh reviewers' of the same seat | capitulation, or a fresh reviewer that is harsher by chance | look at the status changes named in `score_changes`; trust the statuses, not the levels |
| Fresh reviewers raise serious, upheld points that no returning reviewer raised | anchoring or fatigue of returning reviewers, or a genuinely new reading | treat the points on their merits; note the pattern |
| A returning reviewer marks nearly everything not-resolved while the fresh reviewers find little | anchoring on the first verdict | check the step-1 criteria against the earlier review; a raised bar is a moving goalpost |
| Fresh and returning agree | the healthy case | nothing |

One fresh reviewer is one reading; do not over-interpret a single disagreement. In the
table of serious new points, a group of duplicates shows its head's check verdict and says
how many members' verdicts differ; when they differ, read those members' checks before
relying on the group's verdict.

## 7. The per-round change statement

For every round from 2 on, write `statement` in `synthesis.json` in plain words: what the
revision actually changed in the paper (sections rewritten, analyses added, claims
narrowed), and anything it broke, if it broke anything. The report places it next to the
ledger's counts: points
resolved and partly resolved, points introduced by the revision, response rows by action,
open must-fix before and after. The ledger flags two churn patterns: changes reported but
nothing confirmed resolved, and as many points introduced as resolved. A round that only
moved text around should read as such.

## 8. Stopping

Agree the rule in `plan.json` before round 1; after that, apply it as written. Default:
stop when any of these holds.

1. **No pending must-fix point.** Points set aside as `not-recommended` with a reason do not
   count; the report lists them for the user. A must-fix point judged `partly` with a lower
   `remaining_severity` no longer counts as must-fix.
2. **The round's fresh reviewers raised nothing new that survives checking**, counting
   must-fix and should-fix points only. A fresh point counts as new unless it duplicates a
   point still open from an earlier round; a fresh point that re-raises a closed point
   counts, because it says the closing may be wrong. A checker's `unclear` counts as
   surviving. Duplicates count once: a group survives when any of its fresh must-fix or
   should-fix members does, since one refuted copy does not remove an upheld one. Points
   not yet checked block this condition until they are.
3. **The agreed maximum number of rounds, or the budget, is reached.**

`ledger.py build` prints which hold. Recommend stop or continue in `synthesis.json`
(`stop.decision` and a one-line note); the user decides. Stopping does not mean the paper
is good; it means another round is unlikely to improve it.

## 9. Comparing seats and methods

The report's seat table counts, per reviewer: points raised, points withdrawn by the
reviewer's own self-check, points withdrawn on quote repair (kept apart, so that a method
that invents quotes does not look as if its self-check works), quotes found, points upheld
by the checker (and how many were checked), points upheld that no other reviewer raised,
must-fix points upheld, and the overall level per round.

To compare an external method with the built-in seats:

- Add it as an extra fresh seat in the same round, with its own seat name (for example
  `external-<name>`), on the same model and effort, with the same manuscript, so that the
  method is the only difference. It does not replace a built-in seat: each built-in seat
  keeps its own fresh-against-returning comparison.
- Read the counts together: many points with few upheld is noise; few points with many
  upheld and unique is the useful profile; a high withdrawal count means the method's
  self-check is doing work (or that it over-generates first).
- Then read its unique upheld points yourself: are they real, and would the authors act on
  them? That judgement, not the counts, decides whether the method is worth keeping.
- A single run per method on a single paper is an anecdote. Two runs per method show how
  much of the difference is chance.

## 10. Checklist for round k (k ≥ 2)

1. Before the revision: agree with the user what cannot be done this round and record it in
   `plan.json` (`out_of_reach`, keyed by the round number).
2. `round-k/manuscript.pdf` (revised) and any supplement, `extract_text.py` on all of them
   (manuscript first), `round-k/response.json`.
3. `check_quotes.py round-k` and fix any response row whose quote is not found.
4. `ledger.py rooms DIR --round k --out ROOMS --fresh-out FRESH --fresh <seat> ...
   [--external <seat> ...]`, FRESH a neutral path unrelated to ROOMS (a fresh room must not
   have returning rooms as siblings); note the returning reviewers and the fresh ids; fill
   each external seat's `protocol/` folder.
5. Briefs by room: returning (section 5 of `reviewer-briefs.md`) and fresh (sections 3 and
   4, no hint of a revision), plus any external seat; models set on every launch.
6. Launch; save reviews unedited.
7. `check_quotes.py round-k`; one repair pass; checks (a finding check for every fresh
   must-fix and should-fix point, resolution, literature; batches of about twenty items,
   split by reviewer); `queries.json` from the transcripts where there are any;
   `check_quotes.py round-k` again.
8. `ledger.py build DIR`; act on its warnings.
9. Triage pass 1 (`same_as` marks only), `ledger.py build`, `render_report.py`; read fresh
   against returning.
10. Triage pass 2: groups, the statement and the stop recommendation in
    `round-k/synthesis.json`.
11. `ledger.py build DIR`, `render_report.py DIR --lang <xx>`; report to the user.
