# SaralcreditAI (repository: MunimAI)

An agentic voice and text assistant that turns a micro-enterprise's bills and UPI
activity into clean compliance records, matched government schemes, and a
lender-ready credit file.

Built for **Tech4Bharat 2026** (JanAI Mass Entrepreneurship Challenge), problem
statement **3.2** — access to formal credit and schemes — with problem statement
**3.1** (GST compliance paperwork) built in as a feature.

> **Thesis:** compliance is not a cost centre. It is the data engine that makes
> a micro business bankable. Every bill filed for GST also becomes a verified
> line in a credit file.

---

## Status

Working end to end in a browser test console (WhatsApp is paused). Voice and text, in Kannada, Hindi and English.

| Component | State |
|---|---|
| Voice + text assistant (Bhashini ASR/TTS/translation) | Working: reply in the user's language, spoken in Hindi/Kannada |
| Scheme knowledge base | MUDRA, PMEGP, CGTMSE, PM SVANidhi, Stand-Up India, PM Vishwakarma, NSIC, SIDBI, Startup India, SISFS: verbatim official clauses with source URL and fetch date |
| Document Q&A, web fallback, own knowledge | Working, each answer labelled with its source |
| Bills to books, GST draft, affordability | Working; arithmetic in code, never by the model |
| Bank file + loan application (PDF) | Working; Kannada/Hindi glyphs render |
| **Sealed, verifiable bank file** | Working (see below) |
| **Scheme fit: "what would make me eligible?"** | Working (see below) |
| **Books and GST discipline readiness** | Working (see below) |
| Boss/worker models | Qwen2.5-7B on GPU (17 GB cap), Gemma 3 4B on system RAM |
| Tests | 56 passing (`python -m pytest eval`) |
| WhatsApp channel | Paused (Meta account lock); the same pipeline serves the web console |

Nothing here files a GST return or submits a loan application. Those actions are
simulated, by design: see *Boundaries*.

## New: trust and guidance

**1. A bank file that proves itself.** Building the bank file or loan application
seals the books behind it: every ledger entry and every proof document goes into a
SHA-256 hash chain, and a QR code and seal id are stamped on page 1. The verify page
(`/verify/<token>`) recomputes the chain, shows the totals the PDF must match, flags
any change to the owner's live books since sealing, and checks an uploaded PDF
byte for byte against the issued file. Honest limit: the notary is the server; a
deployment would also anchor the seal with an outside timestamp authority. Set
`PUBLIC_BASE_URL` so the QR points at a reachable address.

**2. Scheme fit with reasons.** For each scheme the owner sees every published
condition as met, not met, or not known yet, the official clause it comes from, and
what would change a "no". Rules are deterministic code bound to clauses (no model
writes a verdict) and the Verifier withholds any verdict that cannot cite a current
clause.

**3. One ledger, two jobs.** The same bills that make the GST draft also feed a
0-100 books-and-GST-discipline score. Every point has a reason; every missing point
names the fix and its worth. It needs the owner's consent (switch in the side panel)
and says plainly what it cannot see (whether returns were filed on time).

---

## How it works

```
WhatsApp (voice / photo / text)
        │
   Bhashini ASR            Indic speech → text
        │
   Tiered Cognition Router  ~85% handled by a local 7B; hard cases escalate
        │
   Orchestrator (LangGraph) plans across days, holds state in Postgres
        │
   ┌────┴─────────────────────────────────────────┐
   Ledger   Compliance   Scheme   Credit   Document   Follow-up
   └────┬─────────────────────────────────────────┘
        │
   Verifier gate            blocks anything uncited, unconsented or stale
        │
   WhatsApp reply (+ optional Bhashini TTS voice note)
```

A separate **batch tier** runs overnight on a GPU box for fine-tuning, bulk OCR
and credit re-scoring. It never serves live traffic.

### The verifier gate

Four rules, enforced before anything reaches the user:

1. **Citation required** — a scheme eligibility claim with no retrieved clause is rejected.
2. **Rule version current** — every answer carries the notification date it relied on.
3. **Consent active** — any tool call touching financial data checks for a live, purpose-bound consent.
4. **Prepare, never file** — filing and submission are simulated; the owner acts.

These are enforced in the database as well as in code, so the guarantee survives
a bug in an agent. See `munimai/eval/test_schema_guarantees.py` — each test
asserts the database *refuses* something the product must never do.

---

## Stack

- **Reasoning** — Qwen2.5-7B-Instruct-AWQ (Apache 2.0) served with vLLM, capped at ~15 GB VRAM
- **Indic speech** — [Bhashini](https://bhashini.gov.in) (MeitY), ASR + TTS for Hindi and Kannada
- **Data** — PostgreSQL 16 + pgvector
- **Orchestration** — LangGraph
- **Channel** — WhatsApp Cloud API

Indic language work is deliberately handled by Bhashini rather than the LLM:
measured Kannada generation quality from a 7B model was poor (0.70 script
ratio, one degenerate output), while Bhashini round-tripped both languages at
100% script accuracy.

---
Requires Python 3.11+, and a reachable PostgreSQL 16 with the `vector` extension.

```bash
cp .env.example .env     # then fill in your own credentials
pip install -r requirements.txt
psql "$PG_CONNINFO" -f munimai/schema.sql
python -m pytest munimai/eval/test_schema_guarantees.py -v
```

Credentials are read from the environment only and are never hardcoded. `.env`
is gitignored and must stay that way — it holds live API keys.

---
**##Future Plans**
Smarter agents

Search by meaning: combine keyword search with meaning-based search, so "loan without guarantee" finds the "collateral-free" rule, in any language.
Test before shipping: we use it only if it finds the right clause more often on about 60 test questions, including Hindi and Kannada ones.
Follow-up agent: waits days for a bank's reply, watches for rule changes, and reminds the owner. This is where LangGraph would be useful.
Frameworks: LangChain and LangGraph come in only when a feature needs them. Today's flows are short, so plain code is enough.
Better learning

Harder training exam: the current bill-reading test is nearly solved (0.976), so training could not beat it.
Scheme-question training: teach the model to pick the right scheme and cite the right clause.
Same safety rule: a new model replaces the old one only if it scores strictly higher.
More coverage

Fill knowledge gaps: PMEGP rate tables, CLCSS, Jan Samarth and NIDHI.
State schemes: starting with Karnataka.
Reaching owners

WhatsApp: go live once Meta unlocks the account, so owners need no new app.
Field interviews: talk to owners, accountants and bank branches to fix what is confusing.
Trust and fairness

GST sandbox: keep the simulated filing clearly labelled.
Outside time stamp: add an independent time-stamping service to the sealed bank file, because today our server is the only notary.
Fairness audit: check that results don't favour some groups of owners over others.
Roll-out

Pilot: 100 real businesses after the finale on 27 December.
More states: expand after the pilot.
Before the finale

Demo and rehearsal: videos, QR links and dry runs.
Open items to close: the pricing figure and team names on the deck's placeholder slides.

- **Filing stays with the owner or their professional.** MunimAI prepares; it does not file.
- **Financial data is used only with consent**, purpose-bound and revocable.
- **Every eligibility claim cites its source**, restricted to an allowlist of official government domains.
- **Demo data is synthetic** and flagged as such in the schema (`businesses.is_synthetic`).

---

## Licence

Not yet chosen.
