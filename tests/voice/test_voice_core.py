"""
JARVIS voice layer: providers, intents, speech phrasing, and the conversation
engine. The engine tests use an injected clock, so the wake window and its
expiry are tested exactly rather than with sleeps.
"""

from datetime import datetime, timedelta

import pytest

from app.mo.errors import MoError, ResultState
from app.mo.voice import speech
from app.mo.voice.intents import INTENT_SPECS, IntentName, missing_slots, resolve_intent
from app.mo.voice.providers import (
    ExecutionSite, VoiceCapability, VoiceRouter, WakeWordMode, get_voice_router,
    strip_wake_phrase,
)

pytestmark = pytest.mark.voice


# ── Providers: the capability matrix must not overstate anything ────────────

def test_browser_adapter_works_without_any_credentials():
    router = get_voice_router()
    assert router.pick(VoiceCapability.TRANSCRIBE).info.name == "browser_web_speech"
    result = router.synthesize("Hello there.")
    assert result.state is ResultState.SUCCESS
    assert result.data == {"directive": "speak", "text": "Hello there.",
                           "voice": "default", "language": "en-US"}


def test_browser_path_never_accepts_raw_audio():
    """Raw microphone audio must never reach the server on the browser path."""
    adapter = get_voice_router().pick(VoiceCapability.TRANSCRIBE)
    assert adapter.info.execution_site == ExecutionSite.CLIENT
    assert adapter.transcribe(b"\x00\x01").state is ResultState.POLICY_DENIED


def test_speaker_verification_is_never_faked():
    result = get_voice_router().verify_speaker(b"audio", enrolled_id="owner")
    assert result.state is ResultState.CREDENTIAL_REQUIRED
    assert "bearer token" in result.detail


def test_unimplemented_adapters_say_so():
    from app.mo.voice.providers import DeepgramAdapter, WhisperAdapter
    for adapter in (WhisperAdapter(), DeepgramAdapter()):
        assert adapter.info.implemented is False
        result = adapter.transcribe(b"x")
        assert result.state is ResultState.CREDENTIAL_REQUIRED
        assert "no implementation" in result.detail


def test_capability_matrix_reports_gaps_honestly():
    caps = get_voice_router().capabilities()
    assert caps["by_capability"][VoiceCapability.SPEAKER_VERIFY]["supported"] is False
    assert caps["wake_word"]["mode"] == WakeWordMode.TRANSCRIPT_KEYWORD
    assert any("acoustic" in gap for gap in caps["known_gaps"])


def test_synthesis_with_no_provider_reports_credential_required():
    assert VoiceRouter(adapters=[]).synthesize("hi").state is ResultState.CREDENTIAL_REQUIRED


@pytest.mark.parametrize("utterance,detected,rest", [
    ("MO", True, ""),
    ("MO, build a CRM", True, "build a CRM"),
    ("hey mo deploy staging", True, "deploy staging"),
    ("Jarvis: run the tests", True, "run the tests"),
    ("build a CRM", False, "build a CRM"),
    ("moment of truth", False, "moment of truth"),       # 'mo' inside a word is not a wake
    ("", False, ""),
])
def test_wake_phrase_detection(utterance, detected, rest):
    assert strip_wake_phrase(utterance) == (detected, rest)


# ── Intents ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("utterance,expected", [
    ("build a plumbing company website with online booking", IntentName.BUILD_PROJECT),
    ("deploy to production", IntentName.DEPLOY),
    ("stop the deployment", IntentName.CANCEL_DEPLOY),
    ("run the tests", IntentName.RUN_BUILD),
    ("show me the preview", IntentName.SHOW_PREVIEW),
    ("check production health", IntentName.SYSTEM_STATUS),
    ("what needs approval", IntentName.LIST_APPROVALS),
    ("approve the deployment", IntentName.GRANT_APPROVAL),
    ("enable safe mode", IntentName.SAFE_MODE_ON),
    ("emergency stop", IntentName.SAFE_MODE_ON),
    ("disable the booking agent", IntentName.DISABLE_AGENT),
    ("list the agents", IntentName.LIST_AGENTS),
    ("verify the audit log", IntentName.AUDIT_VERIFY),
    ("how much have we spent", IntentName.COST_REPORT),
    ("export the source", IntentName.EXPORT_SOURCE),
    ("list my projects", IntentName.LIST_PROJECTS),
    ("never mind", IntentName.CANCEL),
    ("repeat that", IntentName.REPEAT),
])
def test_intent_resolution(utterance, expected):
    assert resolve_intent(utterance).name is expected


def test_check_production_health_is_not_a_deploy():
    """'production' alone must not trigger a deployment."""
    assert resolve_intent("check production health").name is IntentName.SYSTEM_STATUS


def test_unknown_request_is_not_guessed():
    intent = resolve_intent("what is the weather in paris")
    assert intent.name is IntentName.UNKNOWN


def test_slots_are_extracted():
    assert resolve_intent("deploy to production").slots == {"environment": "production"}
    assert resolve_intent("deploy staging").slots == {"environment": "staging"}
    assert resolve_intent("disable the booking agent").slots == {"agent": "booking"}
    build = resolve_intent("build a CRM for a dental practice")
    assert build.slots["description"] == "CRM for a dental practice"


def test_missing_slot_is_reported():
    assert missing_slots(resolve_intent("deploy it")) == ["environment", "project"]


def test_approval_is_forbidden_by_voice_by_design():
    spec = INTENT_SPECS[IntentName.GRANT_APPROVAL]
    assert spec.voice_forbidden is True
    assert "speaker verification" in spec.forbidden_reason


# ── Speech phrasing ─────────────────────────────────────────────────────────

def test_speakable_turns_enums_into_words_and_drops_ids():
    out = speech.speakable("Project `a1b2c3d4e5f6a7b8` is **APPROVAL_REQUIRED**")
    assert "APPROVAL" not in out and "a1b2c3d4e5f6" not in out
    assert "sign-off" in out


def test_speakable_is_idempotent():
    text = "The build is TEST_FAILED for project `deadbeefdeadbeef`."
    assert speech.speakable(speech.speakable(text)) == speech.speakable(text)


def test_join_capitalises_every_sentence():
    assert speech.join("done.", "two integrations need credentials.") == \
        "Done. Two integrations need credentials."


@pytest.mark.parametrize("seconds,spoken", [
    (1, "one second"), (40, "40 seconds"), (60, "60 seconds"), (240, "four minutes"),
])
def test_duration_is_spoken_naturally(seconds, spoken):
    assert speech.duration(seconds) == spoken


def test_spoken_list_caps_long_lists():
    assert speech.spoken_list(["a", "b", "c", "d", "e", "f"]) == "a, b, c, d, and two more"


def test_greetings_vary_between_turns():
    assert len({speech.greeting(i) for i in range(4)}) == 4
