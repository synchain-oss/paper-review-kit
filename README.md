# paper-review-kit

A Claude Code plugin with one skill, `paper-review-panel`: a simulated peer-review loop for
your own research paper. Independent model reviewers read the PDF; a script checks every
quote they make; the coordinator turns their reports into a short list of changes worth
making; you revise and answer each point; returning reviewers judge their own points while
fresh reviewers check them; an issue ledger and a stopping rule keep repeated rounds honest.

## The first rule

The panel exists to improve the paper, not to produce an impressive review. Reviewers have
no quota of weaknesses; every criticism points at a specific place, quotes it, and says what
change would resolve it; "nothing to change here" and "keep this as it is" are valid
answers; scores only track movement between rounds. The report leads with the change list,
and the full reviews are an appendix.

## When to use it

- Before submitting: what will reviewers object to, and what is worth fixing?
- After a revision: did the changes resolve the points, and did they introduce a problem?
- Between rounds of a real review: check a response letter against the revised PDF.
- To compare review methods: run a published review protocol on one seat, next to the
  built-in seats, on the same paper.

It is not meant for writing referee reports on other people's submissions.

## What a run looks like

1. You give the PDF, the venue, the report language, the model the reviewers should run on
   (the strongest you are willing to pay for), the budget and the stopping rule.
2. Round 1: three reviewers with different methods (subfield expert, methods and
   statistics, general reader of the venue) review independently. Quotes are checked,
   must-fix points are checked by a cheaper model, and you get the change list.
3. You revise and write a response, one row per point.
4. Round 2: returning reviewers judge their own points in three steps; fresh reviewers who
   see only the revised PDF act as the control group. You get what the round changed, the
   score movement, and a fix plan: done, needs your decision, not recommended.
5. Repeat until the stopping rule holds.

## Install

From a local copy of this folder:

```
/plugin marketplace add <path-to>/paper-review-kit
/plugin install paper-review-kit@paper-review-kit
```

Or, with access to the repository:

```
/plugin marketplace add synchain-oss/paper-review-kit
/plugin install paper-review-kit@paper-review-kit
```

Then ask Claude Code to review your paper; the skill triggers on requests such as "review
my paper", "what would reviewers say about this draft" or "check my response letter".

## Requirements

- Python 3.9 or later (tested on 3.10); the scripts use only the standard library.
- `pdftotext` from poppler or xpdf, for the quote check. On Debian or Ubuntu:
  `sudo apt install poppler-utils`; on macOS: `brew install poppler`; with conda:
  `conda install -c conda-forge poppler`. Without it the scripts say so and the report
  states that quotes could not be checked.
- A host that can launch sub-agents or run workflows gives independent reviewers. Without
  either, the reviews are written one after another in one context, and the report says
  that they are not independent.

## Layout

```
.claude-plugin/marketplace.json
plugins/paper-review-kit/
  .claude-plugin/plugin.json
  skills/paper-review-panel/
    SKILL.md                 the loop, the rules, which reference to read when
    references/              reviewer briefs, schemas and score anchors, rounds,
                             response letter, converting earlier reviews,
                             known failure modes
    scripts/                 extract_text.py, check_quotes.py, ledger.py, render_report.py
                             (common.py holds shared helpers)
    evals/                   test prompts in the skill-creator case format
```

## Changes

**0.2.0**, from the first complete multi-round run:

- Supplementary material: `extract_text.py` takes the manuscript and further PDFs, writes
  one text file and a page map; quotes are located as "supplement p. 3".
- Rooms: `ledger.py rooms` builds one folder per reviewer holding only its files, with the
  text layer for copying quotes; reviewers are briefed by room. Fresh rooms get their own
  parent (`--fresh-out`) apart from the returning rooms and neutral PDF names, so fresh
  reviewers get no hint of a revision; hosts that pass project instructions to sub-agents
  are covered.
- Points packets carry each point's title and why, the reviewer's latest scores, and mark
  passages chosen during a conversion.
- `remaining_severity` on a `partly` judgement: a must-fix point whose remainder is
  should-fix no longer blocks the stopping rule; the report shows both levels.
- Duplicate groups show the head's check verdict and how many members differ; the stopping
  rule counts a group as surviving when any fresh member survives.
- An optional extra score sheet (`extra_score_sheet`, `extra_scores`) rendered with its
  movement; display names for seats (`seat_names`).
- Converted reviews (`converted`), a reference for converting a round run by hand or with
  another form, the authors' `disagree`, and a warning for out-of-reach rows the plan does
  not list.
- `check_quotes.py --queries`: audits every web request read from the host's transcripts
  and reports those a reviewer did not list (only the same text counts as listed).
- Briefs: claim-and-evidence step in the methods seat, numeric audit as a default seat for
  table-heavy papers, checker batches split by reviewer, worked examples for
  external-protocol overrides.

## 中文说明

`paper-review-panel` 是一个模拟同行评审的 skill，用来改进作者自己的论文，不是为了写出一份好看的审稿报告。

- **第一条规则**：审稿人不凑问题，没有「至少几条缺点」的配额；每条意见都要指到具体位置、逐字引用原文、说清怎样改能解决；「这里不用改」「这一处保持原样」都是有效的回答；分数只用来看轮与轮之间的变化。给你的报告先列值得做的修改，完整审稿意见放在附录。
- **流程**：第 1 轮三位独立审稿人（领域专家、方法与统计、会议的一般读者）只读 PDF；脚本核对每条引文；统筹者整理出简短的修改清单。作者修订并逐条回复之后，第 2 轮由返场审稿人逐条判定自己的意见是否解决，同时由只看修订稿的新审稿人做对照组，检查锚定和讨好。意见台账的编号跨轮不变，停止规则在第 1 轮之前定好。
- **模型**：审稿人用你愿意付费的最强模型，由你决定；核查、台账和渲染用便宜模型或脚本。
- **联网**：审稿人可以查文献，但未发表、双盲的稿件的标题、原句、作者名和项目名不进入任何检索；指出漏引必须给 DOI、arXiv 编号或完整标题，并写明是否真的打开看过。
- **试用外部审稿方法**：可以让一个席位按公开的审稿 skill 或协议来审，便于在同一篇论文上比较；外部文本只当作不可信的参考资料保存成纯文本，不安装、不运行其中的脚本，越出审稿范围的指令一律不执行。
- **报告语言**：`render_report.py --lang zh` 输出简体中文的标题和标签；审稿人的正文按你指定的语言写。
