#!/usr/bin/env python3
"""Keep the issue ledger of a multi-round review, and prepare returning-reviewer packets.

usage:
  ledger.py build REVIEW_DIR
      Rebuild REVIEW_DIR/ledger.json from every round-<k> folder and print per-round
      status counts, what is still open, the stopping-rule check and any warnings.
  ledger.py packets REVIEW_DIR --round K
      For every earlier reviewer with open points, write
      REVIEW_DIR/round-K/packets/<RID>-points.md   (its own open points with title, why,
                                                    quote, resolution and latest status,
                                                    and its latest scores; read first)
      REVIEW_DIR/round-K/packets/<RID>-response.md (the authors' rows for those points)
      from the ledger up to round K-1 and REVIEW_DIR/round-K/response.json.
  ledger.py rooms REVIEW_DIR --round K --out ROOMS [--fresh-out FRESH_ROOMS]
                  [--fresh SEAT ...] [--external SEAT ...]
      Build one folder per reviewer of round K, ROOMS/<RID>/, holding only that reviewer's
      files, and print the paths to put into the briefs. A returning reviewer (every
      earlier reviewer with an open point; K >= 2) gets its earlier review file(s) as
      returned (and a converted review's original, when converted_from names a file in
      REVIEW_DIR/earlier/), points.md, response.md, previous/ and revised/ (manuscript
      PDF and any supplement) and revised/manuscript.txt, the text layer for copying
      quotes. Each fresh reviewer named by a seat gets the next free id and the
      manuscript as manuscript.pdf (any supplement as supplement.pdf) with its text
      layer; an --external seat also gets an empty protocol/ folder for the coordinator
      to fill. A fresh room must not have returning rooms as siblings: when a round has
      both, the fresh rooms go under FRESH_ROOMS/<RID>/, a parent apart from ROOMS
      (required then). Choose neutral paths for the fresh rooms (no "round", "revised"
      or version in them): fresh reviewers see them. The list of rooms is recorded in
      REVIEW_DIR/round-K/rooms.json, outside the rooms.

The ledger is derived, never edited: it is rebuilt from the reviews, quotes.json,
checks.json, response.json and synthesis.json of each round, so it cannot drift from
them. Ids are the reviewers' finding ids ("R2.3"); they stay the same in every round. A
reviewer's id is its review file's name; ids of any other form are skipped with a warning.

A point counts as open when its latest status is open, partly or not-resolved, or when it
is marked resolved (or withdrawn by its reviewer on re-reading) but the quote of the
revised text was not found by check_quotes.py: closing a point needs verbatim support.
A point judged partly may carry remaining_severity: from then on it counts at that
severity (a must-fix point whose remainder is should-fix is no longer an open must-fix
point), and the report shows both. For the stopping rule, points the coordinator set
aside as not-recommended, with a reason, are not counted; the report lists them so the
user can overrule. A checker's "not upheld" counts only when its own quote was found;
otherwise it is read as "unclear". A review marked "converted": true (written before the
skill, or by hand) draws no warning about missing counter-evidence searches.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    ACTIONS,
    CHECK_KINDS,
    FINDING_TYPES,
    GROUPS,
    JUDGEMENTS,
    OPEN_STATUSES,
    ORIGINS,
    POINT_RE,
    QUOTED_JUDGEMENTS,
    RID_RE,
    SCORE_DIMENSIONS,
    SEVERITIES,
    VERDICTS,
    PageMap,
    as_dict,
    as_list,
    die,
    enum_key,
    extra_scores_of,
    is_converted,
    is_small_value,
    level_of,
    load_reviews,
    norm_enum,
    normalise_severity,
    read_json_optional,
    review_findings,
    review_judgements,
    review_kind,
    reviewer_ids_on_disk,
    rid_number,
    round_dirs,
    safe_console,
    severity_rank,
    text_of,
    write_json,
    write_text,
)

FOUND = ("found", "found-loose")
CLOSING_JUDGEMENTS = ("resolved", "withdrawn")  # close a point only with a found quote
PLAN_KEYS_FOR_REPORT = ("label", "language", "venue", "reviewer_model", "checker_model", "web",
                        "max_rounds", "budget", "stopping_rule", "unpublished", "extra_score_sheet", "seat_names")


def quote_map(quotes: dict | None) -> dict[tuple[str, str, str], dict] | None:
    if not isinstance(quotes, dict):
        return None
    out = {}
    for entry in as_list(quotes.get("results")):
        if isinstance(entry, dict):
            out[(text_of(entry.get("source")), text_of(entry.get("field")), text_of(entry.get("id")))] = entry
    return out


def unverified(h: dict) -> bool:
    """A judgement that would close the point, but whose quote of the revised text was not found."""
    return h.get("event") == "judged" and h["status"] in CLOSING_JUDGEMENTS and h.get("quote_check") not in FOUND


def history_status(h: dict) -> str:
    return f"{h['status']}-unverified" if unverified(h) else h["status"]


def is_open(entry: dict) -> bool:
    last = entry["history"][-1]
    return last["status"] in OPEN_STATUSES or unverified(last)


def effective_status(entry: dict) -> str:
    return history_status(entry["history"][-1])


def current_severity(entry: dict) -> str:
    """The severity a point counts at now: the raised one, or what remains after a `partly`.

    The latest remaining_severity a returning reviewer gave (on a `partly` judgement)
    stands until a later one replaces it; it is never above the severity raised.
    """
    for h in reversed(entry["history"]):
        if h.get("remaining_severity"):
            return h["remaining_severity"]
    return entry["severity"]


class Groups:
    """Duplicate points joined through the coordinator's same_as marks."""

    def __init__(self, issues: dict[str, dict]) -> None:
        self.parent = {iid: iid for iid in issues}
        for iid, entry in issues.items():
            target = entry.get("same_as")
            if target and target in issues and target != iid:
                self._union(iid, target)
        self.members: dict[str, list[str]] = {}
        for iid in issues:
            self.members.setdefault(self.find(iid), []).append(iid)

    def find(self, iid: str) -> str:
        while self.parent[iid] != iid:
            self.parent[iid] = self.parent[self.parent[iid]]
            iid = self.parent[iid]
        return iid

    def _union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def group_view(issues: dict[str, dict], last_round: int) -> list[dict]:
    """One record per group of duplicates, with the coordinator's current disposition.

    A point marked same_as another, without a group of its own, inherits the group's
    triage: the most recent triage of any member (the group's root wins a tie).
    """
    groups = Groups(issues)
    out = []
    for root, member_ids in groups.members.items():
        members = sorted((issues[m] for m in member_ids), key=lambda e: (e["raised_in"], rid_number(e["reviewer"]), e["id"]))
        triaged = [m for m in members if m["triage"]]
        canonical = max(triaged, key=lambda m: (m["triage"][-1]["round"], m["id"] == root)) if triaged else issues[root]
        triage = canonical["triage"][-1] if canonical["triage"] else None
        open_members = [m for m in members if is_open(m)]
        activity = max(h["round"] for m in members for h in m["history"])
        if open_members:
            severity = min((current_severity(m) for m in open_members), key=severity_rank)
            raised_severity = min((m["severity"] for m in open_members), key=severity_rank)
        else:
            severity = raised_severity = min((m["severity"] for m in members), key=severity_rank)
        if not open_members and (triage is None or triage["round"] < activity):
            last = [m["history"][-1] for m in members]
            statuses = {h["status"] for h in last}
            if "resolved" in statuses:
                disposition, reason = "done", "resolved, confirmed by the reviewer with a quote of the revised text"
            elif "reason-accepted" in statuses:
                disposition, reason = "not-recommended", "the authors' reason for not changing was accepted by the reviewer"
            elif any(h.get("event") == "judged" for h in last):
                disposition, reason = "withdrawn", "withdrawn by its reviewer on re-reading: the paper already answered it"
            elif all(m.get("withdrawn_on_repair") for m in members):
                disposition, reason = "withdrawn", "withdrawn on quote repair: no verbatim passage supports it"
            else:
                disposition, reason = "withdrawn", "withdrawn by the reviewer"
            auto = True
        elif triage:
            disposition, reason, auto = triage["group"], triage.get("reason", ""), False
        else:
            disposition, reason, auto = "untriaged", "", False
        set_aside = disposition == "not-recommended" and bool(reason) and bool(open_members)
        out.append({
            "id": canonical["id"],
            "members": [m["id"] for m in members],
            "reviewers": sorted({m["reviewer"] for m in members}, key=rid_number),
            "severity": severity,
            "raised_severity": raised_severity,
            "open": bool(open_members),
            "disposition": disposition,
            "reason": reason,
            "automatic": auto,
            "triaged_in": triage["round"] if triage else None,
            "stale": bool(triage and not auto and triage["round"] < last_round and open_members),
            "set_aside": set_aside,
            # Still to do: open and not set aside, or kept on the list by the coordinator
            # (for example when a checker disputes a resolution). Used by the stopping rule.
            "pending": (bool(open_members) and not set_aside)
            or (disposition in ("change", "author-decision") and not auto and triage is not None
                and triage["round"] >= activity),
        })
    out.sort(key=lambda g: (severity_rank(g["severity"]), -len(g["reviewers"]), g["id"]))
    return out


class QuoteLookup:
    """(status, stitched) of one quote in a round's quotes.json; warns about loose and stitched matches."""

    def __init__(self, quotes: dict, warnings: list[str]) -> None:
        self.quotes, self.warnings = quotes, warnings

    def __call__(self, key: tuple[str, str, str], label: str, default: str = "unchecked") -> tuple[str, bool]:
        entry = self.quotes.get(key)
        if entry is None:
            return default, False
        status = text_of(entry.get("status")) or default
        if status == "found-loose":
            self.warnings.append(f"{label}: quote matched only loosely (case, spacing or punctuation differ); glance at it")
        if entry.get("stitched"):
            self.warnings.append(f"{label}: quote stitched from short or distant fragments; check that together they say what is claimed")
        return status, bool(entry.get("stitched"))

    def location(self, key: tuple[str, str, str]) -> dict | None:
        """Where the quote was found, when a page map says which document: {document, index, page}."""
        entry = self.quotes.get(key) or {}
        if entry.get("document") is None or entry.get("status") not in FOUND:
            return None
        return {"document": entry["document"], "index": entry.get("document_index", 0), "page": entry.get("document_page")}


def add_location(target: dict, location: dict | None) -> None:
    if location:
        target["quote_location"] = location


def counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def build(review_dir: Path, upto: int | None = None) -> dict:
    plan = as_dict(read_json_optional(review_dir / "plan.json"))
    warnings: list[str] = []
    issues: dict[str, dict] = {}
    reviewers: dict[str, dict] = {}
    rounds_out: list[dict] = []
    prev_open_must = 0
    rounds = [(k, d) for k, d in round_dirs(review_dir) if upto is None or k <= upto]
    if not rounds and upto is None:
        die(f"{review_dir}: no round-<k> folders")

    for k, rdir in rounds:
        load_warnings: list[str] = []
        reviews = load_reviews(rdir, load_warnings)
        warnings += load_warnings
        quotes = quote_map(read_json_optional(rdir / "quotes.json"))
        has_quotes = quotes is not None
        if reviews and quotes is None:
            warnings.append(f"{rdir.name}: no quotes.json; run check_quotes.py (until then no quote counts as found)")
        quotes = quotes or {}
        quote_check = QuoteLookup(quotes, warnings)

        checks: dict[tuple[str, str], dict] = {}
        for c in as_list(as_dict(read_json_optional(rdir / "checks.json")).get("checks")):
            if not isinstance(c, dict) or not text_of(c.get("id")).strip():
                continue
            iid = text_of(c.get("id")).strip()
            label = f"{rdir.name}/checks.json: {iid}"
            kind = norm_enum(c.get("kind") or "finding", CHECK_KINDS, warnings, f"{label}: kind") or "finding"
            verdict = norm_enum(c.get("verdict"), VERDICTS, warnings, f"{label}: verdict")
            downgraded = False
            if verdict == "not-upheld" and kind in ("finding", "resolution"):
                if text_of(c.get("quote")).strip():
                    qc, _ = quote_check(("checks", f"check:{kind}", iid), f"{label} (checker)")
                else:
                    qc = "missing"
                if qc not in FOUND:
                    hint = " (run check_quotes.py after writing checks.json)" if qc == "unchecked" else ""
                    warnings.append(f"{label}: 'not upheld' without a found quote (quote {qc}){hint}; counted as unclear")
                    verdict, downgraded = "unclear", True
            checks[(iid, kind)] = {"verdict": verdict, "note": text_of(c.get("note")), "downgraded": downgraded}

        synthesis = as_dict(read_json_optional(rdir / "synthesis.json"))
        response = read_json_optional(rdir / "response.json")
        open_before = {iid for iid, e in issues.items() if is_open(e)}

        # The authors' response to the points still open before this round.
        response_actions: list[str] = []
        other_changes = 0
        if isinstance(response, dict):
            answered = set()
            for answer in as_list(response.get("answers")):
                if not isinstance(answer, dict):
                    continue
                iid = text_of(answer.get("id")).strip()
                label = f"{rdir.name}/response.json: {iid}"
                action = norm_enum(answer.get("action"), ACTIONS, warnings, f"{label}: action") or enum_key(answer.get("action"))
                if iid not in issues:
                    warnings.append(f"{rdir.name}/response.json: row for {iid!r}, which no reviewer raised")
                    continue
                answered.add(iid)
                response_actions.append(action)
                qc, _ = quote_check(("response", "response", iid), label)
                if action in ("changed", "partly") and not text_of(answer.get("where")):
                    warnings.append(f"{label} says {action} but gives no place")
                if action in ("changed", "partly") and qc not in FOUND:
                    warnings.append(f"{label} says {action}; its quote of the new text is {qc}")
                if action == "not-changed" and not text_of(answer.get("why_not")):
                    warnings.append(f"{label} not changed and no reason given")
                disagree = answer.get("disagree") is True
                if disagree and action == "changed":
                    warnings.append(f"{label} says changed but also disagree; a disagreement is not-changed (or partly) with the reason in why_not")
                if disagree and not text_of(answer.get("why_not")):
                    warnings.append(f"{label}: the authors disagree but give no reason in why_not")
                if answer.get("out_of_reach") is True and not as_list(as_dict(plan.get("out_of_reach")).get(str(k))):
                    warnings.append(f"{label} is marked out of reach, but plan.json lists nothing out of reach for round {k}; "
                                    "agree the list with the user and record it under out_of_reach")
                row = {
                    "round": k, "action": action, "what": text_of(answer.get("what")),
                    "where": text_of(answer.get("where")), "why_not": text_of(answer.get("why_not")),
                    "out_of_reach": bool(answer.get("out_of_reach")), "quote_check": qc,
                }
                if disagree:
                    row["disagree"] = True
                add_location(row, quote_check.location(("response", "response", iid)))
                issues[iid]["response"].append(row)
            other_changes = len(as_list(response.get("other_changes")))
            unanswered = sorted(open_before - answered)
            if unanswered:
                warnings.append(f"{rdir.name}/response.json: no row for open point(s) {', '.join(unanswered)}")
        elif k > 1 and open_before:
            warnings.append(f"{rdir.name}: no response.json although {len(open_before)} point(s) were open")

        judged_now: list[str] = []
        judged_statuses: list[str] = []
        for rid, review in reviews.items():
            kind = review_kind(review)
            info = reviewers.setdefault(rid, {
                "reviewer": rid, "seat": text_of(review.get("seat")), "protocol": text_of(review.get("protocol")) or "built-in",
                "first_round": k, "rounds": {}, "scores": {}, "file": {},
            })
            if kind == "fresh" and info["first_round"] != k:
                warnings.append(f"{review['_file']}: fresh review under an id used in round {info['first_round']}; give fresh reviewers new ids")
            if kind == "returning" and info["first_round"] == k:
                warnings.append(f"{review['_file']}: returning review, but {rid} has no earlier round")
            info["rounds"][k] = kind
            info["file"][k] = review["_file"]
            converted = is_converted(review)
            if converted:
                info.setdefault("converted", []).append(k)
                if text_of(review.get("converted_from")).strip():
                    info.setdefault("converted_from", {})[k] = text_of(review.get("converted_from")).strip()

            if kind == "returning":
                criteria = {text_of(c.get("id")).strip() for c in as_list(review.get("criteria")) if isinstance(c, dict)}
                judged = set()
                for j in review_judgements(review):
                    iid = text_of(j.get("id")).strip()
                    label = f"{review['_file']}: {iid}"
                    if iid not in issues:
                        warnings.append(f"{review['_file']}: judgement for unknown point {iid!r}")
                        continue
                    if issues[iid]["reviewer"] != rid:
                        warnings.append(f"{review['_file']}: judges {iid}, which belongs to {issues[iid]['reviewer']}; ignored")
                        continue
                    if iid in judged:
                        warnings.append(f"{label}: judged twice; the first judgement counts")
                        continue
                    status = norm_enum(j.get("status"), JUDGEMENTS, warnings, f"{label}: status")
                    if status is None:
                        continue
                    if iid not in criteria and not converted:
                        warnings.append(f"{label} judged without a step-1 criterion")
                    remaining = None
                    if text_of(j.get("remaining_severity")).strip():
                        if status != "partly":
                            warnings.append(f"{label}: remaining_severity is read only on a partly judgement; ignored")
                        else:
                            remaining = norm_enum(j.get("remaining_severity"), SEVERITIES, warnings,
                                                  f"{label}: remaining_severity")
                            raised_at = issues[iid]["severity"]
                            if remaining and severity_rank(remaining) < severity_rank(raised_at):
                                warnings.append(f"{label}: remaining_severity {remaining} is above the severity raised "
                                                f"({raised_at}); counted as {raised_at}")
                                remaining = raised_at
                    quote = text_of(j.get("quote"))
                    if status in QUOTED_JUDGEMENTS and not quote.strip():
                        qc, stitched = "missing", False
                    else:
                        qc, stitched = quote_check((rid, "judgement", iid), label,
                                                   "unchecked" if status in QUOTED_JUDGEMENTS else "not-needed")
                    rcheck = checks.get((iid, "resolution"))
                    entry = {
                        "round": k, "event": "judged", "status": status, "by": rid, "where": text_of(j.get("where")),
                        "quote": quote, "quote_check": qc, "quote_stitched": stitched, "note": text_of(j.get("note")),
                        "response_check": text_of(j.get("response_check")),
                        "check": rcheck["verdict"] if rcheck else None,
                        "check_note": rcheck["note"] if rcheck else "",
                        "check_downgraded": bool(rcheck and rcheck["downgraded"]),
                    }
                    if remaining:
                        entry["remaining_severity"] = remaining
                    add_location(entry, quote_check.location((rid, "judgement", iid)))
                    issues[iid]["history"].append(entry)
                    judged.add(iid)
                    judged_now.append(iid)
                    judged_statuses.append(history_status(entry))
                skipped = sorted(i for i in open_before if issues[i]["reviewer"] == rid and i not in judged)
                if skipped:
                    warnings.append(f"{review['_file']}: open point(s) not judged: {', '.join(skipped)} (status carried forward)")

            for f in review_findings(review):
                iid = text_of(f.get("id")).strip()
                match = POINT_RE.match(iid)
                if not match or match.group(1) != rid:
                    warnings.append(f"{review['_file']}: point id {iid!r} is not of the form {rid}.<n>; skipped")
                    continue
                if iid in issues:
                    warnings.append(f"{review['_file']}: id {iid} already used in round {issues[iid]['raised_in']}; skipped")
                    continue
                ftype = norm_enum(f.get("type"), FINDING_TYPES, warnings, f"{review['_file']}: {iid}: type") or enum_key(f.get("type"))
                severity, recognised = normalise_severity(f.get("severity"))
                if not recognised:
                    warnings.append(f"{review['_file']}: {iid}: severity {f.get('severity')!r} is not one of {SEVERITIES}; read as {severity}")
                if kind == "fresh":
                    origin = "first-read"
                else:
                    raw_origin = text_of(f.get("origin"))
                    origin = enum_key(raw_origin)
                    if origin not in ORIGINS[1:]:
                        warnings.append(f"{review['_file']}: new point {iid} must be marked introduced-by-revision or missed-earlier (got {raw_origin!r})")
                    elif origin != raw_origin:
                        warnings.append(f"{review['_file']}: {iid}: origin {raw_origin!r} read as {origin!r}")
                status = "withdrawn" if enum_key(f.get("status")) == "withdrawn" else "open"
                on_repair = status == "withdrawn" and bool(f.get("withdrawn_on_repair"))
                counter = as_dict(f.get("counter_evidence"))
                if severity == "must-fix" and status == "open" and not text_of(counter.get("looked_at")) and not converted:
                    warnings.append(f"{review['_file']}: must-fix {iid} has no counter-evidence search recorded")
                if not text_of(f.get("resolution")) and status == "open":
                    warnings.append(f"{review['_file']}: {iid} does not say what change would resolve it")
                if status == "open":
                    qc, stitched = quote_check((rid, "finding", iid), f"{review['_file']}: {iid}")
                else:
                    entry = quotes.get((rid, "finding", iid))
                    qc, stitched = (text_of(entry.get("status")), bool(entry.get("stitched"))) if entry else ("unchecked", False)
                fcheck = checks.get((iid, "finding"))
                lcheck = checks.get((iid, "literature"))
                issues[iid] = {
                    "id": iid, "reviewer": rid, "seat": info["seat"], "protocol": info["protocol"],
                    "raised_in": k, "origin": origin, "type": ftype, "severity": severity,
                    "title": text_of(f.get("title")), "where": text_of(f.get("where")),
                    "quote": text_of(f.get("quote")), "quote_check": qc, "quote_stitched": stitched,
                    "quote_repaired": bool(f.get("quote_repaired")),
                    "why": text_of(f.get("why")), "resolution": text_of(f.get("resolution")),
                    "needs_new_work": bool(f.get("needs_new_work")),
                    "counter_evidence": counter, "looked_for": text_of(f.get("looked_for")),
                    "literature": [x for x in as_list(f.get("literature")) if isinstance(x, dict)],
                    "withdrawn_on_repair": on_repair,
                    "withdrawn_reason": (text_of(f.get("withdrawn_reason")) or text_of(counter.get("note")))
                    if status == "withdrawn" else "",
                    "check": fcheck["verdict"] if fcheck else None,
                    "check_note": fcheck["note"] if fcheck else "",
                    "check_downgraded": bool(fcheck and fcheck["downgraded"]),
                    "literature_check": lcheck["verdict"] if lcheck else None,
                    "history": [{"round": k, "event": "raised", "status": status, "by": rid, "quote_check": qc}],
                    "response": [], "triage": [], "same_as": None,
                }
                if f.get("quote_chosen") is True:
                    issues[iid]["quote_chosen"] = True  # passage chosen by the coordinator during a conversion
                add_location(issues[iid], quote_check.location((rid, "finding", iid)))

            scores = as_dict(review.get("scores"))
            record = {"kind": kind, "overall": level_of(review.get("overall")),
                      "confidence": level_of(review.get("confidence")),
                      "dimensions": {d: level_of(scores.get(d)) for d in SCORE_DIMENSIONS}}
            extra = extra_scores_of(review)
            if extra:
                record["extra"] = extra
            if record["overall"] is None:
                warnings.append(f"{review['_file']}: no overall level")
            earlier = [r for r in info["scores"] if r < k]
            if kind == "returning" and earlier:
                before = info["scores"][max(earlier)]["overall"]
                changes = [c for c in as_list(review.get("score_changes")) if isinstance(c, dict)]
                if before != record["overall"] and not any(as_list(c.get("because")) for c in changes):
                    warnings.append(f"{review['_file']}: overall moved {before} -> {record['overall']} without naming the status changes behind it")
                record["changes"] = changes
            info["scores"][k] = record

        for (iid, kind), c in checks.items():
            if iid not in issues:
                warnings.append(f"{rdir.name}/checks.json: check for unknown point {iid!r}")
            elif kind == "finding" and issues[iid]["check"] is None:
                issues[iid]["check"], issues[iid]["check_note"] = c["verdict"], c["note"]
                issues[iid]["check_downgraded"] = c["downgraded"]
            elif kind == "literature" and issues[iid]["literature_check"] is None:
                issues[iid]["literature_check"] = c["verdict"]
            elif kind == "resolution" and iid not in judged_now:
                warnings.append(f"{rdir.name}/checks.json: resolution check for {iid}, which was not judged this round")

        same_as_marks = 0
        for item in as_list(synthesis.get("items")):
            if not isinstance(item, dict):
                continue
            iid = text_of(item.get("id")).strip()
            label = f"{rdir.name}/synthesis.json: {iid}"
            if iid not in issues:
                warnings.append(f"{rdir.name}/synthesis.json: {iid!r} is not a point any reviewer raised; the synthesis may only triage reviewers' points")
                continue
            same_as = text_of(item.get("same_as")).strip() or None
            if same_as and (same_as not in issues or same_as == iid):
                warnings.append(f"{label}: same_as {same_as!r} is not another known point")
                same_as = None
            if same_as:
                issues[iid]["same_as"] = same_as
                same_as_marks += 1
            if not text_of(item.get("group")).strip():
                if not same_as:
                    warnings.append(f"{label}: neither a group nor a same_as mark")
                continue  # a duplicate without a group inherits its group's triage
            group = norm_enum(item.get("group"), GROUPS, warnings, f"{label}: group")
            if group is None:
                continue
            reason = text_of(item.get("reason"))
            if group in ("not-recommended", "author-decision") and not reason:
                warnings.append(f"{label} is {group} without a reason")
            issues[iid]["triage"].append({"round": k, "group": group, "reason": reason, "same_as": same_as})

        groups = group_view(issues, k)
        for g in groups:
            if g["set_aside"] and g["triaged_in"] == k and any(issues[m]["check_downgraded"] for m in g["members"]):
                warnings.append(f"{rdir.name}/synthesis.json: {g['id']} set aside as not-recommended, but its checker's "
                                "'not upheld' has no found quote; that verdict is no reason to set it aside")
        if synthesis:
            disposition = {m: g["disposition"] for g in groups for m in g["members"]}
            untriaged = [iid for iid, e in issues.items()
                         if e["raised_in"] == k and e["history"][-1]["status"] != "withdrawn" and disposition[iid] == "untriaged"]
            if untriaged:
                warnings.append(f"{rdir.name}/synthesis.json: new point(s) not triaged: {', '.join(untriaged)}")
        elif reviews:
            warnings.append(f"{rdir.name}: no synthesis.json yet")

        open_must = [g for g in groups if g["pending"] and g["severity"] == "must-fix"]
        open_should = [g for g in groups if g["pending"] and g["severity"] == "should-fix"]
        lowered = [g["id"] for g in groups if g["pending"] and g["raised_severity"] == "must-fix" and g["severity"] != "must-fix"]
        raised = [e for e in issues.values() if e["raised_in"] == k]
        judged_counts = counts(judged_statuses)
        fresh_ids = [rid for rid, r in reviews.items() if review_kind(r) == "fresh"]
        surviving, unchecked = fresh_surviving(issues, groups, k, set(fresh_ids)) if k > 1 else ([], [])
        introduced = [e for e in raised if e["origin"] == "introduced-by-revision"]
        churn = []
        confirmed = judged_counts.get("resolved", 0) + judged_counts.get("partly", 0)
        if k > 1 and confirmed == 0 and response_actions.count("changed") + response_actions.count("partly") > 0:
            churn.append("changes-unconfirmed")
        if k > 1 and introduced and len(introduced) >= judged_counts.get("resolved", 0):
            churn.append("introduced-as-many")
        withdrawn_at_raise = [e for e in raised if e["history"][0]["status"] == "withdrawn"]
        rounds_out.append({
            "round": k,
            "reviewers": [dict({"reviewer": rid, "kind": review_kind(r), "seat": text_of(r.get("seat")),
                                "protocol": text_of(r.get("protocol")) or "built-in"},
                               **({"converted": True} if is_converted(r) else {})) for rid, r in reviews.items()],
            "raised": len(raised),
            "raised_by_severity": counts(e["severity"] for e in raised if e["history"][0]["status"] != "withdrawn"),
            "withdrawn_on_self_check": sum(1 for e in withdrawn_at_raise if not e["withdrawn_on_repair"]),
            "withdrawn_on_repair": sum(1 for e in withdrawn_at_raise if e["withdrawn_on_repair"]),
            "raised_by_origin": counts(e["origin"] for e in raised),
            "judged": judged_counts,
            "response": counts(response_actions),
            "other_changes": other_changes,
            "fresh_new_surviving": surviving,
            "fresh_new_unchecked": unchecked,
            "open_must_fix_before": prev_open_must,
            "open_must_fix_after": len(open_must),
            "open_must_fix": [g["id"] for g in open_must],
            "open_should_fix": [g["id"] for g in open_should],
            **({"must_fix_remainder_lower": lowered} if lowered else {}),
            "set_aside": [g["id"] for g in groups if g["set_aside"]],
            "churn": churn,
            "quotes_checked": has_quotes,
            "synthesis_written": bool(synthesis),
            "same_as_marks": same_as_marks,
            "statement": text_of(synthesis.get("statement")),
            "launch": as_dict(synthesis.get("launch")),
            "decision": as_dict(synthesis.get("stop")),
        })
        prev_open_must = len(open_must)

    last = rounds[-1][0] if rounds else 0
    groups = group_view(issues, last) if issues else []
    for entry in issues.values():
        entry["status"] = effective_status(entry)
        entry["open"] = is_open(entry)
        entry["current_severity"] = current_severity(entry)
    return {
        "plan": {key: plan[key] for key in PLAN_KEYS_FOR_REPORT if key in plan},
        "out_of_reach": as_dict(plan.get("out_of_reach")),
        "last_round": last,
        "rounds": rounds_out,
        "reviewers": list(reviewers.values()),
        "issues": list(issues.values()),
        "groups": groups,
        "seats": seat_table(issues, reviewers, groups),
        "fresh_vs_returning": fresh_vs_returning(issues, reviewers, groups, last, rounds_out),
        "stopping": stopping(plan, rounds_out),
        "warnings": warnings,
    }


def fresh_surviving(issues: dict[str, dict], groups: list[dict], k: int, fresh: set[str]) -> tuple[list[str], list[str]]:
    """New must-fix / should-fix points from this round's fresh reviewers that survived checking.

    A fresh point that duplicates a point still open from an earlier round is not new.
    One that re-raises a point closed earlier counts: it says the closing may be wrong.
    A point the checker could not decide ("unclear") counts as surviving: only a refutation
    with a found quote removes it. Duplicates count once per group: the group survives when
    any of its fresh must-fix or should-fix members survives (one refuted copy does not
    remove an upheld one), and is unchecked when none survives and one is not yet checked.
    """
    surviving, unchecked = [], []
    for g in groups:
        members = [issues[m] for m in g["members"]]
        if any(x["raised_in"] < k and is_open(x) for x in members):
            continue
        candidates = [x for x in members if x["raised_in"] == k and x["reviewer"] in fresh
                      and x["history"][0]["status"] != "withdrawn" and x["severity"] in ("must-fix", "should-fix")]
        alive = [x["id"] for x in candidates if x["check"] in ("upheld", "unclear")]
        if alive:
            surviving.append(alive[0])
            continue
        pending = [x["id"] for x in candidates if x["check"] is None]
        if pending:
            unchecked.append(pending[0])
    order = {e["id"]: n for n, e in enumerate(issues.values())}
    return sorted(surviving, key=order.get), sorted(unchecked, key=order.get)


def seat_table(issues: dict[str, dict], reviewers: dict[str, dict], groups: list[dict]) -> list[dict]:
    by_member = {m: g for g in groups for m in g["members"]}
    rows = []
    for rid, info in reviewers.items():
        own = [e for e in issues.values() if e["reviewer"] == rid]
        kept = [e for e in own if e["history"][0]["status"] != "withdrawn"]
        on_repair = [e for e in own if e["history"][0]["status"] == "withdrawn" and e["withdrawn_on_repair"]]
        upheld = [e for e in kept if e["check"] == "upheld"]
        unique = [e for e in upheld if len(by_member[e["id"]]["reviewers"]) == 1]
        rows.append({
            "reviewer": rid, "seat": info["seat"], "protocol": info["protocol"],
            "rounds": {str(r): kind for r, kind in sorted(info["rounds"].items())},
            "raised": len(own), "withdrawn_on_self_check": len(own) - len(kept) - len(on_repair),
            "withdrawn_on_repair": len(on_repair), "kept": len(kept),
            "quotes_found": sum(1 for e in kept if e["quote_check"] in FOUND),
            "checked": sum(1 for e in kept if e["check"] is not None),
            "upheld": len(upheld), "not_upheld": sum(1 for e in kept if e["check"] == "not-upheld"),
            "unique_upheld": len(unique),
            "must_fix_upheld": sum(1 for e in upheld if e["severity"] == "must-fix"),
            "overall": {str(r): s["overall"] for r, s in sorted(info["scores"].items())},
        })
    return rows


def fresh_vs_returning(issues: dict[str, dict], reviewers: dict[str, dict], groups: list[dict], k: int,
                       rounds: list[dict]) -> dict:
    if k < 2:
        return {}
    returning = [r for r in reviewers.values() if r["rounds"].get(k) == "returning"]
    fresh = [r for r in reviewers.values() if r["rounds"].get(k) == "fresh"]
    if not fresh:
        return {"note": "no fresh reviewer in the latest round: anchoring and capitulation cannot be checked"}
    by_member = {m: g for g in groups for m in g["members"]}
    reraised = []
    for e in issues.values():
        if e["raised_in"] != k or e["reviewer"] not in {r["reviewer"] for r in fresh}:
            continue
        for m in by_member[e["id"]]["members"]:
            other, last = issues[m], issues[m]["history"][-1]
            closed_by_reviewer = last["status"] in ("resolved", "reason-accepted") or (
                last["status"] == "withdrawn" and last.get("event") == "judged")
            if other["raised_in"] < k and closed_by_reviewer:
                reraised.append({"fresh": e["id"], "earlier": m, "earlier_status": history_status(other["history"][-1]),
                                 "check": e["check"]})
    fresh_ids = {r["reviewer"] for r in fresh}
    returning_ids = {r["reviewer"] for r in returning}
    new_serious = []
    for g in groups:
        members = [issues[m] for m in g["members"]]
        from_fresh = [m for m in members if m["reviewer"] in fresh_ids and m["history"][0]["status"] != "withdrawn"]
        if not from_fresh or g["severity"] not in ("must-fix", "should-fix"):
            continue
        if any(m["raised_in"] < k for m in members):
            continue
        # One verdict per group: the head's (the group's own id), and how many members differ.
        verdict = issues[g["id"]]["check"]
        differ = {m["id"]: m["check"] for m in members if m["check"] is not None and m["check"] != verdict}
        new_serious.append({"id": g["id"], "members": g["members"], "severity": g["severity"],
                            "check": verdict, "check_differs": differ,
                            "also_raised_by_returning": any(m["reviewer"] in returning_ids for m in members)})
    seats = {}
    for r in returning + fresh:
        seat = r["seat"] or "(no seat)"
        row = seats.setdefault(seat, {"returning": [], "fresh": []})
        score = r["scores"].get(k, {}).get("overall")
        row[r["rounds"][k]].append({"reviewer": r["reviewer"], "overall": score,
                                    "previous": next((r["scores"][x]["overall"] for x in sorted(r["scores"], reverse=True) if x < k), None)})
    latest = rounds[-1] if rounds else {}
    out = {"round": k, "reraised_after_closing": reraised, "new_from_fresh": new_serious, "by_seat": seats}
    if not latest.get("synthesis_written"):
        out["unlinked"] = True  # no same_as marks yet: re-raised points cannot be seen
    return out


def stopping(plan: dict, rounds: list[dict]) -> dict:
    if not rounds:
        return {}
    last = rounds[-1]
    met = []
    if last["open_must_fix_after"] == 0:
        met.append("no-open-must-fix")
    fresh_present = any(r["kind"] == "fresh" for r in last["reviewers"])
    if last["round"] > 1 and fresh_present and not last["fresh_new_surviving"] and not last["fresh_new_unchecked"]:
        met.append("fresh-nothing-new")
    max_rounds = plan.get("max_rounds")
    if isinstance(max_rounds, int) and last["round"] >= max_rounds:
        met.append("max-rounds")
    return {
        "rule": text_of(plan.get("stopping_rule")),
        "round": last["round"],
        "max_rounds": max_rounds,
        "open_must_fix": last["open_must_fix"],
        "fresh_new_surviving": last["fresh_new_surviving"],
        "fresh_new_unchecked": last["fresh_new_unchecked"],
        "conditions_met": met,
    }


CONDITION_TEXT = {
    "no-open-must-fix": "no open must-fix point",
    "fresh-nothing-new": "this round's fresh reviewers raised nothing new (must-fix or should-fix) that survived checking",
    "max-rounds": "the agreed maximum number of rounds is reached",
}
CHURN_TEXT = {
    "changes-unconfirmed": "the authors report changes, but no point was confirmed resolved or partly resolved",
    "introduced-as-many": "the revision introduced at least as many points as it resolved",
}
PACKET_STATUS_TEXT = {
    "resolved-unverified": "resolved, but your quote of the revised text was not found",
    "withdrawn-unverified": "withdrawn, but your quote of the revised text was not found",
}
UNLINKED_TEXT = ("no synthesis.json for this round yet, so fresh points are not linked to earlier ones: "
                 "write the same_as marks first, then rebuild, before reading re-raised points")


def ids(values: list[str]) -> str:
    return f" ({', '.join(values)})" if values else ""


def print_summary(ledger: dict) -> None:
    issues = ledger["issues"]
    print(f"ledger: {len(ledger['rounds'])} round(s), {len(ledger['reviewers'])} reviewer(s), {len(issues)} point(s)")
    for r in ledger["rounds"]:
        kinds = counts(x["kind"] for x in r["reviewers"])
        who = ", ".join(f"{n} {kind}" for kind, n in kinds.items()) or "no reviews yet"
        sev = ", ".join(f"{s} {r['raised_by_severity'].get(s, 0)}" for s in SEVERITIES)
        print(f"round {r['round']}: {who}; raised {r['raised']} ({sev}; withdrawn on self-check "
              f"{r['withdrawn_on_self_check']}, on quote repair {r['withdrawn_on_repair']})")
        if r["round"] > 1:
            judged = ", ".join(f"{s} {n}" for s, n in sorted(r["judged"].items())) or "none"
            resp = ", ".join(f"{a} {n}" for a, n in sorted(r["response"].items())) or "none"
            origins = r["raised_by_origin"]
            print(f"  judged: {judged}")
            print(f"  response rows: {resp}; other changes listed: {r['other_changes']}")
            print(f"  new from returning reviewers: introduced by revision {origins.get('introduced-by-revision', 0)}, "
                  f"missed earlier {origins.get('missed-earlier', 0)}")
            print(f"  fresh, new and surviving checks: {len(r['fresh_new_surviving'])}{ids(r['fresh_new_surviving'])}"
                  f"; not yet checked: {len(r['fresh_new_unchecked'])}{ids(r['fresh_new_unchecked'])}")
        print(f"  open must-fix: {r['open_must_fix_before']} before -> {r['open_must_fix_after']} after{ids(r['open_must_fix'])}")
        if r.get("must_fix_remainder_lower"):
            print(f"  raised as must-fix, judged partly, what remains is lower: {', '.join(r['must_fix_remainder_lower'])}")
        if r["set_aside"]:
            print(f"  set aside by the coordinator (not-recommended): {', '.join(r['set_aside'])}")
        for note in r["churn"]:
            print(f"  churn: {CHURN_TEXT.get(note, note)}")
    still_open = [e for e in issues if e["open"]]
    if still_open:
        print("open now:")
        for e in sorted(still_open, key=lambda x: (severity_rank(x["current_severity"]), x["id"])):
            was = f" (was {e['severity']}; what remains: {e['current_severity']})" if e["current_severity"] != e["severity"] else ""
            print(f"  {e['id']:8s} {e['current_severity']:10s} {e['status']:20s} {e['title'][:70]}{was}")
    else:
        print("open now: nothing")
    stop = ledger["stopping"]
    if stop:
        print(f"stopping rule: {stop['rule'] or '(not stated in plan.json; state it before round 1)'}")
        print(f"  conditions met: {'; '.join(CONDITION_TEXT.get(c, c) for c in stop['conditions_met']) or 'none'}")
    fvr = ledger["fresh_vs_returning"]
    if fvr.get("unlinked"):
        print(f"  fresh against returning: {UNLINKED_TEXT}")
    for x in fvr.get("reraised_after_closing", []):
        print(f"  capitulation signal: fresh {x['fresh']} re-raises {x['earlier']} ({x['earlier_status']})")
    for warning in ledger["warnings"]:
        print(f"warning: {warning}")


def md_cell(value: object) -> str:
    return text_of(value).replace("|", "\\|").replace("\n", " ").strip() or "-"


SCORE_LABELS = ("overall", "confidence") + SCORE_DIMENSIONS
NOT_NEUTRAL = re.compile(r"round|revis|rebuttal|respon|resubmi|(^|[^a-z0-9])v[0-9]+($|[^a-z0-9])")


def severity_cell(e: dict) -> str:
    now = e.get("current_severity") or current_severity(e)
    return now if now == e["severity"] else f"{e['severity']} (what remains: {now})"


def quote_cell(e: dict) -> str:
    if not e["quote"].strip():
        return "(no quote)"
    if e.get("quote_chosen"):
        return f"(passage chosen by the coordinator when your review was converted, not quoted by you) {e['quote']}"
    return e["quote"]


def scores_lines(info: dict, before: int, sheet: dict) -> list[str]:
    """The reviewer's latest levels before round `before`, so that score_changes can name `from`."""
    earlier = [r for r in info["scores"] if r < before]
    if not earlier:
        return []
    r = max(earlier)
    record = info["scores"][r]
    levels = {"overall": record["overall"], "confidence": record["confidence"], **record["dimensions"]}
    lines = ["## Your latest scores", "",
             f"From your review of round {r}, on the anchored scale; use them as `from` in `score_changes`.", ""]
    lines += [f"- {name}: {text_of(levels.get(name)) or '-'}" for name in SCORE_LABELS]
    extra = {key: value for key, value in as_dict(record.get("extra")).items() if is_small_value(value)}
    if extra:
        name = text_of(as_dict(sheet).get("name"))
        lines += ["", "On the extra score sheet" + (f" ({name})" if name else "") + ": "
                  + "; ".join(f"{key} {text_of(value)}" for key, value in extra.items())]
    return lines + [""]


def action_cell(a: dict) -> str:
    action = text_of(a.get("action"))
    notes = [n for n, flag in (("the authors disagree", a.get("disagree") is True),
                                ("out of reach this round", a.get("out_of_reach") is True)) if flag]
    return action + (f" ({'; '.join(notes)})" if notes else "")


def packet_texts(ledger: dict, response: dict, rid: str, points: list[dict], k: int, files: list[str],
                 top: int, sheet: dict) -> tuple[str, str]:
    """(points.md, response.md) for one returning reviewer; `files` are its earlier review files as named for it."""
    answers = {text_of(a.get("id")).strip(): a for a in as_list(response.get("answers")) if isinstance(a, dict)}
    others = [o for o in as_list(response.get("other_changes")) if isinstance(o, dict)]
    out_of_reach = as_list(ledger["out_of_reach"].get(str(k)))
    info = next(r for r in ledger["reviewers"] if r["reviewer"] == rid)
    lines = [
        f"# Your open points (reviewer {rid}, round {k})", "",
        "Your earlier review files: " + ", ".join(f"`{f}`" for f in files), "",
        "Each point below is still open. Step 1: before you open the response file, write for",
        "each one what would count as resolving it, from what you wrote earlier.", "",
        "| id | severity | type | raised | title | where | your quote | why it matters | what you said would resolve it | your latest status |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in sorted(points, key=lambda x: (severity_rank(x.get("current_severity") or x["severity"]), x["id"])):
        hist = e["history"][-1]
        status = history_status(hist)
        latest = f"round {hist['round']}: {PACKET_STATUS_TEXT.get(status, status)}" + (f" ({hist['note']})" if hist.get("note") else "")
        lines.append("| " + " | ".join(md_cell(v) for v in (
            e["id"], severity_cell(e), e["type"], f"round {e['raised_in']}", e["title"], e["where"], quote_cell(e),
            e["why"], e["resolution"], latest)) + " |")
    lines += [""] + scores_lines(info, k, sheet)
    lines += ["## Numbering new points", "",
              f"Your highest point id so far is {rid}.{top}. If you raise a new point, number it from {rid}.{top + 1} on;",
              "an id that was used before cannot be recorded.", ""]
    lines += ["## Out of reach this round", ""]
    lines += [f"- {text_of(x)}" for x in out_of_reach] or ["- (none listed)"]
    lines += ["", "Do not hold these against the revision. Judge instead whether the paper now handles them",
              "within reach: a narrowed claim, a stated limitation, a clear plan for later work.", ""]

    rows = [
        f"# Authors' response to reviewer {rid} (round {k})", "",
        "Open this only after you have written your criteria and judged every point against the",
        "revised PDF. Check every claimed change in the revised PDF yourself.", "",
        "| id | action | what was done | where | why not |", "|---|---|---|---|---|",
    ]
    for e in sorted(points, key=lambda x: x["id"]):
        a = answers.get(e["id"])
        if a:
            rows.append("| " + " | ".join(md_cell(v) for v in (
                e["id"], action_cell(a), a.get("what"), a.get("where"), a.get("why_not"))) + " |")
        else:
            rows.append(f"| {e['id']} | (no row) | the authors did not answer this point | - | - |")
    rows += ["", "## Other changes the authors list", ""]
    rows += [f"- {md_cell(o.get('what'))} ({md_cell(o.get('where'))})" for o in others] or ["- (none)"]
    rows.append("")
    return "\n".join(lines), "\n".join(rows)


def returning_points(review_dir: Path, k: int) -> tuple[dict, dict, dict[str, list[dict]], dict[str, int]]:
    """(ledger up to round k-1, response of round k, open points by reviewer, highest point number by reviewer)."""
    rdir = review_dir / f"round-{k}"
    if not rdir.is_dir():
        die(f"{rdir}: create the round folder (with the revised manuscript and response.json) first")
    ledger = build(review_dir, upto=k - 1)
    if not ledger["rounds"]:
        die(f"no rounds before round {k}")
    response = read_json_optional(rdir / "response.json")
    if not isinstance(response, dict):
        die(f"{rdir / 'response.json'}: missing; returning reviewers need the authors' response")
    for warning in ledger["warnings"]:
        print(f"warning: {warning}")
    by_reviewer: dict[str, list[dict]] = {}
    highest: dict[str, int] = {}
    for e in ledger["issues"]:
        number = int(POINT_RE.match(e["id"]).group(2))
        highest[e["reviewer"]] = max(highest.get(e["reviewer"], 0), number)
        if e["open"] and RID_RE.match(e["reviewer"]):  # ids come from file names; never write anywhere else
            by_reviewer.setdefault(e["reviewer"], []).append(e)
    return ledger, response, dict(sorted(by_reviewer.items(), key=lambda item: rid_number(item[0]))), highest


def write_packets(review_dir: Path, k: int) -> None:
    rdir = review_dir / f"round-{k}"
    ledger, response, by_reviewer, highest = returning_points(review_dir, k)
    infos = {r["reviewer"]: r for r in ledger["reviewers"]}
    sheet = as_dict(ledger["plan"].get("extra_score_sheet"))
    for rid, points in by_reviewer.items():
        files = [infos[rid]["file"][r] for r in sorted(infos[rid]["file"])]
        top = highest.get(rid, 0)
        points_md, response_md = packet_texts(ledger, response, rid, points, k, files, top, sheet)
        write_text(rdir / "packets" / f"{rid}-points.md", points_md)
        write_text(rdir / "packets" / f"{rid}-response.md", response_md)
        print(f"{rid}: {len(points)} open point(s), new points from {rid}.{top + 1} -> "
              f"packets/{rid}-points.md, packets/{rid}-response.md")
    if not by_reviewer:
        print("no earlier reviewer has an open point; this round needs fresh reviewers only")
    taken = reviewer_ids_on_disk(review_dir)
    print(f"next free id for a fresh reviewer: R{max((rid_number(r) for r in taken), default=0) + 1}")


def round_documents(rdir: Path) -> list[Path]:
    """The PDFs of one round's version: the manuscript, then any supplement listed in the page map."""
    page_map = PageMap.for_text(rdir / "manuscript.txt")
    if not page_map:
        return [rdir / "manuscript.pdf"]
    out = []
    for name in page_map.files():
        path = Path(name)
        out.append(path if path.is_absolute() else rdir / path)
    return out


class Room:
    """One reviewer's folder: the files it may read, and nothing else."""

    def __init__(self, path: Path) -> None:
        self.path, self.files, self.missing = path, [], []

    def copy(self, source: Path, name: str) -> None:
        if not source.is_file():
            self.missing.append(str(source))
            return
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self.files.append(name)

    def write(self, name: str, text: str) -> None:
        write_text(self.path / name, text)
        self.files.append(name)

    def stale(self) -> list[str]:
        """Files already in the room that this run did not put there (protocol/ is the coordinator's)."""
        if not self.path.is_dir():
            return []
        mine = set(self.files)
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*")
                      if p.is_file() and p.relative_to(self.path).as_posix() not in mine
                      and p.relative_to(self.path).parts[0] != "protocol")


def earlier_original(review_dir: Path, value: str) -> Path | None:
    """A converted review's original, accepted only as a file inside <review-dir>/earlier/."""
    earlier = (review_dir / "earlier").resolve()
    path = (review_dir / value).resolve()
    try:
        path.relative_to(earlier)
    except ValueError:
        return None
    return path if path.is_file() else None


def neutral_document_name(index: int, path: Path) -> str:
    """The name a fresh room gives a document: manuscript.pdf, supplement.pdf, supplement-3.pdf, ..."""
    suffix = path.suffix or ".pdf"
    if index == 0:
        return f"manuscript{suffix}"
    return f"supplement{suffix}" if index == 1 else f"supplement-{index}{suffix}"


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def write_rooms(review_dir: Path, k: int, out: Path, fresh: list[str], external: list[str],
                fresh_out: Path | None = None) -> None:
    rdir = review_dir / f"round-{k}"
    if not rdir.is_dir():
        die(f"{rdir}: create the round folder with this round's manuscript first")
    if not (rdir / "manuscript.txt").is_file():
        die(f"{rdir / 'manuscript.txt'}: missing; run extract_text.py on this round's PDF(s) first")
    out = out.resolve()
    fresh_parent = (fresh_out or out).resolve()
    for path in {out, fresh_parent}:
        if inside(path, review_dir.resolve()):
            die(f"{path}: inside the review folder; rooms must not sit next to plan.json and the other rounds")
    if fresh_out is not None and (inside(fresh_parent, out) or inside(out, fresh_parent)):
        die(f"{fresh_parent} and {out}: one holds the other; fresh rooms need a parent apart from the returning rooms")
    if fresh_out is not None and fresh_parent.parent == out.parent:
        print(f"warning: {fresh_parent} and {out} sit side by side; a fresh reviewer listing two folders up sees the "
              "returning rooms; prefer two unrelated paths", file=sys.stderr)
    if (fresh or external) and NOT_NEUTRAL.search(fresh_parent.as_posix().lower()):
        print(f"warning: {fresh_parent}: the path names a round, a revision or a version, and fresh reviewers see it; "
              "choose a neutral path", file=sys.stderr)
    private = [t for t in as_list(as_dict(read_json_optional(review_dir / "plan.json")).get("private_terms"))
               if isinstance(t, str) and t.strip()]
    for n, term in enumerate(private, 1):
        for path in sorted({out, fresh_parent}):
            if term.casefold() in path.as_posix().casefold():
                print(f"warning: {path}: the path contains private term #{n} of plan.json, and every reviewer "
                      "sees it; choose a neutral path", file=sys.stderr)
    documents = round_documents(rdir)
    rooms = []

    if k >= 2:
        ledger, response, by_reviewer, highest = returning_points(review_dir, k)
        if by_reviewer and (fresh or external) and fresh_out is None:
            die("this round has returning and fresh reviewers: give the fresh rooms their own parent with "
                "--fresh-out, apart from --out, so that a fresh reviewer cannot list the returning rooms "
                "(previous/, revised/, response.md) next to its own")
        infos = {r["reviewer"]: r for r in ledger["reviewers"]}
        sheet = as_dict(ledger["plan"].get("extra_score_sheet"))
        previous = round_documents(review_dir / f"round-{k - 1}")
        for rid, points in by_reviewer.items():
            info = infos[rid]
            room = Room(out / rid)
            for r in sorted(info["file"]):
                room.copy(review_dir / info["file"][r], f"review-round-{r}.json")
                repair = review_dir / f"round-{r}" / "repairs" / f"{rid}.json"
                if repair.is_file():
                    room.copy(repair, f"repairs-round-{r}.json")
                original = as_dict(info.get("converted_from")).get(r)
                if original:
                    source = earlier_original(review_dir, original)
                    if source is None:
                        print(f"warning: {rid}, round {r}: converted_from {original!r} is not a file inside "
                              f"{review_dir / 'earlier'}; the original was not copied into the room", file=sys.stderr)
                    else:
                        room.copy(source, f"review-round-{r}-original{source.suffix}")
            points_md, response_md = packet_texts(ledger, response, rid, points, k, room.files[:], highest.get(rid, 0), sheet)
            room.write("points.md", points_md)
            room.write("response.md", response_md)
            for pdf in previous:
                room.copy(pdf, f"previous/{pdf.name}")
            for pdf in documents:
                room.copy(pdf, f"revised/{pdf.name}")
            room.copy(rdir / "manuscript.txt", "revised/manuscript.txt")
            rooms.append({"reviewer": rid, "kind": "returning", "seat": info["seat"], "room": room})

    earlier_ids = {p.stem for r, d in round_dirs(review_dir) if r < k for p in (d / "reviews").glob("*.json")
                   if RID_RE.match(p.stem)}
    next_id = max((rid_number(r) for r in earlier_ids), default=0) + 1
    for n, seat in enumerate(list(fresh) + list(external)):
        rid = f"R{next_id + n}"
        room = Room(fresh_parent / rid)
        for index, pdf in enumerate(documents):
            room.copy(pdf, neutral_document_name(index, pdf))  # the user's own file names may say "v2"
        room.copy(rdir / "manuscript.txt", "manuscript.txt")
        is_external = n >= len(fresh)
        if is_external:
            (room.path / "protocol").mkdir(parents=True, exist_ok=True)
        rooms.append({"reviewer": rid, "kind": "fresh", "seat": seat, "external": is_external, "room": room})

    record = []
    for item in rooms:
        room = item.pop("room")
        label = f"{item['reviewer']} {item['kind']}" + (", external protocol" if item.get("external") else "") + \
            (f" (seat {item['seat']})" if item["seat"] else "")
        print(f"{label}: {room.path}")
        for name in room.files:
            print(f"    {(room.path / name)}")
        if item.get("external"):
            protocol = room.path / "protocol"
            filled = any(protocol.rglob("*"))
            print(f"    {protocol}{'' if filled else '  (empty: copy the protocol files the seat should read into it)'}")
        for path in room.missing:
            print(f"  warning: {path} not found; the room lacks it", file=sys.stderr)
        stale = room.stale()
        if stale:
            print(f"  warning: {room.path} also holds files this command did not put there: {', '.join(stale)}; "
                  "remove them unless the reviewer should read them", file=sys.stderr)
        record.append(dict(item, path=str(room.path), files=room.files))
    if not rooms:
        print("no rooms: no earlier reviewer has an open point and no fresh seat was given (--fresh, --external)")
    write_json(rdir / "rooms.json", {"round": k, "rooms": record})
    print(f"wrote {rdir / 'rooms.json'}")
    print("Brief each reviewer by its room: list these absolute paths as the only files it may read.")


def main() -> None:
    safe_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_build = sub.add_parser("build", help="rebuild ledger.json and print the status")
    p_build.add_argument("review_dir", type=Path)
    p_packets = sub.add_parser("packets", help="write returning-reviewer packets for a round")
    p_packets.add_argument("review_dir", type=Path)
    p_packets.add_argument("--round", type=int, required=True, dest="round_k")
    p_rooms = sub.add_parser("rooms", help="build one folder per reviewer holding only its files")
    p_rooms.add_argument("review_dir", type=Path)
    p_rooms.add_argument("--round", type=int, required=True, dest="round_k")
    p_rooms.add_argument("--out", type=Path, required=True,
                         help="parent folder of the rooms (of the returning rooms when --fresh-out is given); "
                              "outside the review folder, neutral when it holds fresh rooms")
    p_rooms.add_argument("--fresh-out", type=Path, dest="fresh_out",
                         help="parent folder of the fresh rooms, apart from --out; required when a round has both "
                              "returning and fresh reviewers, so that no fresh room sits next to a returning room")
    p_rooms.add_argument("--fresh", nargs="*", default=[], metavar="SEAT", help="one seat name per fresh built-in reviewer")
    p_rooms.add_argument("--external", nargs="*", default=[], metavar="SEAT",
                         help="one seat name per fresh external-protocol reviewer (gets an empty protocol/ folder)")
    args = parser.parse_args()

    if args.command == "build":
        ledger = build(args.review_dir)
        write_json(args.review_dir / "ledger.json", ledger)
        print_summary(ledger)
        print(f"wrote {args.review_dir / 'ledger.json'}")
    elif args.command == "packets":
        if args.round_k < 2:
            die("packets are for round 2 and later")
        write_packets(args.review_dir, args.round_k)
    else:
        if args.round_k < 1:
            die("rounds are numbered from 1")
        write_rooms(args.review_dir, args.round_k, args.out, args.fresh, args.external, args.fresh_out)


if __name__ == "__main__":
    main()
