"""Shared helpers for the paper-review-panel scripts. Standard library only.

The review directory layout these scripts read is described in SKILL.md:

    <review-dir>/plan.json
    <review-dir>/round-<k>/manuscript.txt
    <review-dir>/round-<k>/manuscript.pages.json (page map, when a supplement was extracted too)
    <review-dir>/round-<k>/queries.json          (optional, web requests read from transcripts)
    <review-dir>/round-<k>/response.json        (from round 2 on)
    <review-dir>/round-<k>/reviews/<RID>.json
    <review-dir>/round-<k>/repairs/<RID>.json    (optional, one quote-repair pass)
    <review-dir>/round-<k>/checks.json           (optional, checker verdicts)
    <review-dir>/round-<k>/quotes.json           (written by check_quotes.py)
    <review-dir>/round-<k>/synthesis.json        (coordinator triage)

A reviewer's id is the review file's name (R1, R2, ...), never the `reviewer` field inside
it: the field is model output, and the id ends up in file names the scripts write.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

FINDING_TYPES = ("defect", "unsupported-claim", "clarification")
SEVERITIES = ("must-fix", "should-fix", "minor")
JUDGEMENTS = ("resolved", "partly", "not-resolved", "reason-accepted", "withdrawn")
QUOTED_JUDGEMENTS = ("resolved", "partly", "withdrawn")  # need a quote of the revised text
ORIGINS = ("first-read", "introduced-by-revision", "missed-earlier")
GROUPS = ("change", "author-decision", "done", "not-recommended")
ACTIONS = ("changed", "partly", "not-changed")
VERDICTS = ("upheld", "not-upheld", "unclear")
CHECK_KINDS = ("finding", "resolution", "literature")
OPEN_STATUSES = ("open", "partly", "not-resolved")
SCORE_DIMENSIONS = ("novelty", "soundness", "evidence", "clarity", "reproducibility")

ROUND_RE = re.compile(r"^round-(\d+)$")
RID_RE = re.compile(r"^R[0-9]+$")
POINT_RE = re.compile(r"^(R[0-9]+)\.([0-9]+)$")
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def safe_console() -> None:
    """Never crash on a console that cannot encode a character (a title in Chinese, a ligature)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def die(message: str, code: int = 2) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        die(f"{path}: not valid JSON ({exc})")
    except OSError as exc:
        die(f"{path}: cannot read ({exc})")


def read_json_optional(path: Path) -> Any:
    return read_json(path) if path.is_file() else None


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "; ".join(text_of(v) for v in value if text_of(v))
    if isinstance(value, dict):
        return "; ".join(f"{k}: {text_of(v)}" for k, v in value.items() if text_of(v))
    return str(value)


def enum_key(value: Any) -> str:
    """'Not resolved', 'not_resolved' and ' not-resolved' all become 'not-resolved'."""
    return re.sub(r"[\s_]+", "-", text_of(value).strip().lower())


def norm_enum(value: Any, allowed: tuple, warnings: list[str], label: str) -> str | None:
    """The allowed value `value` stands for, or None; warns when it had to be normalised."""
    raw = text_of(value)
    key = enum_key(raw)
    if key in allowed:
        if key != raw:
            warnings.append(f"{label}: {raw!r} read as {key!r}")
        return key
    warnings.append(f"{label}: {raw!r} is not one of {allowed}")
    return None


def text_units(text: str) -> int:
    """Length in words; CJK text, which has no spaces, counts one word per two characters."""
    cjk = len(CJK_RE.findall(text))
    words = len(CJK_RE.sub(" ", text).split())
    return words + (cjk + 1) // 2


def round_dirs(review_dir: Path) -> list[tuple[int, Path]]:
    """All round-<k> folders under the review directory, in round order."""
    if not review_dir.is_dir():
        die(f"{review_dir}: not a directory")
    found = []
    for child in review_dir.iterdir():
        match = ROUND_RE.match(child.name)
        if match and child.is_dir():
            found.append((int(match.group(1)), child))
    return sorted(found)


def round_number(round_dir: Path) -> int | None:
    match = ROUND_RE.match(round_dir.name)
    return int(match.group(1)) if match else None


def rid_number(rid: str) -> int:
    return int(rid[1:]) if RID_RE.match(rid) else 0


def reviewer_ids_on_disk(review_dir: Path) -> set[str]:
    """Every reviewer id that has a review file in any round."""
    return {p.stem for _, rdir in round_dirs(review_dir) for p in (rdir / "reviews").glob("*.json")
            if RID_RE.match(p.stem)}


def review_kind(review: dict) -> str:
    kind = enum_key(review.get("kind"))
    if kind in ("fresh", "returning"):
        return kind
    return "returning" if "judgements" in review else "fresh"


def review_findings(review: dict) -> list[dict]:
    """Findings a review raises: `findings` for fresh reviews, `new_findings` for returning ones."""
    key = "new_findings" if review_kind(review) == "returning" else "findings"
    return [f for f in as_list(review.get(key)) if isinstance(f, dict)]


def review_judgements(review: dict) -> list[dict]:
    return [j for j in as_list(review.get("judgements")) if isinstance(j, dict)]


def apply_repairs(review: dict, repair: dict, warnings: list[str], label: str) -> None:
    """Apply one quote-repair pass to a frozen review, in memory only.

    The review file itself is never edited; the repair file says which quotes were
    replaced and which findings the reviewer withdrew when asked for verbatim text.
    A withdrawal on repair is marked as such, so that it is never counted as the
    reviewer's own self-check.
    """
    items: dict[str, tuple[str, dict]] = {}
    for finding in review_findings(review):
        items[text_of(finding.get("id")).strip()] = ("finding", finding)
    for judgement in review_judgements(review):
        items[text_of(judgement.get("id")).strip()] = ("judgement", judgement)
    for entry in as_list(repair.get("repairs")):
        if not isinstance(entry, dict):
            continue
        iid = text_of(entry.get("id")).strip()
        kind, item = items.get(iid, ("", None))
        if item is None:
            warnings.append(f"{label}: repair for unknown id {iid!r} ignored")
            continue
        action = enum_key(entry.get("action")) or "replace"
        if action == "replace" and text_of(entry.get("quote")).strip():
            item["quote_original"] = item.get("quote", "")
            item["quote"] = text_of(entry.get("quote"))
            item["quote_repaired"] = True
        elif action == "withdraw":
            reason = text_of(entry.get("why")) or "no verbatim passage found on repair"
            if kind == "judgement":
                item["status"] = "not-resolved"
                item["note"] = (text_of(item.get("note")) + " [judgement withdrawn on quote repair]").strip()
                item["withdrawn_on_repair"] = True
            elif enum_key(item.get("status")) != "withdrawn":
                item["status"] = "withdrawn"
                item["withdrawn_reason"] = reason
                item["withdrawn_on_repair"] = True
        else:
            warnings.append(f"{label}: repair entry for {iid} has no usable action")


def load_reviews(round_dir: Path, warnings: list[str]) -> dict[str, dict]:
    """Reviews of one round keyed by reviewer id (the file name), with any repair pass applied."""
    reviews: dict[str, dict] = {}
    folder = round_dir / "reviews"
    if not folder.is_dir():
        return reviews
    paths = sorted(folder.glob("*.json"), key=lambda p: (rid_number(p.stem), p.name))
    for path in paths:
        rid = path.stem
        label = f"{round_dir.name}/reviews/{path.name}"
        if not RID_RE.match(rid):
            warnings.append(f"{label}: file name is not a reviewer id such as R3.json; skipped")
            continue
        review = read_json(path)
        if not isinstance(review, dict):
            warnings.append(f"{label}: not a JSON object, skipped")
            continue
        claimed = text_of(review.get("reviewer")).strip()
        if claimed and claimed != rid:
            warnings.append(f"{label}: reviewer field {claimed!r} differs from the file name; using {rid}")
        review["reviewer"] = rid
        repair_path = round_dir / "repairs" / f"{rid}.json"
        if repair_path.is_file():
            repair = read_json(repair_path)
            if isinstance(repair, dict):
                apply_repairs(review, repair, warnings, f"{round_dir.name}/repairs/{repair_path.name}")
        review["_file"] = label
        reviews[rid] = review
    for path in sorted((round_dir / "repairs").glob("*.json")):
        if path.stem not in reviews:
            warnings.append(f"{round_dir.name}/repairs/{path.name}: no review with this reviewer id; ignored")
    return reviews


def level_of(score: Any) -> Any:
    """A score's level: an int 1-5, the string 'not-assessed', or None when absent."""
    if isinstance(score, dict):
        score = score.get("level")
    if isinstance(score, bool):
        return None
    if isinstance(score, (int, float)):
        return int(score)
    if isinstance(score, str):
        s = score.strip().lower()
        if s.isdigit():
            return int(s)
        if s in ("not-assessed", "not assessed", "na", "n/a"):
            return "not-assessed"
    return None


SEVERITY_SYNONYMS = {
    "major": "must-fix", "critical": "must-fix", "blocking": "must-fix", "high": "must-fix", "must": "must-fix",
    "moderate": "should-fix", "medium": "should-fix", "should": "should-fix", "important": "should-fix",
    "low": "minor", "trivial": "minor", "nit": "minor",
}


def normalise_severity(value: object) -> tuple[str, bool]:
    """(severity, recognised). Unknown values become should-fix, so nothing serious is buried."""
    s = enum_key(value)
    if s in SEVERITIES:
        return s, True
    if s in SEVERITY_SYNONYMS:
        return SEVERITY_SYNONYMS[s], False
    return "should-fix", False


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def is_converted(review: dict) -> bool:
    """True for a review written before the skill or by hand and converted to its schema."""
    return review.get("converted") is True


def extra_scores_of(review: dict) -> dict:
    """The review's extra score sheet (`extra_scores`; `legacy_scores` is read as an alias)."""
    for key in ("extra_scores", "legacy_scores"):
        value = review.get(key)
        if isinstance(value, dict):
            return value
    return {}


def is_small_value(value: Any) -> bool:
    """A score-like value (number, flag, label of up to 30 characters) rather than a text field."""
    if isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= 30 and "\n" not in value


def page_map_path(text_path: Path) -> Path:
    """manuscript.txt -> manuscript.pages.json (written by extract_text.py for several PDFs)."""
    return text_path.with_name(text_path.stem + ".pages.json")


class PageMap:
    """Which pages of a joined text file belong to which document (manuscript, supplement, ...).

    Without a map every page belongs to the manuscript, and locations read "p. N".
    """

    def __init__(self, data: Any = None) -> None:
        self.documents: list[dict] = []
        for doc in as_list(as_dict(data).get("documents")):
            if not isinstance(doc, dict):
                continue
            try:
                first, pages = int(doc.get("first_page")), int(doc.get("pages"))
            except (TypeError, ValueError):
                continue
            self.documents.append({"name": text_of(doc.get("name")) or f"document {len(self.documents) + 1}",
                                   "file": text_of(doc.get("file")), "first_page": first, "pages": pages})
        self.documents.sort(key=lambda d: d["first_page"])

    @classmethod
    def for_text(cls, text_path: Path, explicit: Path | None = None) -> PageMap:
        path = explicit or page_map_path(text_path)
        return cls(read_json(path)) if path.is_file() else cls()

    def __bool__(self) -> bool:
        return len(self.documents) > 1

    @property
    def total_pages(self) -> int:
        return sum(d["pages"] for d in self.documents)

    def locate(self, page: int | None) -> tuple[int, str, int | None]:
        """(document index, document name, page within that document) of a page of the joined text."""
        if page is None or not self:
            return 0, self.documents[0]["name"] if self.documents else "manuscript", page
        for index in range(len(self.documents) - 1, -1, -1):
            doc = self.documents[index]
            if page >= doc["first_page"]:
                return index, doc["name"], page - doc["first_page"] + 1
        return 0, self.documents[0]["name"], page

    def files(self) -> list[str]:
        return [d["file"] for d in self.documents if d["file"]]
