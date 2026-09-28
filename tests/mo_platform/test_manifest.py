"""The capability manifest must not claim what the code does not contain."""

import importlib
from pathlib import Path

import pytest

from app.mo import manifest as mf

ROOT = Path(__file__).resolve().parents[2]


def test_statuses_valid_and_summary_totals():
    assert all(c["status"] in mf.STATUSES for c in mf.CAPABILITIES)
    assert sum(mf.summary().values()) == len(mf.CAPABILITIES)


def test_feature_names_unique():
    names = [(c["area"], c["feature"]) for c in mf.CAPABILITIES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("cap", [c for c in mf.CAPABILITIES if c["module"]], ids=lambda c: c["feature"][:50])
def test_claimed_module_imports(cap):
    importlib.import_module(cap["module"])


@pytest.mark.parametrize("cap", [c for c in mf.CAPABILITIES if c["test"]], ids=lambda c: c["feature"][:50])
def test_claimed_test_path_exists(cap):
    assert (ROOT / cap["test"]).exists(), cap["test"]


def test_implemented_claims_name_code_and_a_test():
    for c in mf.CAPABILITIES:
        if c["status"] == "implemented":
            assert c["module"] and c["test"], c["feature"]


def test_planned_and_future_claim_no_code():
    for c in mf.CAPABILITIES:
        if c["status"] in ("planned", "future"):
            assert c["module"] is None, c["feature"]
            assert c["note"], f"{c['feature']} needs a note explaining the gap"


def test_partial_and_credential_required_state_their_limit():
    for c in mf.CAPABILITIES:
        if c["status"] in ("partial", "credential_required"):
            assert c["note"], c["feature"]


def test_live_overlay_and_manifest_shape():
    live = mf.live_overlay()
    assert live["wake_word_mode"] == "transcript-keyword"
    assert isinstance(live["model_provider_configured"], bool)
    m = mf.manifest()
    assert set(m) == {"summary", "capabilities", "known_blockers", "live"}
    assert m["known_blockers"]
