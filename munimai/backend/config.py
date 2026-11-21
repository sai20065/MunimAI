"""
Central configuration for SaralcreditAI, loaded from environment / .env.

Nothing here has a secret default. If a credential is missing, the component
that needs it raises a clear error at startup rather than failing obscurely
halfway through a user conversation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root is the folder containing the `munimai` package.
ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

# Domains a scheme citation is allowed to come from. The verifier rejects any
# claim citing a source outside this list, so a scraped blog can never become
# the basis of an eligibility answer.
CITATION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "mudra.org.in",
        "www.mudra.org.in",
        "gst.gov.in",
        "www.gst.gov.in",
        "cbic-gst.gov.in",
        "msme.gov.in",
        "www.msme.gov.in",
        "udyamregistration.gov.in",
        "jansamarth.in",
        "www.jansamarth.in",
        "cgtmse.in",
        "www.cgtmse.in",
        "india.gov.in",
        "www.india.gov.in",
        "rbi.org.in",
        "www.rbi.org.in",
        # added for the multi-scheme KB; each verified live and content-bearing
        "pmegp.msme.gov.in",            # Ministry of MSME PMEGP portal
        "pmsvanidhi.mohua.gov.in",      # Ministry of Housing and Urban Affairs
        "pmvishwakarma.gov.in",         # Government of India scheme portal
        "www.standupmitra.in",          # Stand-Up India, SIDBI for Dept of Financial Services
        "www.nsic.co.in",               # National Small Industries Corp (Govt PSU, MSME)
        "nsic.co.in",
        "www.sidbi.in",                 # Small Industries Development Bank of India
        "sidbi.in",
        "www.startupindia.gov.in",      # DPIIT, Startup India
        "startupindia.gov.in",
    }
)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required setting {name} is not set. Add it to {ROOT / '.env'} "
            "(see .env.example)."
        )
    return value


@dataclass(frozen=True)
class DBSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password} connect_timeout=15"
        )

    @classmethod
    def from_env(cls) -> "DBSettings":
        return cls(
            host=_require("PGHOST"),
            port=int(os.environ.get("PGPORT", "5433")),
            dbname=os.environ.get("PGDATABASE", "munimai"),
            user=_require("PGUSER"),
            password=_require("PGPASSWORD"),
        )


@dataclass(frozen=True)
class LLMSettings:
    """
    The reasoning model. Served by vLLM on the supercomputer, reached over
    Tailscale. Deliberately an OpenAI-compatible base_url so the model can be
    swapped (or pointed at a local process) without touching agent code.
    """

    base_url: str
    model_served_name: str   # what the OpenAI API expects in the "model" field
    model_path: str          # the on-disk path, for reference
    timeout_s: int = 120
    role: str = "boss"       # "boss" (Qwen/GPU) or "worker" (Gemma/CPU) — trace tag only

    @classmethod
    def from_env(cls) -> "LLMSettings":
        return cls(
            base_url=os.environ.get(
                "LLM_BASE_URL", "http://100.86.188.31:8077/v1"
            ),
            model_served_name=os.environ.get("LLM_MODEL", "qwen2.5-7b"),
            model_path=os.environ.get(
                "LLM_MODEL_PATH",
                "/home/admin/munimai/models/Qwen2.5-7B-Instruct-AWQ",
            ),
            timeout_s=int(os.environ.get("LLM_TIMEOUT_S", "120")),
            role="boss",
        )

    @classmethod
    def from_env_worker(cls) -> "LLMSettings":
        """
        The worker model: a small Gemma served by llama.cpp on CPU/RAM only
        (no GPU VRAM, capped at 28 GB by a systemd MemoryMax on the lab box).
        Used for narrow, parallelisable extraction jobs (bill-field extraction,
        synthetic scenario generation) so the GPU stays free for the boss.
        """
        return cls(
            base_url=os.environ.get(
                "WORKER_LLM_BASE_URL", "http://100.86.188.31:8090/v1"
            ),
            model_served_name=os.environ.get("WORKER_LLM_MODEL", "gemma-3-4b-it"),
            model_path=os.environ.get(
                "WORKER_LLM_MODEL_PATH",
                "/home/admin/models/gemma3-4b-worker/gemma-3-4b-it-Q4_K_M.gguf",
            ),
            timeout_s=int(os.environ.get("WORKER_LLM_TIMEOUT_S", "60")),
            role="worker",
        )

    @classmethod
    def from_env_math(cls) -> "LLMSettings":
        """The Math agent's second Gemma (Gemma 3n E4B) on system RAM only, capped at 6 GB by systemd."""
        return cls(
            base_url=os.environ.get("MATH_LLM_BASE_URL", "http://100.86.188.31:8092/v1"),
            model_served_name=os.environ.get("MATH_LLM_MODEL", "gemma-3n-math"),
            model_path=os.environ.get("MATH_LLM_MODEL_PATH",
                                      "/home/admin/models/gemma3n-math/gemma-3n-E4B-it-Q4_K_M.gguf"),
            timeout_s=int(os.environ.get("MATH_LLM_TIMEOUT_S", "240")),
            role="math",
        )


@dataclass(frozen=True)
class WhatsAppSettings:
    token: str
    phone_number_id: str
    verify_token: str

    @classmethod
    def from_env(cls) -> "WhatsAppSettings":
        return cls(
            token=_require("WHATSAPP_TOKEN"),
            phone_number_id=_require("WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN", "munimai-verify"),
        )


# Where trace files are written. Kept on the laptop so a lab-box reboot never
# loses the record of a demo run.
TRACE_DIR = ROOT / "traces"

# REPLAY mode plays a recorded trace instead of calling the model, so a
# presentation still works if the supercomputer is unreachable.
REPLAY_MODE: bool = os.environ.get("MUNIMAI_REPLAY", "").lower() in {"1", "true", "yes"}
