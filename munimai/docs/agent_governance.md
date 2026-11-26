# What stops the assistant from doing something wrong

SaralcreditAI uses language models to read and to write, and plain code to decide. This page lists every control, where it lives, and what it cannot do. Each one is enforced in code or in the database, not in a prompt.

## 1. Models never touch numbers, rules or filings

| Thing | Who does it | Where |
|---|---|---|
| GST amounts | Integer arithmetic in paise | `backend/agents/compliance.py` |
| Books errors (duplicates, ITC mismatch, future dates) | Eight fixed rules | `backend/agents/auditor.py` |
| Scheme rules and limits | Verbatim official text, cited by clause id | `backend/agents/scheme.py`, `backend/kb/` |
| Which scheme a question is about | Keyword router, no model | `backend/router.py` |
| Progress on the loan-readiness plan | Fixed checks over saved data | `backend/agents/journey.py` |
| What the assistant remembers | Patterns and counters, no model | `backend/agents/memory.py` |
| Formulas in Insights | A model may propose; a parser, unit check and backtest decide | `backend/analytics/` |

The model's job is to phrase an answer from clauses it is handed, and to read messy text.

## 2. Every claim passes the Verifier before the owner sees it

`backend/agents/verifier.py` checks, in code:

1. **Citation** — a claim tagged as needing a source must cite at least one real clause.
2. **Rule version** — each cited clause must be current (not superseded).
3. **Consent** — a claim that used financial data must have active consent.
4. **No filing** — the claim text must not assert that something was filed/submitted without a receipt.
5. **Number grounding** — an analysis may quote only numbers the code computed.
6. **Faithfulness** (`backend/agents/faithfulness.py`) — a scheme answer may say only what the clauses it cites say. Fixed rules (no model) check every substantive sentence against the cited clause text for: numbers not in any clause, enterprise categories the clauses never mention, unsupported negations ("does not provide X"), scheme names belonging to uncited schemes, and low word overlap. Sentences that hedge about the clauses ("the clauses do not state this") are skipped. On the 60-question real-answer audit (40 retrieval-bench + 20 hand-written), the checker flags 13 of 58 cited answers (22%); manual review confirms about 6 are true positives (the model fabricated a number, a time requirement, or a scheme detail), giving an estimated false-positive rate of ~12% and a true-positive detection rate that catches the clearest overreach.

A clause id the model invents is dropped before the check, so it cannot become a citation.

If the Verifier rejects an answer, the reasons go back to the model **once** for a revised answer (`backend/gateway.py`, visible in the trace as a second verifier event). A second rejection behaves differently depending on the kind of failure: if the answer is **unfaithful** (the citations are real but the summary overshoots them), the gateway returns the cited clause text verbatim — the official words, not the model's summary. Otherwise it returns "I can't confirm that yet". There is no third try.

## 3. Only official text can be cited

`backend/kb/loader.py` refuses any clause whose source domain is not in `CITATION_ALLOWLIST` (`backend/config.py`), so a non-official page is never stored. Every clause carries its source URL and fetch time. When a page is re-fetched, older clauses are marked superseded and kept, never deleted, so old citations still resolve.

Before a policy is loaded, its stated validity period is read. Expired or conflicting documents are left out and listed with the reason in `backend/kb/SOURCES.md`.

## 4. Nothing is filed without a person

- The coordinator and the journey agent stop at "ready for review". They have no code path to approve or file.
- Approval needs a one-time six-digit code, valid ten minutes, stored only as a hash.
- The owner approves an immutable snapshot (a database trigger refuses updates). A filing row cannot exist unless an approval row matches the snapshot's hash (database constraint). If the books change after approval, the hash no longer matches and the filing is refused.
- Filing goes to a sandbox adapter and every receipt is labelled SIMULATED. Real filing is roadmap.

## 5. Limits on autonomous work

- Each task has a step budget and a deadline. A task that runs over is escalated to a person.
- A per-business kill switch is checked before every step. When it is off, the month-close task and the loan-readiness plan both freeze.
- State is saved after every step, so a restart resumes instead of repeating.
- Every step is written to the trace (which agent, which tool, which model).

## 6. The owner controls what is remembered

`GET /sim/memory` shows exactly what is stored (sector, state, headcount, a loan amount you named, schemes you asked about, your last few questions). `DELETE /sim/memory` erases it. Remembered facts reach a model only as "stated by the owner, not verified" and are never a source for a scheme rule. Ledger entries and documents are separate and are not touched by "forget".

## 7. Hardware limits are enforced, not hoped for

The Qwen model owns the GPU (about 9 GB used of a 17 GB budget). Helper models and the embedding model run on system memory only (`CUDA_VISIBLE_DEVICES` is empty for them) under systemd memory caps. The Trace tab shows live use against both budgets (`GET /sim/status`).

## 8. Known limits

- A 7B model can still misread a clause. The faithfulness checker (check 6, below) narrows the gap but cannot prove an answer is a correct paraphrase. The Scheme prompt forbids claiming a scheme "does not offer" something merely because the retrieved clauses do not mention it, but this is a prompt rule, not a proof.
- Retrieval is imperfect: on the 135-question benchmark (`eval/benchmark/retrieval_bench.py`, 1,263 clauses) the gold clause is in the top 12 for about 43% of questions, against 27% with keyword search alone. The figure fell from 48% when the library had 888 clauses: more sources means more near-matches. Roman-script Hindi ("Hinglish") is no better than keyword search.
- One citation host is not a .gov.in site (`investkarnataka.co.in`, hosting the Karnataka Government's own incentive guidelines). It is a named exception in `backend/config.py`.
- Many state policies are not loaded because no current, reachable, official text was found (see `backend/kb/SOURCES.md`).
- Findings and plan text from the server are in English only.
