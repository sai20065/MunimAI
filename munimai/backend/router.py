"""
Tiered Cognition Router — a small classifier that decides what a message
actually wants, so the pipeline does not force every message through the
scheme-eligibility path.

Deliberately NOT an LLM call for intent:
- Zero-latency, deterministic, free.
- Qwen-7B scored 0.90 on JSON tool calls, not 1.00. A wrong intent means a
  wrong agent. For a handful of intent classes, a keyword matcher is both
  cheaper and more accurate than a 7B model.
- The model still does the hard work (answering) once we know where to send.

Intents returned:
  'eligibility' - "can I get a loan", "am I eligible", "mudra kishore?"
  'documents'   - "what documents", "what to send", "kya dastavez"
  'journey'     - "what should I do next", "help me get a loan", "my progress"
  'capability'  - "can you speak kannada", "what can you do", "how do you work"
  'greeting'    - "hi", "hello", "namaste"
  'thanks'      - "thanks", "dhanyavad"
  'unknown'     - fallback (routes to Scheme as before)
"""

from __future__ import annotations

import re

Intent = str

# Short canned replies for the intents that don't need the LLM at all.
# Grounded in what SaralcreditAI really does, not model imagination.
CANNED = {
    "greeting": (
        "Namaste! I'm SaralcreditAI, your credit and compliance helper.\n\n"
        "Send me a bill photo, ask about a MUDRA loan, or record a voice "
        "note in Hindi or Kannada. I'll do the rest."
    ),
    "thanks": "Anytime. Send another bill or ask another question whenever you need.",
    "capability": (
        "Here is what I can do:\n\n"
        "- Answer loan, subsidy and startup-funding questions from official scheme pages "
        "(MUDRA, PMEGP, CGTMSE, SVANidhi, Stand-Up India, Startup India and more), always naming the clause.\n"
        "- Read your bills, PDFs and certificates, add bills to your books, and answer questions about your documents.\n"
        "- Search the web when the official pages do not cover a question, and say clearly where the answer came from.\n"
        "- Prepare a GST summary and a bank file (PDF), and draft a loan application and covering letter.\n"
        "- Save any answer as a PDF or an image.\n\n"
        "I understand and reply in Kannada, Hindi and English, by voice or text. I never file a return or "
        "submit a loan for you: I prepare, you review and decide."
    ),
    "documents": (
        "For SaralcreditAI to work, send me what the business already has:\n\n"
        "- A clear photo of each supplier and customer bill (I'll extract the amount and GST).\n"
        "- Your Udyam number and GSTIN (if you have them — I can work without).\n"
        "- A WhatsApp voice note describing anything that isn't on a bill.\n\n"
        "For a MUDRA loan application itself, the bank decides what it needs. "
        "MUDRA loans up to Rs 20 lakh are collateral-free and PAN is not compulsory "
        "(MUDRA FAQ). I'll ask about the specific bank's checklist once you tell me which one."
    ),
}


def classify(text: str) -> Intent:
    t = (text or "").strip().lower()
    if not t:
        return "unknown"

    # deliverables first: they contain words ("loan", "documents") that would
    # otherwise route to eligibility or the canned documents reply
    if _any(t, [r"\bbank[- ]?(ready )?(file|dossier|pack)\b", r"\bloan file\b", r"\bdossier\b",
                r"\bprepare (my|the) (file|documents|pack)\b", r"\bpdf (of|with) my (documents|books|proofs)\b"]):
        return "dossier"
    if _any(t, [r"\b(draft|write|prepare|make|create)\b.*\b(loan )?application\b", r"\bapplication (letter|form|draft)\b",
                r"\bletter to (the )?(bank|sbi|branch)\b", r"\bdetailed draft\b"]):
        return "application"
    if _any(t, [r"\b(as|in|into|to) (a |an )?(pdf|image|png|jpeg|picture)\b",
                r"\b(save|send|give|download|make|export)\b.*\b(pdf|image|png|picture)\b"]):
        return "export"

    # progress on the owner's loan-readiness plan (a plan, not a scheme question)
    if _any(t, [r"\bwhat (should|do|shall) i do next\b", r"\bnext steps?\b", r"\b(my|the) (progress|plan|journey|checklist|to-?do)\b",
                r"\bhelp me (get|apply|prepare|become)\b.*\b(loan|credit|finance|funding|bank)\b",
                r"\bloan journey\b", r"\bwhere (am i|do i stand)\b", r"\bwhat('s| is) (left|pending|missing)\b"]):
        return "journey"

    # personalised checks, before the generic scheme question
    if _any(t, [r"\bwhat (would|will|can|should) (i|make me|help me)\b.*\b(eligible|qualify)\b",
                r"\bwhy (am i|can't i|cant i|am i not)\b.*\b(eligible|qualify)\b",
                r"\bhow (can|do) i (become|get|be) eligible\b", r"\bscheme fit\b", r"\bcheck my (scheme|eligibility)\b",
                r"\bwhich schemes?\b.*\b(am i|can i|do i)\b.*\b(eligible|qualify|get)\b",
                r"\bmake me eligible\b", r"\bbecome eligible\b",
                r"\bwhat (do|should|must|will) i (need to |have to |want to )?do to (be |become |get )?(eligible|qualify)\b",
                r"\bhow (can|do|could|should) i (qualify|become eligible|be eligible|get eligible)\b"]):
        return "fit"
    if _any(t, [r"\b(credit|loan) readiness\b", r"\bhow ready\b", r"\bready for (a |an )?(bank |business )?(loan|lender|credit)\b", r"\bam i ready (for|to)\b.*\b(loan|lender|bank|credit)\b",
                r"\b(improve|increase|boost)\b.*\b(my )?(chances|credit|score|readiness)\b",
                r"\bgst discipline\b", r"\bhow (good|strong|ready) (are|is) my (books|credit)\b",
                r"\bbooks (score|discipline)\b", r"\bcredit score\b"]):
        return "readiness"

    # eligibility — strong signals win first
    if _any(t, [
        r"\bmudra\b", r"\bkishore\b", r"\bshishu\b", r"\btarun\b",
        r"\bloan\b", r"\bgive me money\b", r"\beligib", r"\bqualify\b",
        r"\bam i (eligible|able)\b", r"\bpaisa\b", r"\brupees\b",
        r"\bfinance\b", r"\bbusiness loan\b",
        r"\bpmegp\b", r"\bcgtmse\b", r"\bsvanidhi\b", r"\bstand[- ]?up\b", r"\bstartup\b", r"\bsubsid",
        r"\bseed fund\b", r"\bfund of funds\b", r"\bnidhi\b", r"\bvishwakarma\b", r"\bnsic\b",
        r"\bgrant\b", r"\bsidbi\b", r"\bjan samarth\b", r"\bcollateral\b", r"\bguarantee\b",
        r"\b(which|what) (government |govt )?(scheme|schemes|subsidy|loan)\b", r"\bseed (funding|capital)\b",
        r"\b(government|govt|central|state) (loan |msme )?schemes?\b", r"\bmsme schemes?\b",
        r"\b(karnataka|telangana|andhra|tamil ?nadu|gujarat|uttar pradesh)\b.*\b(polic(y|ies)|incentive|subsid|scheme|msme|startup)",
        r"\bclcss\b", r"\bsclcss\b", r"\bprayas\b", r"\budyam\b", r"\bcapital subsid", r"\binterest subsid",
    ]):
        return "eligibility"

    if _any(t, [
        r"\bwhat (do|should|all) (i|we) (give|send|share|provide)\b",
        r"\bwhat document", r"\bdocuments?\b", r"\bdastavez", r"\bkagaz\b",
        r"\bwhat to send\b", r"\bkyc\b", r"\bpaperwork\b",
        r"\bwhat (will|do) (you|u) need\b",
    ]):
        return "documents"

    if _any(t, [
        r"\bcan (you|u) speak\b", r"\bdo you (speak|know|support)\b",
        r"\bwhat can you do\b", r"\bhow do you work\b",
        r"\bwho are you\b", r"\bwhat are you\b", r"\bare you an? ai\b",
        r"\blanguage(s)?\b", r"\bkannada\b", r"\bhindi\b", r"\btelugu\b",
        r"\btamil\b",
    ]):
        return "capability"

    if _any(t, [
        r"^\s*(hi|hello|hey|namaste|namaskara|namaskar|vanakkam|salaam)[\s!,.]*$",
        r"^\s*good (morning|afternoon|evening|night)\b",
    ]):
        return "greeting"

    if _any(t, [
        r"^\s*(thanks|thank you|thnx|dhanyavad|shukriya)[\s!,.]*$",
    ]):
        return "thanks"

    return "unknown"


def _any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)
