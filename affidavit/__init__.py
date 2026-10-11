"""Affidavit of Documents assembly pipeline (proof of concept).

A deterministic, local-only document pipeline for assembling an Affidavit of
Documents under Ontario Rules of Civil Procedure, Rule 30.03.

Design principle: the machine converts, normalises, files and reconciles.
It NEVER decides relevance, privilege, or schedule placement. Those are
sworn, human decisions and are recorded as such.
"""

__version__ = "0.1.0"
