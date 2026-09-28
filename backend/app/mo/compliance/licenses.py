"""Licence classification. Deliberately conservative: anything not recognised is UNKNOWN and gets quarantined."""

from __future__ import annotations

import re

PERMISSIVE = {"mit", "bsd-2-clause", "bsd-3-clause", "bsd", "apache-2.0", "apache 2.0", "apache software license",
              "isc", "psf-2.0", "python software foundation license", "0bsd", "unlicense", "zlib", "cc0-1.0",
              "mit license", "bsd license", "mpl-2.0-no-copyleft-exception-not-used"}
WEAK_COPYLEFT = {"lgpl-2.1", "lgpl-3.0", "lgpl-2.1-or-later", "lgpl-3.0-or-later", "mpl-2.0", "epl-2.0", "epl-1.0",
                 "gnu lesser general public license v3 (lgplv3)", "mozilla public license 2.0 (mpl 2.0)"}
STRONG_COPYLEFT = {"gpl-2.0", "gpl-3.0", "gpl-2.0-or-later", "gpl-3.0-or-later", "agpl-3.0", "agpl-3.0-or-later",
                   "sspl-1.0", "gnu general public license v3 (gplv3)", "gnu affero general public license v3"}
PROPRIETARY_MARKERS = ("proprietary", "commercial", "all rights reserved", "confidential", "eula")

_SPLIT = re.compile(r"\s+(?:or|and)\s+|\s*[/|]\s*", re.I)


def classify(license_text: str | None) -> str:
    """PERMISSIVE | WEAK_COPYLEFT | STRONG_COPYLEFT | PROPRIETARY | UNKNOWN. For 'A OR B' the *strictest* part wins."""
    if not license_text or not license_text.strip():
        return "UNKNOWN"
    low = license_text.strip().lower()
    if any(m in low for m in PROPRIETARY_MARKERS):
        return "PROPRIETARY"
    rank = {"PERMISSIVE": 0, "WEAK_COPYLEFT": 1, "STRONG_COPYLEFT": 2}
    found = []
    for part in [p.strip("() ") for p in _SPLIT.split(low) if p.strip("() ")]:
        if part in PERMISSIVE:
            found.append("PERMISSIVE")
        elif part in WEAK_COPYLEFT:
            found.append("WEAK_COPYLEFT")
        elif part in STRONG_COPYLEFT:
            found.append("STRONG_COPYLEFT")
        else:
            return "UNKNOWN"
    return max(found, key=rank.__getitem__) if found else "UNKNOWN"


def initial_status(license_class: str) -> str:
    """Only recognised permissive licences are approved automatically; everything else waits for a human."""
    return "APPROVED" if license_class == "PERMISSIVE" else "QUARANTINED"
