# Prompt library

Versioned copies of the three system prompts this build uses in production,
matching the PR-CS-01/02/03 entries in Stage 3's prompt register addendum
(`deliverables/Stage_3_Prompt_Library_DRAFT.docx`).

**Source of truth is the code**, not these files — `src/classify.py`'s
`_SYSTEM_PROMPT` and `src/generate.py`'s `_ANSWER_SYSTEM_PROMPT` /
`_SUMMARY_SYSTEM_PROMPT` are what actually runs. These are extracted, dated
copies kept here so the prompt library exists as reviewable files per the
Submission Guide's required repository structure, and so a prompt change
shows up as a diff against a known-good version rather than only inside a
larger code change.

| File | Used by | Current version |
|---|---|---|
| `classify_v2.txt` | `src/classify.py` — intent, urgency, confidence (A3) | v2, 2026-09-10 — added disambiguation rules for 4 confusable intent-category pairs found during evaluation (Stage 5 revision log) |
| `generate_answer_v1.txt` | `src/generate.py` — customer-facing answer when routing decides `auto_respond` (A6) | v1, 2026-09-10 |
| `generate_summary_v1.txt` | `src/generate.py` — agent-facing handoff summary when routing decides `escalate` | v1, 2026-09-10 |

If you change a prompt in the code, update the matching file here in the
same commit — this folder is documentation, and stale documentation is
worse than none.
