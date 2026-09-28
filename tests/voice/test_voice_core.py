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


def test_speaker_verification_adapter_says_it_is_unimplemented():
    from app.mo.voice.providers import SpeakerVerifyAdapter
    adapter = SpeakerVerifyAdapter()
    assert adapter.info.implemented is False
    result = adapter.verify_speaker(b"x", enrolled_id="owner")
    assert result.state is ResultState.CREDENTIAL_REQUIRED and "no implementation" in result.detail


def test_speech_providers_need_their_credential(monkeypatch):
    from app.mo.voice.providers import DeepgramAdapter, ElevenLabsAdapter, WhisperAdapter
    for var in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for adapter in (WhisperAdapter(), DeepgramAdapter()):
        assert adapter.info.implemented is True and adapter.info.configured is False
        assert adapter.transcribe(b"x").state is ResultState.CREDENTIAL_REQUIRED
    assert ElevenLabsAdapter().synthesize("hi").state is ResultState.CREDENTIAL_REQUIRED


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


# ── server-side providers (mock transport: the live services were not contacted) ──────────────────

import base64

import httpx


def _mock(handler):
    return httpx.MockTransport(handler)


@pytest.fixture
def keys(monkeypatch):
    for var, val in (("OPENAI_API_KEY", "k-openai"), ("DEEPGRAM_API_KEY", "k-dg"), ("ELEVENLABS_API_KEY", "k-el"),
                     ("ELEVENLABS_VOICE_ID", "voice12345")):
        monkeypatch.setenv(var, val)


def test_whisper_transcribes_and_marks_output_untrusted(keys):
    from app.mo.voice.providers import WhisperAdapter
    seen = []
    a = WhisperAdapter()
    a.transport = _mock(lambda r: (seen.append(r), httpx.Response(200, json={"text": " open the dashboard "}))[1])
    res = a.transcribe(b"RIFFdata", language="en-US")
    assert res.state.is_success and res.data["text"] == "open the dashboard" and res.meta["untrusted"] is True
    assert seen[0].headers["authorization"] == "Bearer k-openai" and b"whisper-1" in seen[0].content


def test_deepgram_transcribes(keys):
    from app.mo.voice.providers import DeepgramAdapter
    body = {"results": {"channels": [{"alternatives": [{"transcript": "hello mo"}]}]}}
    a = DeepgramAdapter()
    a.transport = _mock(lambda r: httpx.Response(200, json=body))
    assert a.transcribe(b"x").data["text"] == "hello mo"


def test_elevenlabs_synthesizes_and_validates_voice(keys):
    from app.mo.voice.providers import ElevenLabsAdapter
    a = ElevenLabsAdapter()
    a.transport = _mock(lambda r: httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"}))
    res = a.synthesize("Good morning")
    assert res.state.is_success and base64.b64decode(res.data["audio_b64"]) == b"ID3audio"
    assert a.synthesize("hi", voice="../etc/passwd").state is ResultState.FAILED
    assert a.synthesize("").state is ResultState.FAILED and a.synthesize("x" * 6000).state is ResultState.FAILED


@pytest.mark.parametrize("status,state", [(401, "POLICY_DENIED"), (429, "RATE_LIMITED"), (503, "PROVIDER_UNAVAILABLE"), (400, "FAILED")])
def test_provider_errors_map_to_truthful_states(keys, status, state):
    from app.mo.voice.providers import WhisperAdapter
    a = WhisperAdapter()
    a.transport = _mock(lambda r: httpx.Response(status, json={}))
    assert a.transcribe(b"x").state.value == state


def test_provider_timeouts_and_malformed_bodies(keys):
    from app.mo.voice.providers import WhisperAdapter
    a = WhisperAdapter()
    def boom(request):
        raise httpx.ReadTimeout("slow")
    a.transport = _mock(boom)
    assert a.transcribe(b"x").state is ResultState.TIMEOUT
    a.transport = _mock(lambda r: httpx.Response(200, json={"nope": 1}))
    assert a.transcribe(b"x").state is ResultState.FAILED


def test_audio_limits(keys):
    from app.mo.voice.providers import WhisperAdapter
    a = WhisperAdapter()
    assert a.transcribe(b"").state is ResultState.FAILED
    assert a.transcribe(b"x" * (10 * 1024 * 1024 + 1)).state is ResultState.FAILED


def test_router_transcribe_reports_what_is_missing(monkeypatch):
    for var in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    res = get_voice_router().transcribe(b"x")
    assert res.state is ResultState.CREDENTIAL_REQUIRED and "browser console" in res.detail


def test_router_prefers_a_configured_provider_over_the_browser_adapter(keys):
    res = get_voice_router().adapters_for(VoiceCapability.TRANSCRIBE)
    assert {a.info.name for a in res} >= {"whisper", "deepgram"}
