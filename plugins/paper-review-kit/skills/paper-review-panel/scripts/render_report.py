#!/usr/bin/env python3
"""Render the panel report: change list first, then score movement, then the reviews.

usage: render_report.py REVIEW_DIR [--lang en|zh] [--format md|html|both] [--out DIR]

Builds the ledger in memory (same logic as ledger.py build, so the report can never be
staler than the files) and writes REVIEW_DIR/report/report-round-<K>.md and/or .html,
where K is the latest round. The HTML file is self-contained (inline CSS, no scripts,
light and dark themes) and works offline.

--lang chooses the headings and labels (en, zh = Simplified Chinese; default: the plan's
language when it is one of these, else en). The reviewers' own text is shown as written,
so ask reviewers to write in the user's language.

Order of the report: changes worth making; needs your decision; done; not recommended;
not yet triaged; what should not change; how the review was run; what each round changed;
stopping rule; score movement (with the plan's extra score sheet, when reviews carry
extra_scores, or legacy_scores as an alias); fresh against returning reviewers; seat
comparison; the issue ledger; warnings; appendix with every review and the authors'
responses.

plan.json may give seat_names (seat id to a display name in the report language) and
extra_score_sheet ({"name": ..., "description": ...}). A point judged partly with a
remaining_severity shows both levels ("was must-fix; what remains: should-fix"); reviews
marked "converted" and response rows marked "disagree" are labelled as such; with a page
map, quotes found in a supplement say so ("supplement p. 3").
"""

from __future__ import annotations

import argparse
import datetime
import html
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ledger as ledger_mod  # noqa: E402
from common import (  # noqa: E402
    SCORE_DIMENSIONS,
    as_dict,
    as_list,
    die,
    enum_key,
    extra_scores_of,
    is_converted,
    is_small_value,
    level_of,
    load_reviews,
    read_json_optional,
    review_findings,
    review_kind,
    round_dirs,
    safe_console,
    severity_rank,
    text_of,
    write_text,
)

LABELS = {
    "en": {
        "title": "Review panel report",
        "sub": "Round {k}. Simulated peer review by AI models, run to improve the paper; the section \"How this review was run\" says how. Generated {date}.",
        "change": "Changes worth making",
        "change_none": "No change is recommended from this round.",
        "change_intro": "Each item says where, what change would resolve it, and why. Severity is the reviewer's.",
        "author-decision": "Needs your decision",
        "author-decision_intro": "Trade-offs, scope questions or disagreements the coordinator should not settle alone.",
        "done": "Done",
        "done_intro": "Points the reviewer confirmed as resolved, quoting the revised text.",
        "not-recommended": "Not recommended",
        "not-recommended_intro": "Points the coordinator advises against acting on, each with its reason. Overrule any of them.",
        "untriaged": "Not yet triaged",
        "untriaged_intro": "Open points the coordinator has not placed in a group yet.",
        "none": "(none)",
        "keep": "What should not change",
        "keep_intro": "Parts the reviewers of the latest round advise keeping as they are.",
        "how": "How this review was run",
        "how_round": "Round {k}: {mode}; reviewer model {rmodel}; checker model {cmodel}.",
        "mode_workflow": "reviewers launched in parallel by a workflow tool, each in a fresh context",
        "mode_subagents": "reviewers launched as separate sub-agents, each in a fresh context",
        "mode_sequential": "reviews written one after another in a single context: NOT independent",
        "mode_unknown": "launch mode not recorded",
        "how_fixed": "Every reviewer read only the manuscript (returning reviewers also their own earlier review, the authors' response to their points and the previous version). Reviews were frozen before synthesis; the coordinator adds no criticism and changes no score.",
        "how_quotes": "Quotes were checked by script against the PDF's text layer in round(s) {k}.",
        "how_noquotes": "Quotes in round {k} were not checked by script (no quotes.json): treat every quote of that round as unverified.",
        "how_scores": "Model reviewers tend to score high and separate strong from weak papers poorly. Read the movement between rounds, not the levels.",
        "how_web": "Web searches recorded by reviewers: {n}.",
        "how_flags": "Search queries flagged by the privacy audit (they may have exposed the manuscript): {n}.",
        "how_transcripts": "Web requests read from the host's transcripts in round {k}: {n}; not listed by the reviewers themselves: {m}.",
        "how_converted": "Round {k}: converted reviews ({ids}), written before this skill or by hand and converted to its format. Their counter-evidence searches and reading records were not recorded, and quotes marked as chosen were picked by the coordinator.",
        "converted": "converted",
        "loc_page": "p. {p}", "loc_doc": "{d} p. {p}",
        "was_sev": "was {was}; what remains: {now}",
        "remains": "what remains: {s}",
        "disagree": "the authors disagree",
        "out_of_reach": "out of reach this round",
        "differ": "{n} other member(s) differ: {list}",
        "quote_chosen": "passage chosen during the conversion",
        "extra": "Extra score sheet: {name}",
        "extra_default": "Extra score sheet",
        "not_checked": "not checked",
        "extra_intro": "Each reviewer also filled this sheet; it is not on the anchored scale. For returning reviewers \"a -> b\" shows the movement since their previous round. Compare levels within this sheet only.",
        "extra_text": "Text fields of the extra score sheet",
        "how_seq_warn": "In round(s) {k} the reviews were written one after another in the coordinator's own context. They are not independent of each other or of the coordinator; read them as one careful reading, not as a panel.",
        "rounds": "What each round changed",
        "round_line": "Round {k}",
        "round_inline": "round {k}",
        "sep": ": ",
        "comma": ", ",
        "cond": {"no-open-must-fix": "no open must-fix point",
                 "fresh-nothing-new": "this round's fresh reviewers raised nothing new (must-fix or should-fix) that survived checking",
                 "max-rounds": "the agreed maximum number of rounds is reached"},
        "churn": {"changes-unconfirmed": "the authors report changes, but no point was confirmed resolved or partly resolved",
                  "introduced-as-many": "the revision introduced at least as many points as it resolved"},
        "decision": {"continue": "continue", "stop": "stop"},
        "res_check": "resolution check",
        "fvr_also": "also raised by a returning reviewer",
        "lit_opened": "opened", "lit_not_opened": "not opened, unverified",
        "statement": "Statement",
        "r_first": "First reading of the manuscript; nothing has been revised yet.",
        "r_raised": "Points raised: {n} ({sev}); withdrawn on the reviewers' own self-check: {w}; withdrawn on quote repair: {wr}.",
        "r_judged": "Returning reviewers' judgements: {j}.",
        "r_response": "Authors' response rows: {r}; other changes listed: {o}.",
        "r_new": "New points from returning reviewers: introduced by the revision {i}, missed earlier {m}. New serious points from fresh reviewers that survived checking: {f} (not yet checked: {u}).",
        "r_open": "Open must-fix points: {b} before, {a} after.",
        "r_churn": "Churn warning",
        "stop": "Stopping rule",
        "stop_rule": "Rule agreed before round 1: {rule}",
        "stop_norule": "No stopping rule was recorded in plan.json.",
        "stop_met": "Conditions met now: {met}.",
        "stop_none": "Conditions met now: none.",
        "stop_decision": "Coordinator's recommendation for round {k}: {d}.",
        "scores": "Score movement",
        "scores_intro": "Overall level per reviewer and round (f = fresh, r = returning, c = converted). Overall follows the most serious open point; it is not an average.",
        "scores_dims": "All levels in round {k}",
        "scores_changes": "Why returning reviewers changed scores",
        "fvr": "Fresh against returning reviewers",
        "fvr_intro": "Fresh reviewers saw only the revised manuscript. If returning reviewers score well above fresh ones of the same seat, or fresh reviewers re-raise points marked resolved, suspect capitulation. If fresh reviewers find serious points the returning ones never raised, suspect anchoring or fatigue (or a genuinely new view).",
        "fvr_unlinked": "This round has no synthesis.json yet, so fresh points are not linked to earlier ones and re-raised points cannot show below. Write the same_as marks first, then render again.",
        "fvr_reraised": "Fresh points that re-raise a closed point",
        "fvr_new": "Serious new points from fresh reviewers",
        "fvr_seats": "Overall by seat in round {k}",
        "seats": "Seat comparison",
        "seats_intro": "Counts per reviewer. A point survives checking when the checker upheld it. \"Withdrawn (self-check)\" counts the points the reviewer's own counter-evidence step dropped; points withdrawn because no verbatim quote could be found on repair are counted apart. One run per seat is an anecdote, not a measurement.",
        "ledger": "Issue ledger",
        "warnings": "Warnings from the scripts",
        "appendix": "Appendix: the reviews",
        "response": "Authors' response submitted with round {k}",
        "other_changes": "Other changes listed by the authors",
        "h_reviewer": "Reviewer", "h_seat": "Seat", "h_protocol": "Protocol", "h_raised": "Raised",
        "h_withdrawn": "Withdrawn (self-check)", "h_withdrawn_repair": "Withdrawn (quote repair)",
        "h_quotes": "Quotes found", "h_upheld": "Upheld / checked",
        "h_unique": "Unique upheld", "h_mustfix": "Must-fix upheld", "h_overall": "Overall",
        "h_round_k": "Round", "h_id": "Id", "h_severity": "Severity", "h_type": "Type", "h_round": "Raised in",
        "h_history": "Status by round", "h_now": "Now", "h_disposition": "Group",
        "h_action": "Action", "h_what": "What was done", "h_where": "Where", "h_whynot": "Why not",
        "h_status": "Status", "h_quote": "Quote", "h_note": "Note", "h_dimension": "Score", "h_level": "Level",
        "h_basis": "Basis", "h_returning": "Returning (previous -> now)", "h_fresh": "Fresh",
        "h_earlier": "Earlier point", "h_check": "Check",
        "f_where": "Where", "f_change": "Change that would resolve it", "f_why": "Why it matters",
        "f_by": "Raised by", "f_status": "Status", "f_check": "Coordinator's check", "f_reason": "Reason",
        "f_quote": "Quote", "f_newwork": "Needs new work", "f_counter": "Counter-evidence searched",
        "f_lookedfor": "Looked for", "f_lit": "Literature", "f_withdrawn": "Withdrawn because",
        "yes": "yes", "no": "no",
        "rv_reading": "Reading", "rv_summary": "Summary", "rv_contrib": "Contributions as understood",
        "rv_strengths": "Strengths", "rv_keep": "Keep as is", "rv_findings": "Points raised",
        "rv_checked": "Checked, nothing to change", "rv_questions": "Questions", "rv_injected": "Text addressed to reviewing models (ignored)",
        "rv_cannot": "Could not assess", "rv_scores": "Scores", "rv_confidence": "Confidence",
        "rv_criteria": "Step 1: what would resolve each point", "rv_judgements": "Steps 2-3: judgements",
        "rv_new": "New points (introduced by the revision or missed earlier)", "rv_changes": "Score changes",
        "rv_notes": "Protocol notes",
        "read_pages": "pages read: {p}; page images inspected: {i}; not inspected: {n}; web used: {w}; searches: {s}",
        "fresh": "fresh", "returning": "returning",
        "sev": {"must-fix": "must-fix", "should-fix": "should-fix", "minor": "minor"},
        "type": {"defect": "confirmed defect", "unsupported-claim": "claim lacking evidence", "clarification": "needs clarification"},
        "status": {"open": "open", "partly": "partly resolved", "not-resolved": "not resolved", "resolved": "resolved",
                   "resolved-unverified": "resolved, quote not found", "reason-accepted": "reason accepted",
                   "withdrawn": "withdrawn", "withdrawn-unverified": "withdrawn, quote not found"},
        "chk_nf": "checker's quote not found",
        "qc_stitched": "stitched from fragments",
        "group": {"change": "change", "author-decision": "your decision", "done": "done",
                  "not-recommended": "not recommended", "untriaged": "untriaged", "withdrawn": "withdrawn"},
        "action": {"changed": "changed", "partly": "partly", "not-changed": "not changed"},
        "verdict": {"upheld": "upheld", "not-upheld": "not upheld", "unclear": "unclear"},
        "qc": {"found": "quote found", "found-loose": "quote found (loose match)", "not-found": "quote NOT found",
               "missing": "no quote", "unchecked": "quote not checked", "not-needed": ""},
        "dim": {"novelty": "Novelty", "soundness": "Soundness", "evidence": "Evidence for the claims",
                "clarity": "Clarity", "reproducibility": "Reproducibility", "overall": "Overall", "confidence": "Confidence"},
    },
    "zh": {
        "title": "审稿面板报告",
        "sub": "第 {k} 轮。这是由 AI 模型模拟的同行评审，目的是改进论文；具体怎么跑的见「这次审稿是怎么跑的」一节。生成于 {date}。",
        "change": "值得做的修改",
        "change_none": "这一轮没有建议的修改。",
        "change_intro": "每条写明位置、怎样改能解决、为什么重要。严重度是审稿人给的。",
        "author-decision": "需要你拍板的",
        "author-decision_intro": "取舍、范围问题或审稿人之间的分歧，统筹者不宜单独决定。",
        "done": "已完成",
        "done_intro": "审稿人引用修订稿原文、确认已解决的意见。",
        "not-recommended": "不建议改的",
        "not-recommended_intro": "统筹者建议不采纳的意见，每条附理由。任何一条你都可以推翻。",
        "untriaged": "尚未分组",
        "untriaged_intro": "统筹者还没有归入任何一组的未决意见。",
        "none": "（无）",
        "keep": "不应改动的地方",
        "keep_intro": "最近一轮审稿人建议保持原样的部分。",
        "how": "这次审稿是怎么跑的",
        "how_round": "第 {k} 轮：{mode}；审稿人模型 {rmodel}；核查模型 {cmodel}。",
        "mode_workflow": "由工作流工具并行启动审稿人，每位在全新的上下文里",
        "mode_subagents": "作为独立的子代理启动审稿人，每位在全新的上下文里",
        "mode_sequential": "在同一个上下文里依次写出各份审稿：不是独立审稿",
        "mode_unknown": "没有记录启动方式",
        "how_fixed": "每位审稿人只读稿件（返场审稿人另读自己之前的审稿、作者对其意见的回复和上一版稿件）。审稿在综合之前冻结；统筹者不新增批评、不改分数。",
        "how_quotes": "第 {k} 轮的引文由脚本对照 PDF 的文字层核对过。",
        "how_noquotes": "第 {k} 轮的引文没有经过脚本核对（没有 quotes.json）：这一轮的所有引文都应视为未核实。",
        "how_scores": "模型审稿人打分普遍偏高，也很难把好论文和差论文分开。请看轮与轮之间的变化，不要看分数本身的高低。",
        "how_web": "审稿人记录的联网检索：{n} 次。",
        "how_flags": "隐私审计标出的检索（可能泄露了稿件信息）：{n} 次。",
        "how_transcripts": "第 {k} 轮从宿主的运行记录中读出的联网请求：{n} 次；审稿人自己没有列出的：{m} 次。",
        "how_converted": "第 {k} 轮：转换来的审稿（{ids}），是在本 skill 之前或手工写成、再转成本 skill 格式的。它们没有记录反证查找和阅读情况；标为「选定」的引文是统筹者挑的。",
        "converted": "转换",
        "loc_page": "第 {p} 页", "loc_doc": "{d} 第 {p} 页",
        "was_sev": "原为{was}；剩余部分：{now}",
        "remains": "剩余部分：{s}",
        "disagree": "作者不同意",
        "out_of_reach": "本轮做不到",
        "differ": "另有 {n} 条重复意见的核查结论不同：{list}",
        "quote_chosen": "转换时选定的段落",
        "extra": "另一套评分表：{name}",
        "extra_default": "另一套评分表",
        "not_checked": "未核查",
        "extra_intro": "每位审稿人还填了这套表，它不是锚定量表。返场审稿人的「a -> b」是相对其上一轮的变化。只在这套表内部比较。",
        "extra_text": "另一套评分表的文字栏",
        "how_seq_warn": "第 {k} 轮的各份审稿是在统筹者自己的上下文里依次写出的，彼此之间、与统筹者之间都不独立；只能当作一次仔细的通读，不能当作一个审稿面板。",
        "rounds": "每一轮实际改了什么",
        "round_line": "第 {k} 轮",
        "round_inline": "第 {k} 轮",
        "sep": "：",
        "comma": "，",
        "cond": {"no-open-must-fix": "没有未决的必须改意见",
                 "fresh-nothing-new": "本轮新审稿人没有提出经核查成立的新意见（必须改或应该改）",
                 "max-rounds": "已达到约定的最多轮数"},
        "churn": {"changes-unconfirmed": "作者报告做了修改，但没有一条意见被确认为已解决或部分解决",
                  "introduced-as-many": "修订引入的新意见不少于它解决的意见"},
        "decision": {"continue": "继续", "stop": "停止"},
        "res_check": "对「已解决」的核查",
        "fvr_also": "返场审稿人也提出了",
        "lit_opened": "已打开核对", "lit_not_opened": "没有打开，未核实",
        "statement": "说明",
        "r_first": "第一次读稿，还没有任何修订。",
        "r_raised": "提出意见 {n} 条（{sev}）；审稿人自己反证后撤回 {w} 条；引文修复时撤回 {wr} 条。",
        "r_judged": "返场审稿人的判定：{j}。",
        "r_response": "作者回复的条目：{r}；另列的其他修改：{o} 处。",
        "r_new": "返场审稿人的新意见：修订引入 {i} 条，之前漏看 {m} 条。新审稿人提出且经核查成立的严重新意见：{f} 条（尚未核查 {u} 条）。",
        "r_open": "未决的必须改意见：本轮前 {b} 条，本轮后 {a} 条。",
        "r_churn": "空转提示",
        "stop": "停止规则",
        "stop_rule": "第 1 轮之前约定的规则：{rule}",
        "stop_norule": "plan.json 里没有记录停止规则。",
        "stop_met": "目前满足的条件：{met}。",
        "stop_none": "目前满足的条件：无。",
        "stop_decision": "统筹者对第 {k} 轮的建议：{d}。",
        "scores": "分数变化",
        "scores_intro": "每位审稿人每轮的总分（f = 新审稿人，r = 返场审稿人，c = 转换来的审稿）。总分取决于最严重的未决意见，不是平均分。",
        "scores_dims": "第 {k} 轮的全部分项",
        "scores_changes": "返场审稿人改分的理由",
        "fvr": "新审稿人与返场审稿人的对照",
        "fvr_intro": "新审稿人只看到修订稿。如果返场审稿人的分数明显高于同一席位的新审稿人，或者新审稿人重新提出了已标为解决的意见，要怀疑讨好；如果新审稿人发现了返场审稿人从没提过的严重问题，要怀疑锚定或疲劳（也可能只是视角不同）。",
        "fvr_unlinked": "这一轮还没有 synthesis.json，新审稿人的意见还没有和之前的意见关联起来，下面看不出哪些已关闭的意见被重新提出。请先写好 same_as 标记，再重新生成报告。",
        "fvr_reraised": "新审稿人重新提出的已关闭意见",
        "fvr_new": "新审稿人提出的严重新意见",
        "fvr_seats": "第 {k} 轮各席位的总分",
        "seats": "席位对比",
        "seats_intro": "按审稿人计数。核查者维持的意见算「经核查成立」。「撤回（自查）」是审稿人自己找反证后放弃的意见；引文修复时因找不到原文而撤回的另列一栏。每个席位只跑一次，只能算个案，不算测量。",
        "ledger": "意见台账",
        "warnings": "脚本给出的警告",
        "appendix": "附录：全部审稿意见",
        "response": "随第 {k} 轮稿件提交的作者回复",
        "other_changes": "作者另列的其他修改",
        "h_reviewer": "审稿人", "h_seat": "席位", "h_protocol": "协议", "h_raised": "提出",
        "h_withdrawn": "撤回（自查）", "h_withdrawn_repair": "撤回（引文修复）",
        "h_quotes": "引文找到", "h_upheld": "成立 / 已核查",
        "h_unique": "独有且成立", "h_mustfix": "必须改且成立", "h_overall": "总分",
        "h_round_k": "轮次", "h_id": "编号", "h_severity": "严重度", "h_type": "类型", "h_round": "提出轮次",
        "h_history": "各轮状态", "h_now": "现在", "h_disposition": "分组",
        "h_action": "处理", "h_what": "做了什么", "h_where": "位置", "h_whynot": "不改的理由",
        "h_status": "状态", "h_quote": "引文", "h_note": "备注", "h_dimension": "分项", "h_level": "分数",
        "h_basis": "依据", "h_returning": "返场（上轮 -> 本轮）", "h_fresh": "新审稿人",
        "h_earlier": "之前的意见", "h_check": "核查",
        "f_where": "位置", "f_change": "怎样改能解决", "f_why": "为什么重要",
        "f_by": "提出者", "f_status": "状态", "f_check": "统筹者的核查", "f_reason": "理由",
        "f_quote": "引文", "f_newwork": "需要新工作", "f_counter": "反证查过的地方",
        "f_lookedfor": "查找过", "f_lit": "文献", "f_withdrawn": "撤回原因",
        "yes": "是", "no": "否",
        "rv_reading": "阅读情况", "rv_summary": "概括", "rv_contrib": "审稿人理解的贡献",
        "rv_strengths": "优点", "rv_keep": "保持原样", "rv_findings": "提出的意见",
        "rv_checked": "查过、无需修改", "rv_questions": "问题", "rv_injected": "稿件中写给审稿模型的文字（已忽略）",
        "rv_cannot": "无法评估", "rv_scores": "分数", "rv_confidence": "把握",
        "rv_criteria": "第一步：每条意见怎样算解决", "rv_judgements": "第二、三步：判定",
        "rv_new": "新意见（修订引入或之前漏看）", "rv_changes": "改分",
        "rv_notes": "协议备注",
        "read_pages": "读过的页：{p}；看过页面图像：{i}；没能查看：{n}；联网：{w}；检索：{s} 次",
        "fresh": "新审稿人", "returning": "返场审稿人",
        "sev": {"must-fix": "必须改", "should-fix": "应该改", "minor": "次要"},
        "type": {"defect": "已证实的缺陷", "unsupported-claim": "缺证据的主张", "clarification": "需要澄清"},
        "status": {"open": "未决", "partly": "部分解决", "not-resolved": "未解决", "resolved": "已解决",
                   "resolved-unverified": "标为已解决但引文没找到", "reason-accepted": "接受不改的理由",
                   "withdrawn": "已撤回", "withdrawn-unverified": "标为撤回但引文没找到"},
        "chk_nf": "核查者的引文没找到",
        "qc_stitched": "由零散片段拼成",
        "group": {"change": "要改", "author-decision": "你来定", "done": "已完成",
                  "not-recommended": "不建议改", "untriaged": "未分组", "withdrawn": "已撤回"},
        "action": {"changed": "已改", "partly": "部分改", "not-changed": "未改"},
        "verdict": {"upheld": "成立", "not-upheld": "不成立", "unclear": "说不清"},
        "qc": {"found": "引文已找到", "found-loose": "引文已找到（宽松匹配）", "not-found": "引文没找到",
               "missing": "没有引文", "unchecked": "引文未核对", "not-needed": ""},
        "dim": {"novelty": "新颖性", "soundness": "方法正确性", "evidence": "主张的证据",
                "clarity": "清楚程度", "reproducibility": "可复现性", "overall": "总分", "confidence": "把握"},
    },
}

CSS = """
:root{--bg:#fafaf8;--fg:#1d1d1b;--mute:#666660;--card:#ffffff;--line:#dcdcd4;--must:#b3392f;--should:#a86f0c;--minor:#4a6f8a;--ok:#2e7d4f;--acc:#2b5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#e8e8e2;--mute:#a3a39b;--card:#20201d;--line:#3b3b35;--must:#ef7d72;--should:#e0b050;--minor:#8ab8e0;--ok:#6cc08e;--acc:#8ab8e0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 -apple-system,"Segoe UI","Noto Sans","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 6px}h2{font-size:21px;margin:38px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:17px;margin:24px 0 8px}h4{font-size:15px;margin:18px 0 6px}
p{margin:8px 0}.note{color:var(--mute);font-size:14px}.sub{color:var(--mute)}.warn{color:var(--must)}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:10px 16px;margin:10px 0}
.card.must-fix{border-left-color:var(--must)}.card.should-fix{border-left-color:var(--should)}.card.minor{border-left-color:var(--minor)}
.card .t{font-weight:600}.card dl{margin:6px 0 0;display:grid;grid-template-columns:max-content 1fr;gap:2px 14px}
.card dt{color:var(--mute);font-size:14px}.card dd{margin:0}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:15px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--mute);font-weight:600;font-size:14px}
ul{padding-left:22px;margin:6px 0}li{margin:4px 0}
"""


class Doc:
    """A tiny block model rendered to both Markdown and HTML, so the two never disagree."""

    def __init__(self, sep: str = ": ") -> None:
        self.blocks: list[tuple] = []
        self.sep = sep

    def h(self, level: int, text: str) -> None:
        self.blocks.append(("h", level, text))

    def p(self, text: str, cls: str = "") -> None:
        if text:
            self.blocks.append(("p", text, cls))

    def ul(self, items: list[str], empty: str = "") -> None:
        items = [i for i in items if i]
        if items:
            self.blocks.append(("ul", items))
        elif empty:
            self.p(empty, "note")

    def table(self, header: list[str], rows: list[list[str]], empty: str = "") -> None:
        if rows:
            self.blocks.append(("table", header, rows))
        elif empty:
            self.p(empty, "note")

    def card(self, title: str, cls: str, fields: list[tuple[str, str]]) -> None:
        self.blocks.append(("card", title, cls, [(k, v) for k, v in fields if v]))

    def markdown(self) -> str:
        out: list[str] = []
        for block in self.blocks:
            kind = block[0]
            if kind == "h":
                out += ["#" * block[1] + " " + one_line(block[2]), ""]
            elif kind == "p":
                text = block[1].replace("\n", "  \n")
                out += [f"*{text}*" if block[2] == "note" else text, ""]
            elif kind == "ul":
                out += [f"- {one_line(i)}" for i in block[1]] + [""]
            elif kind == "table":
                out.append("| " + " | ".join(md_cell(h) for h in block[1]) + " |")
                out.append("|" + "---|" * len(block[1]))
                out += ["| " + " | ".join(md_cell(c) for c in row) + " |" for row in block[2]]
                out.append("")
            elif kind == "card":
                out.append(f"- **{one_line(block[1])}**")
                out += [f"  - {one_line(k)}{self.sep}{one_line(v)}" for k, v in block[3]]
                out.append("")
        return "\n".join(out).rstrip() + "\n"

    def html(self, title: str, lang: str) -> str:
        out: list[str] = []
        for block in self.blocks:
            kind = block[0]
            if kind == "h":
                out.append(f"<h{block[1]}>{esc(block[2])}</h{block[1]}>")
            elif kind == "p":
                cls = f' class="{block[2]}"' if block[2] else ""
                out.append(f"<p{cls}>{esc(block[1])}</p>")
            elif kind == "ul":
                out.append("<ul>" + "".join(f"<li>{esc(i)}</li>" for i in block[1]) + "</ul>")
            elif kind == "table":
                head = "".join(f"<th>{esc(h)}</th>" for h in block[1])
                rows = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in block[2])
                out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
            elif kind == "card":
                fields = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in block[3])
                out.append(f'<div class="card {block[2]}"><div class="t">{esc(block[1])}</div><dl>{fields}</dl></div>')
        html_lang = "zh-CN" if lang == "zh" else "en"
        return (
            f'<!doctype html>\n<html lang="{html_lang}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f'<body><div class="wrap">\n' + "\n".join(out) + "\n</div></body></html>\n"
        )


def esc(text: object) -> str:
    return html.escape(text_of(text), quote=True).replace("\n", "<br>")


def one_line(text: object) -> str:
    return " ".join(text_of(text).split())


def md_cell(text: object) -> str:
    return one_line(text).replace("|", "\\|") or "-"


def clip(text: str, n: int = 220) -> str:
    text = one_line(text)
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class Report:
    def __init__(self, review_dir: Path, lang: str) -> None:
        self.dir = review_dir
        self.L = LABELS[lang]
        self.lang = lang
        self.ledger = ledger_mod.build(review_dir)
        self.issues = {e["id"]: e for e in self.ledger["issues"]}
        self.reviewers = {r["reviewer"]: r for r in self.ledger["reviewers"]}
        self.k = self.ledger["last_round"]
        self.reviews: dict[int, dict[str, dict]] = {}
        self.responses: dict[int, dict] = {}
        for k, rdir in round_dirs(review_dir):
            self.reviews[k] = load_reviews(rdir, [])
            response = read_json_optional(rdir / "response.json")
            if isinstance(response, dict):
                self.responses[k] = response
        self.doc = Doc(self.L["sep"])
        self.quotes = {k: read_json_optional(rdir / "quotes.json") or {} for k, rdir in round_dirs(review_dir)}

    # --- small label helpers -------------------------------------------------
    def lab(self, table: str, key: object) -> str:
        return self.L[table].get(text_of(key), text_of(key))

    def seat(self, name: object) -> str:
        """The seat's display name from plan.json's seat_names, else the seat id."""
        names = as_dict(self.ledger["plan"].get("seat_names"))
        return text_of(names.get(text_of(name))) or text_of(name)

    def where_found(self, location: object) -> str:
        """'p. 3' or 'supplement p. 3', when a page map located the quote; else ''."""
        loc = as_dict(location)
        if loc.get("page") is None:
            return ""
        if not loc.get("index"):
            return self.L["loc_page"].format(p=loc["page"])
        return self.L["loc_doc"].format(d=text_of(loc.get("document")), p=loc["page"])

    def sev_text(self, raised: str, now: str) -> str:
        if not now or now == raised:
            return self.lab("sev", raised)
        return self.L["was_sev"].format(was=self.lab("sev", raised), now=self.lab("sev", now))

    def who(self, iid: str) -> str:
        e = self.issues[iid]
        info = self.reviewers.get(e["reviewer"], {})
        kind = self.L.get(info.get("rounds", {}).get(e["raised_in"], ""), "")
        converted = self.L["converted"] if e["raised_in"] in info.get("converted", []) else ""
        bits = [b for b in (self.seat(e["seat"]), kind, converted, e["protocol"] if e["protocol"] != "built-in" else "") if b]
        return f"{e['reviewer']} ({self.L['comma'].join(bits)}; {self.L['round_inline'].format(k=e['raised_in'])})"

    def status_text(self, e: dict) -> str:
        parts = []
        for h in e["history"]:
            status = ledger_mod.history_status(h)
            text = self.lab("status", status)
            if h.get("remaining_severity"):
                text += f" ({self.L['remains'].format(s=self.lab('sev', h['remaining_severity']))})"
            parts.append(f"{self.L['round_inline'].format(k=h['round'])}{self.L['sep']}{text}")
        return "; ".join(parts)

    def check_text(self, iid: str, verdict: str, note: str, downgraded: bool, prefix: str = "") -> str:
        text = f"{iid} {prefix}{self.lab('verdict', verdict)}"
        if downgraded:
            text += f" [{self.L['chk_nf']}]"
        return text + (f" ({note})" if note else "")

    def quote_text(self, quote: str, quote_check: str, stitched: bool, full: bool = False,
                   location: object = None, chosen: bool = False) -> str:
        label = self.lab("qc", quote_check)
        for extra in (self.where_found(location), self.L["qc_stitched"] if stitched else "",
                      self.L["quote_chosen"] if chosen else ""):
            if extra:
                label += f"{self.L['comma']}{extra}" if label else extra
        return f"\"{text_of(quote) if full else clip(quote)}\" [{label}]"

    # --- sections ---------------------------------------------------------------
    def group_cards(self, disposition: str, show_reason: bool) -> int:
        groups = [g for g in self.ledger["groups"] if g["disposition"] == disposition]
        for g in groups:
            e = self.issues[g["id"]]
            ids = " + ".join(g["members"])
            severity = self.sev_text(g.get("raised_severity") or g["severity"], g["severity"])
            title = f"[{severity}] {ids}{self.L['sep']}{e['title'] or clip(e['resolution'], 80)}"
            checks = []
            for m in g["members"]:
                x = self.issues[m]
                if x["check"]:
                    checks.append(self.check_text(m, x["check"], x["check_note"], x.get("check_downgraded", False)))
                last = x["history"][-1]
                if last.get("check"):
                    checks.append(self.check_text(m, last["check"], last.get("check_note", ""),
                                                  last.get("check_downgraded", False), f"{self.L['res_check']} "))
            check = "; ".join(checks)
            fields = [
                (self.L["f_where"], e["where"]),
                (self.L["f_change"], e["resolution"]),
                (self.L["f_why"], e["why"]),
                (self.L["f_quote"], self.quote_text(e["quote"], e["quote_check"], e.get("quote_stitched", False),
                                                    location=e.get("quote_location"), chosen=bool(e.get("quote_chosen")))
                 if e["quote"] else ""),
                (self.L["f_by"], "; ".join(self.who(m) for m in g["members"])),
                (self.L["f_status"], "; ".join(f"{m}: {self.status_text(self.issues[m])}" for m in g["members"])),
                (self.L["f_newwork"], self.L["yes"] if any(self.issues[m]["needs_new_work"] for m in g["members"]) else ""),
                (self.L["f_check"], check),
                (self.L["f_reason"], g["reason"] if show_reason else ""),
            ]
            self.doc.card(title, g["severity"], fields)
        return len(groups)

    def change_list(self) -> None:
        d = self.doc
        d.h(2, self.L["change"])
        d.p(self.L["change_intro"], "note")
        if not self.group_cards("change", show_reason=True):
            d.p(self.L["change_none"])
        for disposition in ("author-decision", "done", "not-recommended"):
            d.h(2, self.L[disposition])
            d.p(self.L[f"{disposition}_intro"], "note")
            if not self.group_cards(disposition, show_reason=True):
                d.p(self.L["none"], "note")
        if any(g["disposition"] == "untriaged" for g in self.ledger["groups"]):
            d.h(2, self.L["untriaged"])
            d.p(self.L["untriaged_intro"], "note")
            self.group_cards("untriaged", show_reason=False)

    def keep(self) -> None:
        d = self.doc
        d.h(2, self.L["keep"])
        d.p(self.L["keep_intro"], "note")
        items = []
        for rid, review in self.reviews.get(self.k, {}).items():
            for item in as_list(review.get("keep_as_is")):
                if isinstance(item, dict):
                    items.append(f"{rid}: {text_of(item.get('where'))}: {text_of(item.get('why'))}")
                elif text_of(item):
                    items.append(f"{rid}: {text_of(item)}")
        d.ul(items, self.L["none"])

    def how(self) -> None:
        d = self.doc
        d.h(2, self.L["how"])
        plan = self.ledger["plan"]
        lines = []
        for r in self.ledger["rounds"]:
            launch = as_dict(r.get("launch"))
            mode = enum_key(launch.get("mode")) or "unknown"
            mode_text = self.L.get(f"mode_{mode}", self.L["mode_unknown"])
            if text_of(launch.get("notes")):
                mode_text += f" ({text_of(launch.get('notes'))})"
            lines.append(self.L["how_round"].format(
                k=r["round"], mode=mode_text,
                rmodel=text_of(launch.get("reviewer_model")) or text_of(plan.get("reviewer_model")) or "?",
                cmodel=text_of(launch.get("checker_model")) or text_of(plan.get("checker_model")) or "?"))
        d.ul(lines)
        sequential = [str(r["round"]) for r in self.ledger["rounds"] if enum_key(as_dict(r.get("launch")).get("mode")) == "sequential"]
        if sequential:
            d.p(self.L["how_seq_warn"].format(k=self.L["comma"].join(sequential)), "warn")
        if len(sequential) < len(self.ledger["rounds"]):
            d.p(self.L["how_fixed"])
        checked = [str(r["round"]) for r in self.ledger["rounds"] if r.get("quotes_checked")]
        if checked:
            d.p(self.L["how_quotes"].format(k=self.L["comma"].join(checked)))
        for r in self.ledger["rounds"]:
            if not r.get("quotes_checked"):
                d.p(self.L["how_noquotes"].format(k=r["round"]), "warn")
        for k in sorted(self.reviews):
            converted = [rid for rid, rv in self.reviews[k].items() if is_converted(rv)]
            if converted:
                d.p(self.L["how_converted"].format(k=k, ids=self.L["comma"].join(converted)), "note")
        searches = sum(len(as_list(as_dict(rv.get("reading")).get("searches")))
                       for per_round in self.reviews.values() for rv in per_round.values())
        d.p(self.L["how_web"].format(n=searches))
        for k, q in sorted(self.quotes.items()):
            audit = as_dict(q.get("transcript_audit"))
            if audit:
                unlisted = [x for x in as_list(audit.get("unlisted")) if isinstance(x, dict)]
                d.p(self.L["how_transcripts"].format(k=k, n=audit.get("requests", 0), m=len(unlisted)))
                d.ul([f"{text_of(x.get('reviewer'))} ({text_of(x.get('kind'))}): \"{text_of(x.get('query'))}\"" for x in unlisted])
        flags = [f for q in self.quotes.values() for f in as_list(q.get("search_flags")) if isinstance(f, dict)]
        if flags:
            d.p(self.L["how_flags"].format(n=len(flags)), "warn")
            d.ul([f"{text_of(f.get('reviewer'))}: \"{text_of(f.get('query'))}\" ({'; '.join(as_list(f.get('flags')))})" for f in flags])
        d.p(self.L["how_scores"], "note")

    def rounds(self) -> None:
        d = self.doc
        d.h(2, self.L["rounds"])
        for r in self.ledger["rounds"]:
            d.h(3, self.L["round_line"].format(k=r["round"]))
            comma = self.L["comma"]
            sev = comma.join(f"{self.lab('sev', s)} {r['raised_by_severity'].get(s, 0)}" for s in ("must-fix", "should-fix", "minor"))
            lines = []
            if r["round"] == 1:
                lines.append(self.L["r_first"])
            lines.append(self.L["r_raised"].format(n=r["raised"], sev=sev, w=r["withdrawn_on_self_check"],
                                                   wr=r.get("withdrawn_on_repair", 0)))
            if r["round"] > 1:
                judged = comma.join(f"{self.lab('status', s)} {n}" for s, n in sorted(r["judged"].items())) or self.L["none"]
                resp = comma.join(f"{self.lab('action', a)} {n}" for a, n in sorted(r["response"].items())) or self.L["none"]
                origins = r["raised_by_origin"]
                lines.append(self.L["r_judged"].format(j=judged))
                lines.append(self.L["r_response"].format(r=resp, o=r["other_changes"]))
                lines.append(self.L["r_new"].format(i=origins.get("introduced-by-revision", 0), m=origins.get("missed-earlier", 0),
                                                    f=len(r["fresh_new_surviving"]), u=len(r["fresh_new_unchecked"])))
            lines.append(self.L["r_open"].format(b=r["open_must_fix_before"], a=r["open_must_fix_after"]))
            lines += [f"{self.L['r_churn']}{self.L['sep']}{self.lab('churn', c)}" for c in r["churn"]]
            d.ul(lines)
            if r["statement"]:
                d.p(f"{self.L['statement']}{self.L['sep']}{r['statement']}")

    def stopping(self) -> None:
        d = self.doc
        stop = self.ledger["stopping"]
        if not stop:
            return
        d.h(2, self.L["stop"])
        d.p(self.L["stop_rule"].format(rule=stop["rule"]) if stop["rule"] else self.L["stop_norule"])
        met = [self.lab("cond", c) for c in stop["conditions_met"]]
        d.p(self.L["stop_met"].format(met="; ".join(met)) if met else self.L["stop_none"])
        decision = as_dict(self.ledger["rounds"][-1].get("decision"))
        if decision:
            text = self.lab("decision", enum_key(decision.get("decision")))
            if text_of(decision.get("note")):
                text += f" ({text_of(decision.get('note'))})"
            d.p(self.L["stop_decision"].format(k=self.k, d=text))

    def scores(self) -> None:
        d = self.doc
        d.h(2, self.L["scores"])
        d.p(self.L["scores_intro"], "note")
        rounds = [r["round"] for r in self.ledger["rounds"]]
        rows = []
        for rid, info in self.reviewers.items():
            row = [rid, self.seat(info["seat"])]
            for k in rounds:
                s = info["scores"].get(k)
                mark = ("f" if s["kind"] == "fresh" else "r") + (", c" if k in info.get("converted", []) else "") if s else ""
                row.append(f"{text_of(s['overall'])} ({mark})" if s else "")
            rows.append(row)
        d.table([self.L["h_reviewer"], self.L["h_seat"]] + [self.L["round_line"].format(k=k) for k in rounds], rows, self.L["none"])
        d.h(3, self.L["scores_dims"].format(k=self.k))
        dims = list(SCORE_DIMENSIONS) + ["overall", "confidence"]
        rows = []
        for rid, review in self.reviews.get(self.k, {}).items():
            scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
            row = [rid]
            for dim in dims:
                value = review.get(dim) if dim in ("overall", "confidence") else scores.get(dim)
                level = level_of(value)
                row.append(text_of(level) if level is not None else "")
            rows.append(row)
        d.table([self.L["h_reviewer"]] + [self.lab("dim", x) for x in dims], rows, self.L["none"])
        changes = []
        for rid, info in self.reviewers.items():
            for c in as_list(info["scores"].get(self.k, {}).get("changes")):
                changes.append(f"{rid}: {self.lab('dim', c.get('score'))} {text_of(c.get('from'))} -> {text_of(c.get('to'))}: "
                               f"{', '.join(text_of(b) for b in as_list(c.get('because')))}")
        if changes:
            d.h(3, self.L["scores_changes"])
            d.ul(changes)
        self.extra_scores()

    def extra_scores(self) -> None:
        """The plan's extra score sheet (a venue's form, or the form of a round run before the skill)."""
        sheet = as_dict(self.ledger["plan"].get("extra_score_sheet"))
        cells: list[tuple[int, str, dict]] = []
        for k in sorted(self.reviews):
            for rid, review in self.reviews[k].items():
                extra = extra_scores_of(review)
                if extra:
                    cells.append((k, rid, extra))
        if not cells:
            return
        d = self.doc
        name = text_of(sheet.get("name"))
        d.h(3, self.L["extra"].format(name=name) if name else self.L["extra_default"])
        if text_of(sheet.get("description")):
            d.p(text_of(sheet.get("description")))
        d.p(self.L["extra_intro"], "note")
        keys: list[str] = []
        for _, _, extra in cells:
            keys += [key for key, value in extra.items() if is_small_value(value) and key not in keys]
        latest: dict[str, dict] = {}
        rows = []
        for k, rid, extra in cells:
            before = latest.get(rid, {}) if self.reviewers.get(rid, {}).get("rounds", {}).get(k) == "returning" else {}
            row = [rid, self.seat(self.reviewers.get(rid, {}).get("seat", "")), self.L["round_line"].format(k=k)]
            for key in keys:
                now, prev = extra.get(key), before.get(key)
                if now is None or not is_small_value(now):
                    row.append("")
                elif prev is not None and is_small_value(prev) and prev != now:
                    row.append(f"{text_of(prev)} -> {text_of(now)}")
                else:
                    row.append(text_of(now))
            rows.append(row)
            latest[rid] = extra
        d.table([self.L["h_reviewer"], self.L["h_seat"], self.L["h_round_k"]] + keys, rows)

    def fresh_vs_returning(self) -> None:
        fvr = self.ledger["fresh_vs_returning"]
        if not fvr:
            return
        d = self.doc
        d.h(2, self.L["fvr"])
        d.p(self.L["fvr_intro"], "note")
        if fvr.get("note"):
            d.p(fvr["note"], "warn")
            return
        if fvr.get("unlinked"):
            d.p(self.L["fvr_unlinked"], "warn")
        d.h(3, self.L["fvr_seats"].format(k=fvr["round"]))
        rows = []
        for seat, row in fvr["by_seat"].items():
            ret = ", ".join(f"{x['reviewer']} {text_of(x['previous'])} -> {text_of(x['overall'])}" for x in row["returning"])
            fresh = ", ".join(f"{x['reviewer']} {text_of(x['overall'])}" for x in row["fresh"])
            rows.append([self.seat(seat), ret, fresh])
        d.table([self.L["h_seat"], self.L["h_returning"], self.L["h_fresh"]], rows, self.L["none"])
        d.h(3, self.L["fvr_reraised"])
        d.table([self.L["h_id"], self.L["h_earlier"], self.L["h_status"], self.L["h_check"]],
                [[x["fresh"], x["earlier"], self.lab("status", x["earlier_status"]), self.lab("verdict", x["check"] or "")]
                 for x in fvr["reraised_after_closing"]], self.L["none"])
        d.h(3, self.L["fvr_new"])
        rows = []
        for x in fvr["new_from_fresh"]:
            # One verdict per group: the head's (listed first), and how many other members differ.
            verdict = self.lab("verdict", x["check"] or "")
            differ = as_dict(x.get("check_differs"))
            if differ:
                listing = self.L["comma"].join(f"{m} {self.lab('verdict', v)}" for m, v in differ.items())
                verdict = f"{verdict or self.L['not_checked']} ({self.L['differ'].format(n=len(differ), list=listing)})"
            ids = [x["id"]] + [m for m in x["members"] if m != x["id"]]
            rows.append([" + ".join(ids), self.lab("sev", x["severity"]), verdict,
                         self.L["yes"] if x["also_raised_by_returning"] else self.L["no"]])
        d.table([self.L["h_id"], self.L["h_severity"], self.L["h_check"], self.L["fvr_also"]], rows, self.L["none"])

    def seats(self) -> None:
        d = self.doc
        d.h(2, self.L["seats"])
        d.p(self.L["seats_intro"], "note")
        rows = []
        for s in self.ledger["seats"]:
            overall = ", ".join(f"{k}: {text_of(v)}" for k, v in s["overall"].items())
            rows.append([s["reviewer"], self.seat(s["seat"]), s["protocol"], str(s["raised"]), str(s["withdrawn_on_self_check"]),
                         str(s.get("withdrawn_on_repair", 0)),
                         f"{s['quotes_found']} / {s['kept']}", f"{s['upheld']} / {s['checked']}", str(s["unique_upheld"]),
                         str(s["must_fix_upheld"]), overall])
        d.table([self.L[h] for h in ("h_reviewer", "h_seat", "h_protocol", "h_raised", "h_withdrawn", "h_withdrawn_repair",
                                     "h_quotes", "h_upheld", "h_unique", "h_mustfix", "h_overall")], rows, self.L["none"])

    def ledger_table(self) -> None:
        d = self.doc
        d.h(2, self.L["ledger"])
        group_of = {m: g for g in self.ledger["groups"] for m in g["members"]}
        rows = []
        for e in sorted(self.issues.values(), key=lambda x: (x["raised_in"], x["reviewer"], x["id"])):
            g = group_of.get(e["id"], {})
            severity = self.sev_text(e["severity"], e.get("current_severity", e["severity"]) if e["open"] else e["severity"])
            rows.append([e["id"], severity, self.lab("type", e["type"]), str(e["raised_in"]),
                         self.status_text(e), self.lab("status", e["status"]),
                         self.lab("group", g.get("disposition", "")) + (f" ({g['id']})" if g and g["id"] != e["id"] else "")])
        d.table([self.L[h] for h in ("h_id", "h_severity", "h_type", "h_round", "h_history", "h_now", "h_disposition")],
                rows, self.L["none"])
        if self.ledger["warnings"]:
            d.h(2, self.L["warnings"])
            d.ul(self.ledger["warnings"])

    def finding_card(self, f: dict, rid: str) -> None:
        iid = text_of(f.get("id"))
        e = self.issues.get(iid, {})
        counter = f.get("counter_evidence") if isinstance(f.get("counter_evidence"), dict) else {}
        lit = []
        for x in as_list(f.get("literature")):
            if isinstance(x, dict):
                opened = self.L["lit_opened"] if x.get("opened") else self.L["lit_not_opened"]
                lit.append(f"{text_of(x.get('ref'))} ({opened}){self.L['sep']}{text_of(x.get('relation'))}")
        status = "withdrawn" if enum_key(f.get("status")) == "withdrawn" else "open"
        title = f"[{self.lab('sev', f.get('severity'))}] {iid}{self.L['sep']}{text_of(f.get('title'))}"
        if f.get("origin"):
            title += f" ({text_of(f.get('origin'))})"
        if status == "withdrawn":
            title += f" [{self.lab('status', 'withdrawn')}]"
        self.doc.card(title, text_of(f.get("severity")), [
            (self.L["h_type"], self.lab("type", f.get("type"))),
            (self.L["f_where"], text_of(f.get("where"))),
            (self.L["f_quote"], self.quote_text(text_of(f.get("quote")), e.get("quote_check", "unchecked"),
                                                e.get("quote_stitched", False), full=True, location=e.get("quote_location"),
                                                chosen=f.get("quote_chosen") is True) if f.get("quote") else ""),
            (self.L["f_why"], text_of(f.get("why"))),
            (self.L["f_change"], text_of(f.get("resolution"))),
            (self.L["f_newwork"], self.L["yes"] if f.get("needs_new_work") else ""),
            (self.L["f_counter"], " ".join(x for x in (text_of(counter.get("looked_at")), text_of(counter.get("outcome")),
                                                       text_of(counter.get("note"))) if x)),
            (self.L["f_lookedfor"], text_of(f.get("looked_for"))),
            (self.L["f_lit"], "; ".join(lit)),
            (self.L["f_withdrawn"], text_of(f.get("withdrawn_reason")) if status == "withdrawn" else ""),
        ])

    def review_section(self, k: int, rid: str, review: dict) -> None:
        d, L = self.doc, self.L
        kind = review_kind(review)
        protocol = text_of(review.get("protocol")) or "built-in"
        d.h(3, f"{rid}{L['sep']}{self.seat(review.get('seat'))} ({L[kind]}{L['comma']}{L['round_inline'].format(k=k)}"
               + (f"{L['comma']}{protocol}" if protocol != "built-in" else "")
               + (f"{L['comma']}{L['converted']}" if is_converted(review) else "") + ")")
        reading = review.get("reading") if isinstance(review.get("reading"), dict) else {}
        d.p(L["read_pages"].format(
            p=text_of(reading.get("pages_read")) or "?", i=L["yes"] if reading.get("page_images") else L["no"],
            n=text_of(reading.get("not_inspected")) or L["none"], w=L["yes"] if reading.get("web_used") else L["no"],
            s=len(as_list(reading.get("searches")))), "note")
        if kind == "fresh":
            d.h(4, L["rv_summary"])
            d.p(text_of(review.get("summary")))
            d.h(4, L["rv_contrib"])
            d.ul([text_of(c) for c in as_list(review.get("contributions"))], L["none"])
        d.h(4, L["rv_strengths"])
        d.ul([f"{text_of(s.get('point'))} ({text_of(s.get('where'))})" if isinstance(s, dict) else text_of(s)
              for s in as_list(review.get("strengths"))], L["none"])
        d.h(4, L["rv_keep"])
        d.ul([f"{text_of(s.get('where'))}: {text_of(s.get('why'))}" if isinstance(s, dict) else text_of(s)
              for s in as_list(review.get("keep_as_is"))], L["none"])
        if kind == "returning":
            d.h(4, L["rv_criteria"])
            d.table([L["h_id"], L["f_change"]],
                    [[text_of(c.get("id")), text_of(c.get("would_resolve"))] for c in as_list(review.get("criteria")) if isinstance(c, dict)],
                    L["none"])
            d.h(4, L["rv_judgements"])
            rows = []
            for j in as_list(review.get("judgements")):
                if not isinstance(j, dict):
                    continue
                iid = text_of(j.get("id"))
                hist = next((h for h in self.issues.get(iid, {}).get("history", [])
                             if h["round"] == k and h.get("event") == "judged"), {})
                status = ledger_mod.history_status(hist) if hist else enum_key(j.get("status"))
                status_label = self.lab("status", status)
                if hist.get("remaining_severity"):
                    status_label += f" ({L['remains'].format(s=self.lab('sev', hist['remaining_severity']))})"
                note = " ".join(x for x in (text_of(j.get("note")), text_of(j.get("response_check"))) if x)
                quote = text_of(j.get("quote"))
                rows.append([iid, status_label, text_of(j.get("where")),
                             self.quote_text(quote, hist.get("quote_check", ""), hist.get("quote_stitched", False), full=True,
                                             location=hist.get("quote_location"))
                             if quote else "", note])
            d.table([L["h_id"], L["h_status"], L["h_where"], L["h_quote"], L["h_note"]], rows, L["none"])
        d.h(4, L["rv_new"] if kind == "returning" else L["rv_findings"])
        findings = review_findings(review)
        for f in sorted(findings, key=lambda x: (text_of(x.get("status")) == "withdrawn", severity_rank(text_of(x.get("severity"))))):
            self.finding_card(f, rid)
        if not findings:
            d.p(L["none"], "note")
        d.h(4, L["rv_checked"])
        d.ul([text_of(x) for x in as_list(review.get("checked_without_findings"))], L["none"])
        injected = [f"{text_of(x.get('where'))}: \"{text_of(x.get('quote'))}\"" for x in as_list(review.get("injected_instructions")) if isinstance(x, dict)]
        if injected:
            d.h(4, L["rv_injected"])
            d.ul(injected)
        d.h(4, L["rv_scores"])
        scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
        rows = []
        for dim in SCORE_DIMENSIONS:
            s = scores.get(dim)
            rows.append([self.lab("dim", dim), text_of(level_of(s)), text_of(s.get("basis")) if isinstance(s, dict) else ""])
        overall = review.get("overall") if isinstance(review.get("overall"), dict) else {}
        rows.append([self.lab("dim", "overall"), text_of(level_of(review.get("overall"))), text_of(overall.get("driven_by"))])
        conf = review.get("confidence") if isinstance(review.get("confidence"), dict) else {}
        rows.append([self.lab("dim", "confidence"), text_of(level_of(review.get("confidence"))), text_of(conf.get("basis"))])
        d.table([L["h_dimension"], L["h_level"], L["h_basis"]], rows)
        if kind == "returning" and as_list(review.get("score_changes")):
            d.h(4, L["rv_changes"])
            d.ul([f"{self.lab('dim', c.get('score'))}: {text_of(c.get('from'))} -> {text_of(c.get('to'))} "
                  f"({', '.join(text_of(b) for b in as_list(c.get('because')))})"
                  for c in as_list(review.get("score_changes")) if isinstance(c, dict)])
        extra = extra_scores_of(review)
        if extra:
            name = text_of(as_dict(self.ledger["plan"].get("extra_score_sheet")).get("name"))
            d.h(4, L["extra"].format(name=name) if name else L["extra_default"])
            d.p(L["comma"].join(f"{key} {text_of(value)}" for key, value in extra.items() if is_small_value(value)))
            texts = [(key, value) for key, value in extra.items() if not is_small_value(value) and text_of(value)]
            if texts:
                d.p(L["extra_text"], "note")
            for key, value in texts:
                d.p(f"{key}{L['sep']}{text_of(value)}")
        d.h(4, L["rv_questions"])
        d.ul([text_of(q) for q in as_list(review.get("questions"))], L["none"])
        d.h(4, L["rv_cannot"])
        d.ul([text_of(q) for q in as_list(review.get("could_not_assess"))], L["none"])
        if text_of(review.get("protocol_notes")):
            d.h(4, L["rv_notes"])
            d.p(text_of(review.get("protocol_notes")))

    def response_section(self, k: int, response: dict) -> None:
        d, L = self.doc, self.L
        d.h(3, L["response"].format(k=k))
        by_reviewer: dict[str, list[dict]] = {}
        for a in as_list(response.get("answers")):
            if isinstance(a, dict):
                rid = self.issues.get(text_of(a.get("id")), {}).get("reviewer", "?")
                by_reviewer.setdefault(rid, []).append(a)
        for rid, answers in sorted(by_reviewer.items()):
            d.h(4, f"{L['h_reviewer']} {rid}")
            rows = []
            for a in answers:
                iid = text_of(a.get("id"))
                action = self.lab("action", a.get("action"))
                if a.get("disagree") is True:
                    action += f" ({L['disagree']})"
                if a.get("out_of_reach") is True:
                    action += f" ({L['out_of_reach']})"
                row = next((r for r in self.issues.get(iid, {}).get("response", []) if r["round"] == k), {})
                found = self.where_found(row.get("quote_location"))
                where = text_of(a.get("where")) + (f" [{L['f_quote']}{L['sep']}{found}]" if found else "")
                rows.append([iid, action, text_of(a.get("what")), where, text_of(a.get("why_not"))])
            d.table([L["h_id"], L["h_action"], L["h_what"], L["h_where"], L["h_whynot"]], rows)
        others = [f"{text_of(o.get('what'))} ({text_of(o.get('where'))})" for o in as_list(response.get("other_changes")) if isinstance(o, dict)]
        if others:
            d.h(4, L["other_changes"])
            d.ul(others)

    def build(self) -> Doc:
        L = self.L
        label = text_of(self.ledger["plan"].get("label"))
        self.doc.h(1, L["title"] + (f"{L['sep']}{label}" if label else ""))
        self.doc.p(L["sub"].format(k=self.k, date=datetime.date.today().isoformat()), "sub")
        self.change_list()
        self.keep()
        self.how()
        self.rounds()
        self.stopping()
        self.scores()
        self.fresh_vs_returning()
        self.seats()
        self.ledger_table()
        self.doc.h(2, L["appendix"])
        for k in sorted(self.reviews):
            if k in self.responses:
                self.response_section(k, self.responses[k])
            for rid, review in self.reviews[k].items():
                self.review_section(k, rid, review)
        return self.doc


def main() -> None:
    safe_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--lang", choices=sorted(LABELS), help="language of headings and labels")
    parser.add_argument("--format", choices=("md", "html", "both"), default="both")
    parser.add_argument("--out", type=Path, help="output folder (default: REVIEW_DIR/report)")
    args = parser.parse_args()

    if not args.review_dir.is_dir():
        die(f"{args.review_dir}: not a directory")
    plan = as_dict(read_json_optional(args.review_dir / "plan.json"))
    lang = args.lang or (plan.get("language") if plan.get("language") in LABELS else "en")
    report = Report(args.review_dir, lang)
    doc = report.build()
    out_dir = args.out or args.review_dir / "report"
    stem = f"report-round-{report.k}"
    title = LABELS[lang]["title"]
    if args.format in ("md", "both"):
        write_text(out_dir / f"{stem}.md", doc.markdown())
        print(f"wrote {out_dir / (stem + '.md')}")
    if args.format in ("html", "both"):
        write_text(out_dir / f"{stem}.html", doc.html(title, lang))
        print(f"wrote {out_dir / (stem + '.html')}")
    if report.ledger["warnings"]:
        print(f"{len(report.ledger['warnings'])} warning(s); run ledger.py build to see them")


if __name__ == "__main__":
    main()
