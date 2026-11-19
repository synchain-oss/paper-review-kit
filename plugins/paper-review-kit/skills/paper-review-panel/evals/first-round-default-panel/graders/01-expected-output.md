---
type: llm
focus: trace
weight: 1
---

The result matches this description: the run asks once which model the reviewers should run on (or states which one it uses), writes plan.json with a stopping rule before any review, launches three reviewers (subfield expert, methods and statistics, general reader) in separate fresh contexts with the model set explicitly, each given only its room (the PDF and its text layer), and no quota of weaknesses, saves the reviews unedited as JSON, runs check_quotes.py, ledger.py build and render_report.py, and answers the user with a short change list first, then how the reviewers were run and the report paths, without presenting scores as an acceptance prediction.
