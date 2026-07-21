"""Deterministic command-risk inference (spec 043 T045).

LLM risk labels in ``commands[].risk`` are unreliable: the same model labels
``i2cset`` (register write) as read in one import and ``setpci`` as write in
another. This module provides the deterministic backstop — the LLM may only
*upgrade* a risk level, never downgrade it. The authoritative floor comes
from verb/pattern matching on the command text itself.

Severity order: read < write < danger.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Rule tables — checked danger first, then write; no match → read
# ---------------------------------------------------------------------------

# Irreversible or potentially hardware-damaging operations.
_DANGER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bflash\b",                          # firmware/BIOS flash
        r"\bfw\s+(update|upgrade)\b",          # retimer-cli fw update
        r"\bfirmware\s+(update|upgrade|flash)\b",
        r"\berase\b",                          # flash/seeprom erase
        r"\bdd\b",                             # raw disk write
        r"\bmkfs\b",                           # filesystem format
        r"\brm\s+-[a-z]*r[a-z]*f\b",           # rm -rf
        r"\brm\s+-[a-z]*f[a-z]*r\b",           # rm -fr
        r"\breboot\b",
        r"\bpower\s*off\b|\bpoweroff\b",
    )
)

# State-modifying but recoverable operations.
_WRITE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bi2cset\b",                         # I2C register write
        r"\bsetpci\b.*=",                      # PCI config space write (reg=value)
        r"\bset\b",                            # generic set verb (kubectl set, ...)
        r"\bsave\b",                           # cfg save / config persist
        r"\bupdate\b",                         # generic update (non-firmware)
        r"\bload-cfg\b",                       # config load
        r"\brestart\b",                        # service restart
        r"\btar\s+-?[a-z]*x",                  # tar extract writes files
        r"\bscp\b.*:",                         # scp to remote target (host:path)
    )
)

_RISK_ORDER = {"read": 0, "write": 1, "danger": 2}


def infer_command_risk(cmd: str) -> str:
    """Infer the minimum risk level of a shell command from its text.

    Returns "read", "write", or "danger". This is a floor, not a ceiling —
    commands with no write/danger signature default to "read".
    """
    text = cmd or ""
    for pattern in _DANGER_PATTERNS:
        if pattern.search(text):
            return "danger"
    for pattern in _WRITE_PATTERNS:
        if pattern.search(text):
            return "write"
    return "read"


def correct_command_risk(llm_risk: str, cmd: str) -> str:
    """Escalate-only correction of an LLM-provided risk label.

    Takes the more dangerous of the LLM's label and the deterministic
    inference: LLM says write + inference says read → write (LLM upgrade
    kept); LLM says read + inference says write → write (deterministic
    floor enforced).
    """
    base = llm_risk if llm_risk in _RISK_ORDER else "read"
    inferred = infer_command_risk(cmd)
    if _RISK_ORDER[inferred] > _RISK_ORDER[base]:
        return inferred
    return base
