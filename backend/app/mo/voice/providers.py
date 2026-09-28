"""
MO NEXUS OMEGA — Voice provider fabric.

Speech is a provider-independent capability, the same way models are. Nothing in
MO calls a speech SDK directly; everything goes through a VoiceRouter that picks
a capable, configured, healthy adapter and reports honestly when it cannot.

WHAT ACTUALLY WORKS RIGHT NOW, AND WHAT DOES NOT — read this before believing a
capability matrix:

  BrowserSpeechAdapter   WORKS with zero credentials. Speech recognition and
                         synthesis execute in the viewer's browser via the Web
                         Speech API; the server only receives the resulting
                         transcript and returns the text to speak. This is the
                         adapter that makes the JARVIS console real today.

  WhisperAdapter         Declared, not implemented. Needs OPENAI_API_KEY.
  DeepgramAdapter        Declared, not implemented. Needs DEEPGRAM_API_KEY.
  ElevenLabsAdapter      Declared, not implemented. Needs ELEVENLABS_API_KEY.
  TwilioVoiceAdapter     Backed by the existing real TwiML flow; needs Twilio.
  SpeakerVerifyAdapter   Declared, not implemented. Voice biometrics need a
                         provider; there is no offline substitute, so speaker
                         verification reports CREDENTIAL_REQUIRED rather than
                         pretending to identify anyone.

Wake word is the capability most often overstated. See WakeWordMode below: what
MO does today is transcript-level phrase matching, not an acoustic always-on
keyword model. The router reports which mode is in force so a caller cannot
mistake one for the other.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..errors import MoResult, ResultState


class VoiceCapability(str):
    TRANSCRIBE = "TRANSCRIBE"           # speech -> text
    SYNTHESIZE = "SYNTHESIZE"           # text -> speech
    STREAM_TRANSCRIBE = "STREAM_TRANSCRIBE"
    WAKE_WORD = "WAKE_WORD"
    VAD = "VAD"                         # voice activity detection
    BARGE_IN = "BARGE_IN"
    SPEAKER_VERIFY = "SPEAKER_VERIFY"
    TELEPHONY = "TELEPHONY"


class WakeWordMode(str):
    """
    How wake-word detection is actually performed. Never report a stronger mode
    than the one in force.

    TRANSCRIPT_KEYWORD  The recogniser transcribes continuously and MO matches
                        the wake phrase against the resulting text. Real and
                        working, but it means audio is being transcribed before
                        the wake phrase is seen, and detection latency is the
                        recogniser's latency.
    ACOUSTIC_MODEL      A dedicated on-device keyword-spotting model runs before
                        any transcription (what Alexa and Siri do). MO has no
                        such model bundled; this mode is never returned today.
    """

    TRANSCRIPT_KEYWORD = "TRANSCRIPT_KEYWORD"
    ACOUSTIC_MODEL = "ACOUSTIC_MODEL"


class ExecutionSite(str):
    """Where the work physically happens — it changes the privacy story."""

    CLIENT = "CLIENT"      # in the viewer's browser; audio never reaches MO
    SERVER = "SERVER"      # MO process
    PROVIDER = "PROVIDER"  # a third party receives the audio


@dataclass
class VoiceProviderInfo:
    name: str
    capabilities: frozenset[str]
    execution_site: str
    credential_env_var: Optional[str] = None
    implemented: bool = True
    languages: tuple[str, ...] = ("en-US",)
    notes: str = ""

    @property
    def configured(self) -> bool:
        if not self.implemented:
            return False
        if not self.credential_env_var:
            return True
        return bool(os.getenv(self.credential_env_var, "").strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "execution_site": self.execution_site,
            "credential_env_var": self.credential_env_var,
            "implemented": self.implemented,
            "configured": self.configured,
            "languages": list(self.languages),
            "notes": self.notes,
        }


class VoiceAdapter(ABC):
    """A speech provider. Unimplemented adapters must say so, not fake output."""

    @property
    @abstractmethod
    def info(self) -> VoiceProviderInfo: ...

    def transcribe(self, audio: bytes, *, language: str = "en-US") -> MoResult:
        return self._unavailable(VoiceCapability.TRANSCRIBE)

    def synthesize(self, text: str, *, voice: str = "default", language: str = "en-US") -> MoResult:
        return self._unavailable(VoiceCapability.SYNTHESIZE)

    def verify_speaker(self, audio: bytes, *, enrolled_id: str) -> MoResult:
        return self._unavailable(VoiceCapability.SPEAKER_VERIFY)

    def _unavailable(self, capability: str) -> MoResult:
        info = self.info
        if not info.implemented:
            return MoResult(
                ResultState.CREDENTIAL_REQUIRED,
                f"{info.name} has no implementation in this build; "
                f"'{capability}' is declared but not wired. "
                + (f"It would also require {info.credential_env_var}."
                   if info.credential_env_var else ""),
                meta={"provider": info.name, "capability": capability,
                      "env_var": info.credential_env_var},
            )
        if not info.configured:
            return MoResult.credential_required(info.name, info.credential_env_var or "")
        return MoResult(
            ResultState.FAILED,
            f"{info.name} does not support '{capability}'.",
            meta={"provider": info.name, "capability": capability},
        )


class BrowserSpeechAdapter(VoiceAdapter):
    """
    The Web Speech API, executed in the viewer's browser.

    Transcription and synthesis both happen client-side, so `transcribe` and
    `synthesize` here return *directives* the client carries out rather than
    audio bytes — the server never holds the microphone stream. That is a
    deliberate privacy property, not a limitation being glossed over: raw audio
    does not reach MO at all on this path.
    """

    @property
    def info(self) -> VoiceProviderInfo:
        return VoiceProviderInfo(
            name="browser_web_speech",
            capabilities=frozenset({
                VoiceCapability.TRANSCRIBE, VoiceCapability.SYNTHESIZE,
                VoiceCapability.STREAM_TRANSCRIBE, VoiceCapability.WAKE_WORD,
                VoiceCapability.VAD, VoiceCapability.BARGE_IN,
            }),
            execution_site=ExecutionSite.CLIENT,
            credential_env_var=None,
            implemented=True,
            languages=("en-US", "en-GB", "es-ES", "fr-FR", "de-DE", "hi-IN", "ar-SA", "zh-CN"),
            notes="Runs in the browser. Requires a Chromium or Safari engine for "
                  "recognition; synthesis works in every modern browser. Raw audio "
                  "never leaves the client.",
        )

    def synthesize(self, text: str, *, voice: str = "default", language: str = "en-US") -> MoResult:
        """Return a speak directive for the client, not audio bytes."""
        if not (text or "").strip():
            return MoResult(ResultState.FAILED, "Nothing to speak: text is empty.")
        return MoResult.ok(
            {"directive": "speak", "text": text, "voice": voice, "language": language},
            provider="browser_web_speech", execution_site=ExecutionSite.CLIENT,
        )

    def transcribe(self, audio: bytes, *, language: str = "en-US") -> MoResult:
        return MoResult(
            ResultState.POLICY_DENIED,
            "Server-side transcription is not part of the browser path: recognition "
            "runs in the client and MO receives only the transcript. Post the "
            "transcript to the voice turn endpoint instead of uploading audio.",
            meta={"provider": "browser_web_speech", "execution_site": ExecutionSite.CLIENT},
        )


class _DeclaredOnlyAdapter(VoiceAdapter):
    """Base for providers MO has a slot for but has not implemented."""

    _name = "declared"
    _caps: frozenset[str] = frozenset()
    _env: Optional[str] = None
    _note = ""
    _langs: tuple[str, ...] = ("en-US",)

    @property
    def info(self) -> VoiceProviderInfo:
        return VoiceProviderInfo(
            name=self._name, capabilities=self._caps,
            execution_site=ExecutionSite.PROVIDER, credential_env_var=self._env,
            implemented=False, languages=self._langs, notes=self._note,
        )


class WhisperAdapter(_DeclaredOnlyAdapter):
    _name = "whisper"
    _caps = frozenset({VoiceCapability.TRANSCRIBE})
    _env = "OPENAI_API_KEY"
    _note = "Batch transcription of uploaded audio. Not streaming."
    _langs = ("en-US", "es-ES", "fr-FR", "de-DE", "hi-IN", "ar-SA", "zh-CN", "ja-JP")


class DeepgramAdapter(_DeclaredOnlyAdapter):
    _name = "deepgram"
    _caps = frozenset({VoiceCapability.TRANSCRIBE, VoiceCapability.STREAM_TRANSCRIBE,
                       VoiceCapability.VAD})
    _env = "DEEPGRAM_API_KEY"
    _note = "Low-latency streaming transcription with server-side VAD — the adapter "
    "to implement if browser recognition is not acceptable."


class ElevenLabsAdapter(_DeclaredOnlyAdapter):
    _name = "elevenlabs"
    _caps = frozenset({VoiceCapability.SYNTHESIZE})
    _env = "ELEVENLABS_API_KEY"
    _note = "High-quality synthesis with custom voices."


class SpeakerVerifyAdapter(_DeclaredOnlyAdapter):
    _name = "speaker_verification"
    _caps = frozenset({VoiceCapability.SPEAKER_VERIFY})
    _env = "VOICE_BIOMETRICS_API_KEY"
    _note = ("Voice biometrics. There is no offline substitute, so MO never claims "
             "to have identified a speaker by voice. Until this is configured, a "
             "voice session's identity comes from its bearer token, exactly like an "
             "HTTP request.")


class TwilioVoiceAdapter(VoiceAdapter):
    """Telephony, backed by the existing TwiML flow in app/twilio_voice.py."""

    @property
    def info(self) -> VoiceProviderInfo:
        return VoiceProviderInfo(
            name="twilio",
            capabilities=frozenset({VoiceCapability.TELEPHONY, VoiceCapability.TRANSCRIBE,
                                    VoiceCapability.SYNTHESIZE}),
            execution_site=ExecutionSite.PROVIDER,
            credential_env_var="TWILIO_AUTH_TOKEN",
            implemented=True,
            notes="Turn-based phone calls via TwiML Gather/Say. Real, but not a "
                  "streaming full-duplex pipeline: no barge-in mid-prompt.",
        )

    def synthesize(self, text: str, *, voice: str = "default", language: str = "en-US") -> MoResult:
        if not self.info.configured:
            return MoResult.credential_required("twilio", "TWILIO_AUTH_TOKEN")
        from ...twilio_voice import twiml_say
        return MoResult.ok({"twiml": twiml_say(text, then_hangup=False)},
                           provider="twilio", execution_site=ExecutionSite.PROVIDER)


# ── Wake word ────────────────────────────────────────────────────────────────

DEFAULT_WAKE_PHRASES: tuple[str, ...] = ("mo", "hey mo", "okay mo", "hey nexus", "jarvis")


@dataclass
class WakeWordConfig:
    phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES
    mode: str = WakeWordMode.TRANSCRIPT_KEYWORD
    require_wake_phrase: bool = True
    # How long, after a wake phrase, further speech counts as part of the session.
    follow_up_window_seconds: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrases": list(self.phrases), "mode": self.mode,
            "require_wake_phrase": self.require_wake_phrase,
            "follow_up_window_seconds": self.follow_up_window_seconds,
            "honest_note": (
                "Mode TRANSCRIPT_KEYWORD means audio is transcribed continuously and "
                "the phrase is matched in text. It is not an acoustic always-on "
                "keyword model of the kind Alexa and Siri ship."
            ),
        }


def strip_wake_phrase(text: str, config: Optional[WakeWordConfig] = None) -> tuple[bool, str]:
    """
    Detect a leading wake phrase and return (detected, remaining_command).

    Matching is anchored at the start and tolerant of punctuation and filler, so
    "MO, build me a CRM" and "hey mo build me a CRM" both yield "build me a CRM".
    """
    config = config or WakeWordConfig()
    cleaned = (text or "").strip()
    if not cleaned:
        return False, ""
    lowered = cleaned.lower()
    # Longest phrase first so "hey mo" wins over "mo".
    for phrase in sorted(config.phrases, key=len, reverse=True):
        pattern = rf"^\s*{re.escape(phrase)}\b[\s,.:;!?-]*"
        match = re.match(pattern, lowered)
        if match:
            return True, cleaned[match.end():].strip()
    return False, cleaned


# ── Router ───────────────────────────────────────────────────────────────────

class VoiceRouter:
    """Selects a voice adapter by capability. Reports the truth about coverage."""

    def __init__(self, adapters: Optional[list[VoiceAdapter]] = None):
        self._adapters: list[VoiceAdapter] = adapters if adapters is not None else [
            BrowserSpeechAdapter(),
            TwilioVoiceAdapter(),
            DeepgramAdapter(),
            WhisperAdapter(),
            ElevenLabsAdapter(),
            SpeakerVerifyAdapter(),
        ]

    def adapters_for(self, capability: str, *, configured_only: bool = True) -> list[VoiceAdapter]:
        out = []
        for adapter in self._adapters:
            info = adapter.info
            if capability not in info.capabilities:
                continue
            if configured_only and not info.configured:
                continue
            out.append(adapter)
        return out

    def pick(self, capability: str) -> Optional[VoiceAdapter]:
        candidates = self.adapters_for(capability)
        return candidates[0] if candidates else None

    def synthesize(self, text: str, *, voice: str = "default", language: str = "en-US") -> MoResult:
        adapter = self.pick(VoiceCapability.SYNTHESIZE)
        if adapter is None:
            return MoResult(
                ResultState.CREDENTIAL_REQUIRED,
                "No speech-synthesis provider is available. The browser adapter "
                "covers this with no credentials when the command arrives from the "
                "JARVIS console; a server-side voice needs ELEVENLABS_API_KEY or Twilio.",
                meta={"capability": VoiceCapability.SYNTHESIZE},
            )
        return adapter.synthesize(text, voice=voice, language=language)

    def verify_speaker(self, audio: bytes, *, enrolled_id: str) -> MoResult:
        adapter = self.pick(VoiceCapability.SPEAKER_VERIFY)
        if adapter is None:
            return MoResult(
                ResultState.CREDENTIAL_REQUIRED,
                "Speaker verification has no configured provider. A voice session's "
                "identity therefore comes from its bearer token, not from the voice "
                "itself — MO does not guess who is speaking.",
                meta={"capability": VoiceCapability.SPEAKER_VERIFY,
                      "env_var": "VOICE_BIOMETRICS_API_KEY"},
            )
        return adapter.verify_speaker(audio, enrolled_id=enrolled_id)

    def capabilities(self) -> dict[str, Any]:
        """A truthful capability matrix, including what is missing and why."""
        by_capability: dict[str, dict[str, Any]] = {}
        for capability in (
            VoiceCapability.TRANSCRIBE, VoiceCapability.SYNTHESIZE,
            VoiceCapability.STREAM_TRANSCRIBE, VoiceCapability.WAKE_WORD,
            VoiceCapability.VAD, VoiceCapability.BARGE_IN,
            VoiceCapability.SPEAKER_VERIFY, VoiceCapability.TELEPHONY,
        ):
            available = [a.info.name for a in self.adapters_for(capability)]
            declared = [a.info.name for a in self.adapters_for(capability, configured_only=False)]
            by_capability[capability] = {
                "available": available,
                "declared_but_unavailable": [n for n in declared if n not in available],
                "supported": bool(available),
            }
        return {
            "providers": [a.info.to_dict() for a in self._adapters],
            "by_capability": by_capability,
            "wake_word": WakeWordConfig().to_dict(),
            "known_gaps": [
                "No acoustic always-on wake-word model is bundled; wake detection is "
                "transcript-level phrase matching (WakeWordMode.TRANSCRIPT_KEYWORD).",
                "No speaker verification provider is configured; a voice session is "
                "authenticated by bearer token, never by voice identity.",
                "Server-side streaming transcription is not implemented; the working "
                "path runs recognition in the browser.",
                "Telephony (Twilio) is turn-based TwiML, so there is no barge-in on "
                "a phone call even though the browser console supports it.",
            ],
        }


_router: Optional[VoiceRouter] = None


def get_voice_router() -> VoiceRouter:
    global _router
    if _router is None:
        _router = VoiceRouter()
    return _router


def reset_voice_router() -> None:
    global _router
    _router = None
