#!/usr/bin/env python3
"""Check by script, not by a model, that quotes are verbatim manuscript text.

usage: check_quotes.py ROUND_DIR [--text FILE] [--pages FILE] [--plan FILE]
                       [--queries FILE] [--out FILE]

Reads ROUND_DIR/manuscript.txt (made by extract_text.py), every review in
ROUND_DIR/reviews/ (with ROUND_DIR/repairs/ applied), and ROUND_DIR/response.json and
ROUND_DIR/checks.json when present. Writes ROUND_DIR/quotes.json and prints a summary.
When the text holds a supplement too, the page map next to it (manuscript.pages.json)
says which document each page belongs to, and every quote found is located as, for
example, "supplement p. 3" (fields document and document_page) as well as by its page in
the joined text (field page).

Each quote gets one status:
  found        a substring of the manuscript text after normalising both sides
               (NFKC, quote marks and dashes folded, line-end hyphenation joined,
               whitespace collapsed); case and punctuation must match
  found-loose  matches only when case, spaces and punctuation are also ignored; usually a
               hyphenation or punctuation slip; counts as found, but glance at it. Numbers
               are never loosened: "3.2", "32", "-0.3" and "0.3" stay different
  not-found    neither; send it back to the reviewer once, or mark it "quote not found"
  missing      the record needs a quote and has none
"..." or "…" inside a quote separates fragments; each fragment must be found, in order.
Flags: "short" (under five words, or under about ten CJK characters: it locates text but
proves little); "stitched" (fragments under four words, or more than 300 characters
apart: the pieces exist but may not say together what the quote suggests); "repaired";
"withdrawn" (the point was withdrawn, so its quote needs no repair).

What needs a quote: every finding; every judgement marked resolved, partly or withdrawn
(the quote must come from the revised manuscript, which is this round's text); every
reported injected instruction; every response row marked changed or partly. Quotes in
checks.json are checked when given.

Search queries in each review's reading.searches are audited too: a query that contains a
term from plan.json's private_terms (title, coined names, author or project names), shares
four consecutive words with one of them, or shares eight consecutive words with the
manuscript, is flagged. Flags name a private term by its number in plan.json, not by its
text. The audit cannot unsend a query; it tells the user whether the privacy rule held.

The reviewers' own lists can be incomplete. Where the host keeps transcripts, give the web
requests actually sent with --queries FILE (default: ROUND_DIR/queries.json when it
exists, so that later reruns keep the audit). The file is JSON, reviewer id to a list of
requests: search queries, fetched URLs and a fetch tool's prompts, each a string or an
object such as {"tool": "fetch", "url": "...", "prompt": "..."}. Every request is audited
in the same way, listed or not, and requests that the reviewer did not list in
reading.searches are reported as unlisted. Only the same text counts as listed (case,
outer quotes and spaces aside): a listed search with words added is an unlisted request.
"""

from __future__ import annotations

import argparse
import bisect
import re
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    QUOTED_JUDGEMENTS,
    PageMap,
    as_dict,
    as_list,
    die,
    enum_key,
    load_reviews,
    read_json,
    read_json_optional,
    review_findings,
    review_judgements,
    round_number,
    safe_console,
    text_of,
    text_units,
    write_json,
)

FOLD = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "\u00b4": "'", "`": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"', "\u00ab": '"', "\u00bb": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
        "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u00ad": None, "\u200b": None,
    }
)
ELLIPSIS = re.compile(r"\s*(?:\[\s*(?:\.\s*){3}\]|\[\s*\u2026\s*\]|\u2026|(?:\.\s*){3})\s*")
HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\n[ \t]*(?=[a-z\u00e0-\u00ff])")
EDGE_QUOTES = "\"'\u2018\u2019\u201c\u201d\u00ab\u00bb "
NGRAM = 8
PRIVATE_RUN = 4
MIN_FRAGMENT_WORDS = 4
MAX_FRAGMENT_GAP = 300


def strict_norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(FOLD)
    text = HYPHEN_BREAK.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def loose_norm(text: str) -> str:
    """Letters and digits only, except the marks that make two numbers differ."""
    text = unicodedata.normalize("NFKC", text).translate(FOLD).casefold()
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch.isalnum():
            out.append(ch)
            continue
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in ".," and prev.isdigit() and nxt.isdigit():
            out.append(ch)  # 3.2, 1,000
        elif ch == "%" and out and out[-1].isdigit():
            out.append(ch)  # 5 %, 5%
        elif ch == "-" and nxt.isdigit() and not prev.isalpha():
            out.append(ch)  # 1-9, -0.3
    return "".join(out)


def words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def shares_run(a: list[str], b: list[str], n: int) -> bool:
    runs = {tuple(a[i : i + n]) for i in range(len(a) - n + 1)}
    return any(tuple(b[i : i + n]) in runs for i in range(len(b) - n + 1))


class ManuscriptText:
    """The manuscript text in two normalised forms, with page offsets for each."""

    def __init__(self, raw: str) -> None:
        pages = raw.rstrip("\f").split("\f") if raw.strip() else [""]
        self.pages = len(pages)
        self.strict, self.strict_starts = self._join([strict_norm(p) for p in pages], " ")
        self.loose, self.loose_starts = self._join([loose_norm(p) for p in pages], "")
        tokens = words(raw)
        self.ngrams = {tuple(tokens[i : i + NGRAM]) for i in range(max(0, len(tokens) - NGRAM + 1))}

    @staticmethod
    def _join(parts: list[str], sep: str) -> tuple[str, list[int]]:
        starts, pos = [], 0
        for part in parts:
            starts.append(pos)
            pos += len(part) + len(sep)
        return sep.join(parts), starts

    @staticmethod
    def _page(starts: list[int], offset: int) -> int:
        return bisect.bisect_right(starts, offset)

    def _find_all(self, fragments: list[str], haystack: str, starts: list[int]) -> tuple[int | None, int]:
        """(page of the first fragment, widest gap between fragments), or (None, 0)."""
        pos, first, gap, prev_end = 0, None, 0, None
        for frag in fragments:
            if not frag:
                continue
            idx = haystack.find(frag, pos)
            if idx < 0:
                return None, 0
            if first is None:
                first = self._page(starts, idx)
            if prev_end is not None:
                gap = max(gap, idx - prev_end)
            prev_end = pos = idx + len(frag)
        return first, gap

    def locate_full(self, quote: str) -> dict:
        fragments = [f.strip(EDGE_QUOTES) for f in ELLIPSIS.split(quote)]
        fragments = [f for f in fragments if f]
        if not fragments:
            return {"status": "missing", "page": None, "stitched": False}
        status, (page, gap) = "found", self._find_all([strict_norm(f) for f in fragments], self.strict, self.strict_starts)
        if page is None:
            status, (page, gap) = "found-loose", self._find_all([loose_norm(f) for f in fragments], self.loose, self.loose_starts)
        if page is None:
            return {"status": "not-found", "page": None, "stitched": False}
        stitched = len(fragments) > 1 and (
            min(text_units(f) for f in fragments) < MIN_FRAGMENT_WORDS or gap > MAX_FRAGMENT_GAP)
        return {"status": status, "page": page, "stitched": stitched}

    def locate(self, quote: str) -> tuple[str, int | None]:
        found = self.locate_full(quote)
        return found["status"], found["page"]

    def shares_ngram(self, query: str) -> bool:
        tokens = words(query)
        return any(tuple(tokens[i : i + NGRAM]) in self.ngrams for i in range(len(tokens) - NGRAM + 1))


def quote_targets(rid: str, review: dict):
    """(field, id, quote, required, repaired, withdrawn) for every quote a review carries."""
    for finding in review_findings(review):
        yield ("finding", text_of(finding.get("id")).strip(), text_of(finding.get("quote")), True,
               bool(finding.get("quote_repaired")), enum_key(finding.get("status")) == "withdrawn")
    for judgement in review_judgements(review):
        status = enum_key(judgement.get("status"))
        quote = text_of(judgement.get("quote"))
        if status in QUOTED_JUDGEMENTS or quote:
            yield ("judgement", text_of(judgement.get("id")).strip(), quote, status in QUOTED_JUDGEMENTS,
                   bool(judgement.get("quote_repaired")), bool(judgement.get("withdrawn_on_repair")))
    for n, item in enumerate(as_list(review.get("injected_instructions")), 1):
        if isinstance(item, dict):
            yield "injected", f"{rid}:injected:{n}", text_of(item.get("quote")), True, False, False


def audit_query(query: str, private: list[str], text: ManuscriptText) -> list[str]:
    flags = []
    q_words = words(query)
    for n, term in enumerate(private, 1):
        if term.casefold() in query.casefold():
            flags.append(f"contains private term #{n} of plan.json")
        elif shares_run(words(term), q_words, PRIVATE_RUN):
            flags.append(f"shares {PRIVATE_RUN}+ consecutive words with private term #{n} of plan.json")
    if text.shares_ngram(query):
        flags.append(f"shares {NGRAM}+ consecutive words with the manuscript (fine only for a cited work's title)")
    return flags


REQUEST_FIELDS = ("query", "url", "prompt", "text")


def transcript_requests(value) -> list[tuple[str, str]]:
    """(kind, text) for each web request in one reviewer's list from the transcripts."""
    out = []
    for item in as_list(value):
        if isinstance(item, dict):
            for field in REQUEST_FIELDS:
                if text_of(item.get(field)).strip():
                    out.append((field, text_of(item.get(field)).strip()))
        elif text_of(item).strip():
            out.append(("query", text_of(item).strip()))
    return out


def request_key(text: str) -> str:
    return " ".join(text.strip().strip("\"'").casefold().split())


def is_listed(request: str, listed: list[str]) -> bool:
    """Whether a request from the transcripts is one of the reviewer's own listed searches.

    Only the same text (after folding case, outer quotes and spaces) counts: a request that
    adds words to a listed search is a different request, and the added words may be the
    ones that should not have left the machine.
    """
    return request_key(request) in listed


def check_round(round_dir: Path, text_path: Path, plan_path: Path | None, pages_path: Path | None = None,
                queries_path: Path | None = None) -> dict:
    if not text_path.is_file():
        die(f"{text_path}: no extracted text; run extract_text.py on this round's manuscript first")
    text = ManuscriptText(text_path.read_text(encoding="utf-8"))
    page_map = PageMap.for_text(text_path, pages_path)
    warnings: list[str] = []
    if page_map and page_map.total_pages != text.pages:
        warnings.append(f"the page map gives {page_map.total_pages} pages but {text_path.name} has {text.pages}; "
                        "rerun extract_text.py with all the PDFs")
    reviews = load_reviews(round_dir, warnings)
    results = []

    def record(source: str, field: str, item_id: str, quote: str, required: bool, repaired: bool,
               withdrawn: bool = False) -> None:
        if not quote.strip():
            if required:
                entry = {"source": source, "id": item_id, "field": field, "status": "missing", "page": None}
                if withdrawn:
                    entry["withdrawn"] = True
                results.append(entry)
            return
        found = text.locate_full(quote)
        entry = {"source": source, "id": item_id, "field": field, "status": found["status"], "page": found["page"]}
        if page_map and found["page"] is not None:
            index, name, local = page_map.locate(found["page"])
            entry.update(document=name, document_index=index, document_page=local)
        if text_units(quote) < 5:
            entry["short"] = True
        if found["stitched"]:
            entry["stitched"] = True
        if repaired:
            entry["repaired"] = True
        if withdrawn:
            entry["withdrawn"] = True
        entry["excerpt"] = quote[:90]
        results.append(entry)

    for rid, review in reviews.items():
        for field, item_id, quote, required, repaired, withdrawn in quote_targets(rid, review):
            record(rid, field, item_id, quote, required, repaired, withdrawn)

    response = read_json_optional(round_dir / "response.json")
    if isinstance(response, dict):
        for answer in as_list(response.get("answers")):
            if isinstance(answer, dict):
                action = enum_key(answer.get("action"))
                record("response", "response", text_of(answer.get("id")).strip(), text_of(answer.get("quote")),
                       action in ("changed", "partly"), False)

    checks = read_json_optional(round_dir / "checks.json")
    if isinstance(checks, dict):
        for check in as_list(checks.get("checks")):
            if isinstance(check, dict) and text_of(check.get("quote")):
                record("checks", f"check:{enum_key(check.get('kind')) or 'finding'}", text_of(check.get("id")).strip(),
                       text_of(check.get("quote")), False, False)

    plan = read_json_optional(plan_path) if plan_path else None
    private = [t for t in as_list(as_dict(plan).get("private_terms")) if isinstance(t, str) and t.strip()]
    searches, checked = [], 0
    listed: dict[str, list[str]] = {}
    for rid, review in reviews.items():
        for query in as_list(as_dict(review.get("reading")).get("searches")):
            query = text_of(query)
            if not query.strip():
                continue
            checked += 1
            listed.setdefault(rid, []).append(request_key(query))
            flags = audit_query(query, private, text)
            if flags:
                searches.append({"reviewer": rid, "query": query, "flags": flags})

    report = {
        "round": round_number(round_dir),
        "text": text_path.name,
        "pages": text.pages,
    }
    if page_map:
        report["documents"] = page_map.documents
    if queries_path is not None:
        sent = read_json(queries_path)
        if not isinstance(sent, dict):
            die(f"{queries_path}: expected a JSON object of reviewer id to a list of requests")
        unlisted, from_transcripts = [], 0
        for rid, value in sent.items():
            if rid not in reviews:
                warnings.append(f"{queries_path.name}: requests for {rid}, which has no review in this round")
            for kind, request in transcript_requests(value):
                from_transcripts += 1
                flags = audit_query(request, private, text)  # every request, listed or not
                if is_listed(request, listed.get(rid, [])):
                    # the same text was audited from reading.searches above; do not flag it twice
                    if flags and not any(f["reviewer"] == rid and request_key(f["query"]) == request_key(request)
                                         for f in searches):
                        searches.append({"reviewer": rid, "query": request, "flags": flags, "kind": kind})
                    continue
                unlisted.append({"reviewer": rid, "kind": kind, "query": request, "flags": flags})
                if flags:
                    searches.append({"reviewer": rid, "query": request, "flags": flags, "unlisted": True, "kind": kind})
        report["transcript_audit"] = {"file": queries_path.name, "requests": from_transcripts, "unlisted": unlisted}

    counts: dict[str, int] = {}
    for entry in results:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    report.update({
        "results": results,
        "counts": counts,
        "not_found": [f"{e['source']}:{e['id']}" for e in results
                      if e["status"] in ("not-found", "missing") and not e.get("withdrawn")],
        "searches_checked": checked,
        "search_flags": searches,
        "private_terms_given": bool(private),
        "warnings": warnings,
    })
    return report


def print_summary(report: dict) -> None:
    docs = report.get("documents")
    spans = ": " + ", ".join(f"{d['name']} {d['first_page']}-{d['first_page'] + d['pages'] - 1}" for d in docs) if docs else ""
    print(f"round {report['round']}: {report['text']} ({report['pages']} pages{spans})")
    if docs:
        elsewhere: dict[str, int] = {}
        for entry in report["results"]:
            if entry.get("document_index"):
                key = f"{entry['source']} in {entry['document']}"
                elsewhere[key] = elsewhere.get(key, 0) + 1
        if elsewhere:
            print("  quotes found outside the manuscript: " + ", ".join(f"{k} {n}" for k, n in elsewhere.items()))
    by_source: dict[str, dict[str, list[dict]]] = {}
    for entry in report["results"]:
        by_source.setdefault(entry["source"], {}).setdefault(entry["status"], []).append(entry)
    for source, statuses in by_source.items():
        total = sum(len(v) for v in statuses.values())
        parts = [f"{status} {len(entries)}" for status, entries in sorted(statuses.items())]
        bad = statuses.get("not-found", []) + statuses.get("missing", [])
        to_fix = [e["id"] for e in bad if not e.get("withdrawn")]
        withdrawn = [e["id"] for e in bad if e.get("withdrawn")]
        tail = f"  -> {', '.join(to_fix)}" if to_fix else ""
        if withdrawn:
            tail += f"  (withdrawn, no repair needed: {', '.join(withdrawn)})"
        print(f"  {source:10s} {total:3d} quotes: {', '.join(parts)}{tail}")
        stitched = [e["id"] for v in statuses.values() for e in v if e.get("stitched")]
        if stitched:
            print(f"  {'':10s} stitched from short or distant fragments: {', '.join(stitched)}")
    if not report["results"]:
        print("  no quotes to check")
    print(f"  searches audited: {report['searches_checked']}"
          + ("" if report["private_terms_given"] else " (no private_terms in plan.json; only the n-gram test ran)"))
    audit = report.get("transcript_audit")
    if audit:
        print(f"  requests read from the transcripts ({audit['file']}): {audit['requests']}; "
              f"not listed by the reviewer: {len(audit['unlisted'])}")
        for item in audit["unlisted"]:
            print(f"  UNLISTED {item['reviewer']} {item['kind']}: {item['query']!r}"
                  + (f" (flagged: {'; '.join(item['flags'])})" if item["flags"] else ""))
    for flag in report["search_flags"]:
        print(f"  FLAG {flag['reviewer']}: {flag['query']!r}: {'; '.join(flag['flags'])}")
    for warning in report["warnings"]:
        print(f"  warning: {warning}")


def main() -> None:
    safe_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("round_dir", type=Path, help="a round-<k> folder")
    parser.add_argument("--text", type=Path, help="extracted text (default: ROUND_DIR/manuscript.txt)")
    parser.add_argument("--pages", type=Path,
                        help="page map from extract_text.py (default: the text file's name with .pages.json, when present)")
    parser.add_argument("--plan", type=Path, help="plan.json with private_terms (default: ROUND_DIR/../plan.json)")
    parser.add_argument("--queries", type=Path,
                        help="web requests actually sent, read from the host's transcripts: JSON, reviewer id to a "
                             "list of queries, URLs and fetch prompts (default: ROUND_DIR/queries.json, when present)")
    parser.add_argument("--out", type=Path, help="output (default: ROUND_DIR/quotes.json)")
    args = parser.parse_args()

    round_dir = args.round_dir
    if not round_dir.is_dir():
        die(f"{round_dir}: not a directory")
    text_path = args.text or round_dir / "manuscript.txt"
    plan_path = args.plan or round_dir.parent / "plan.json"
    if args.pages and not args.pages.is_file():
        die(f"{args.pages}: no such file")
    if args.queries and not args.queries.is_file():
        die(f"{args.queries}: no such file")
    queries = args.queries or (round_dir / "queries.json" if (round_dir / "queries.json").is_file() else None)
    report = check_round(round_dir, text_path, plan_path if plan_path.is_file() else None, args.pages, queries)
    out = args.out or round_dir / "quotes.json"
    write_json(out, report)
    print_summary(report)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
