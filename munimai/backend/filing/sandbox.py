"""
Filing adapters.

SandboxFiler is the only adapter that runs in this build. It does NOT contact the GST portal. It
accepts an approved payload and returns a receipt that is always labelled SIMULATED, so a demo
can show the full approve-then-file flow without anything real being filed.

GspFiler is a stub. Real filing needs a licensed GST Suvidha Provider, the taxpayer's written
authorisation, and an OTP/EVC or DSC from the owner each time. It stays disabled until all of
that exists (see docs/REAL_FILING_CHECKLIST.md).
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone


class FilingNotEnabled(RuntimeError):
    pass


class SandboxFiler:
    name = "sandbox"
    simulated = True

    def file(self, payload: dict, snapshot_hash: str) -> dict:
        ref = "SIM-" + hashlib.sha256(snapshot_hash.encode()).hexdigest()[:12].upper()
        return {
            "reference": ref,
            "simulated": True,
            "label": "SIMULATED: nothing was sent to the GST portal",
            "period": payload.get("period"),
            "net_payable_paise": payload.get("figures", {}).get("net_payable_paise"),
            "filed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


class GspFiler:
    name = "gsp"
    simulated = False

    def file(self, payload: dict, snapshot_hash: str) -> dict:
        if os.environ.get("REAL_FILING_ENABLED") != "1":
            raise FilingNotEnabled("Real filing is disabled. It needs a licensed GSP, owner authorisation and an OTP.")
        raise FilingNotEnabled("GSP integration is not built in this version.")
