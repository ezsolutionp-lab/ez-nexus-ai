"""
MO NEXUS OMEGA — Voice conversation engine.

The loop behind "call MO's name, talk to it like a person, and it does the work":

    utterance
      -> wake gate          asleep? only the wake phrase gets through
      -> intent + slots     what is being asked, with what details
      -> follow-up          missing a detail? ask for it, remember the question
      -> governance         scope, MFA, approval, voice-forbidden — same rules as HTTP
      -> execute            the real MO operation, never a simulation
      -> reply              a spoken sentence, plus a TTS directive for the client

Governance is the part that must not bend. A voice context is built from the
same authenticated RequestContext as an HTTP call, with the channel stamped
VOICE, and every action goes through the same approval engine. Some actions are
refused outright on voice (approving a request) because speech alone cannot
establish who is speaking — see IntentSpec.voice_forbidden.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext, SourceChannel
from ..db import (
    AgentManifestRecord, ApprovalRequest, AuditEvent, BuilderBuild, BuilderDeployment,
    BuilderProject, Tenant, VoiceSession, VoiceTurn,
)
from ..errors import MoError, MoResult, ResultState
from ..events import fabric as event_fabric
from ..security.zero_trust import hit_bucket
from . import speech
from .intents import INTENT_SPECS, Intent, IntentName, missing_slots, resolve_intent
from .providers import WakeWordConfig, get_voice_router, strip_wake_phrase


@dataclass
class VoiceReply:
    """What the engine hands back for one utterance."""

    text: str
    state: ResultState
    intent: Optional[Intent] = None
    awake: bool = False
    expecting: Optional[str] = None          # slot MO just asked a question about
    data: dict[str, Any] = field(default_factory=dict)
    end_session: bool = False
    sleep: bool = False                      # stop listening; wake phrase needed again

    def to_dict(self, *, session_id: str, turn_seq: int, latency_ms: int) -> dict[str, Any]:
        synth = get_voice_router().synthesize(self.text) if self.text else None
        return {
            "session_id": session_id,
            "turn": turn_seq,
            "reply": self.text,
            "state": self.state.value,
            "ok": self.state.is_success,
            "awake": self.awake,
            "expecting": self.expecting,
            "end_session": self.end_session,
            "intent": self.intent.to_dict() if self.intent else None,
            "speak": synth.data if synth and synth.state.is_success else None,
            "data": self.data,
            "latency_ms": latency_ms,
        }


def voice_context(ctx: RequestContext) -> RequestContext:
    """Same authority as the caller, stamped as the VOICE channel. Never wider."""
    return RequestContext(
        tenant_id=ctx.tenant_id, actor_id=ctx.actor_id, actor_type=ctx.actor_type,
        actor_label=ctx.actor_label, is_admin=ctx.is_admin, scopes=ctx.scopes,
        source_channel=SourceChannel.VOICE, mfa_verified=ctx.mfa_verified,
        data_classification=ctx.data_classification, trace_id=ctx.trace_id,
        ip_address=ctx.ip_address,
    )


class VoiceEngine:
    def __init__(
        self,
        db: Session,
        ctx: RequestContext,
        *,
        workspace_root: Path,
        wake: Optional[WakeWordConfig] = None,
        clock: Callable[[], datetime] = datetime.utcnow,
    ):
        self.db = db
        self.ctx = voice_context(ctx)
        self.workspace_root = Path(workspace_root)
        self.wake = wake or WakeWordConfig()
        self.clock = clock

    # ── sessions ─────────────────────────────────────────────────────────────

    def start_session(self, *, language: str = "en-US", channel: str = "BROWSER") -> VoiceSession:
        session = VoiceSession(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id,
            actor_id=self.ctx.actor_id, channel=channel, language=language,
            status="ACTIVE",
        )
        self.db.add(session)
        self.db.flush()
        chain.record(self.db, self.ctx, action="voice.session.started",
                     result_state=ResultState.SUCCESS, resource_type="voice_session",
                     resource_id=session.id)
        return session

    def load_session(self, session_id: str) -> VoiceSession:
        session = self.db.get(VoiceSession, session_id)
        if session is None:
            raise MoError(ResultState.FAILED, f"Voice session {session_id} does not exist.")
        # A session belongs to a tenant *and* a speaker. Another user in the same
        # tenant must not be able to continue someone else's conversation.
        self.ctx.require_same_tenant(session.tenant_id, f"Voice session {session_id}")
        if session.actor_id != self.ctx.actor_id:
            raise MoError(ResultState.POLICY_DENIED,
                          "That voice session belongs to someone else.")
        if session.status != "ACTIVE":
            raise MoError(ResultState.BLOCKED, "That voice session has ended. Start a new one.")
        return session

    def end_session(self, session: VoiceSession) -> None:
        session.status = "ENDED"
        session.ended_at = self.clock()
        session.awake_until = None
        self.db.flush()
        chain.record(self.db, self.ctx, action="voice.session.ended",
                     result_state=ResultState.SUCCESS, resource_type="voice_session",
                     resource_id=session.id, detail=f"{session.turn_count} turn(s)")

    def is_awake(self, session: VoiceSession) -> bool:
        return bool(session.awake_until and self.clock() < session.awake_until)

    def _wake(self, session: VoiceSession) -> None:
        session.awake_until = self.clock() + timedelta(seconds=self.wake.follow_up_window_seconds)

    # ── the turn ─────────────────────────────────────────────────────────────

    def handle(self, session: VoiceSession, transcript: str) -> dict[str, Any]:
        """Process one utterance end to end and persist the turn."""
        started = time.perf_counter()
        seed = session.turn_count
        reply = self._respond(session, transcript or "", seed)

        # Any turn MO actually answers keeps the conversation open, so the user
        # does not have to repeat the wake phrase for every follow-up.
        if reply.awake and not reply.end_session:
            self._wake(session)
        if reply.end_session or reply.sleep:
            session.awake_until = None

        session.turn_count += 1
        if reply.text:
            session.last_response = reply.text
        latency_ms = int((time.perf_counter() - started) * 1000)

        wake_detected, _ = strip_wake_phrase(transcript, self.wake)
        self.db.add(VoiceTurn(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id,
            session_id=session.id, seq=session.turn_count,
            transcript=(transcript or "")[:4000], wake_detected=wake_detected,
            intent=reply.intent.name.value if reply.intent else None,
            confidence=reply.intent.confidence if reply.intent else None,
            slots_json=json.dumps(reply.intent.slots if reply.intent else {}),
            result_state=reply.state.value, reply=reply.text, latency_ms=latency_ms,
        ))
        self.db.flush()
        chain.record(
            self.db, self.ctx, action="voice.turn", result_state=reply.state,
            resource_type="voice_session", resource_id=session.id,
            detail=reply.intent.name.value if reply.intent else "asleep",
            payload={"transcript": (transcript or "")[:300],
                     "intent": reply.intent.name.value if reply.intent else None},
        )
        return reply.to_dict(session_id=session.id, turn_seq=session.turn_count,
                             latency_ms=latency_ms)

    def _respond(self, session: VoiceSession, transcript: str, seed: int) -> VoiceReply:
        detected, command = strip_wake_phrase(transcript, self.wake)
        awake = self.is_awake(session)

        # 1. Asleep and not addressed: stay silent. Ambient speech is not a command.
        if not awake and not detected and self.wake.require_wake_phrase:
            return VoiceReply(text="", state=ResultState.SUCCESS, awake=False,
                              data={"ignored": "no wake phrase while asleep"})

        # 2. Just the name: answer like a person would when called.
        if detected and not command:
            return VoiceReply(text=speech.greeting(seed), state=ResultState.SUCCESS, awake=True)

        utterance = command if detected else transcript

        # 3. Answering a question MO asked on the previous turn.
        if session.pending_intent:
            return self._continue_pending(session, utterance, seed)

        intent = resolve_intent(utterance)
        return self._dispatch(session, intent, seed)

    def _continue_pending(self, session: VoiceSession, utterance: str, seed: int) -> VoiceReply:
        """Fill the slot MO asked about, then run the original request."""
        # The user may change their mind instead of answering.
        redirect = resolve_intent(utterance)
        if redirect.name is IntentName.CANCEL:
            self._clear_pending(session)
            return VoiceReply(text=speech.cancelled(seed), state=ResultState.CANCELLED,
                              intent=redirect, awake=True)

        pending = IntentName(session.pending_intent)
        slots = json.loads(session.pending_slots_json or "{}")
        asked = slots.pop("__asked__", None)

        answer = utterance.strip(" .,")
        if asked == "environment":
            lowered = answer.lower()
            if "prod" in lowered or "live" in lowered:
                answer = "production"
            elif "stag" in lowered or "test" in lowered:
                answer = "staging"
            else:
                return VoiceReply(text="Sorry, staging or production?",
                                  state=ResultState.PARTIAL, awake=True,
                                  intent=Intent(pending, 1.0, slots=slots),
                                  expecting="environment")
        if asked:
            slots[asked] = answer

        self._clear_pending(session)
        intent = Intent(pending, 1.0, slots=slots, transcript=utterance,
                        provenance="FOLLOW_UP")
        return self._dispatch(session, intent, seed)

    def _clear_pending(self, session: VoiceSession) -> None:
        session.pending_intent = None
        session.pending_slots_json = "{}"

    # ── dispatch ─────────────────────────────────────────────────────────────

    def _dispatch(self, session: VoiceSession, intent: Intent, seed: int) -> VoiceReply:
        spec = intent.spec

        if intent.name is IntentName.UNKNOWN:
            return VoiceReply(text=speech.did_not_catch(seed), state=ResultState.FAILED,
                              intent=intent, awake=True)

        # Governance, before anything else runs.
        if spec.voice_forbidden:
            return VoiceReply(text=speech.refusal(spec.forbidden_reason),
                              state=ResultState.POLICY_DENIED, intent=intent, awake=True)
        if spec.required_scope and not (self.ctx.is_admin or spec.required_scope in self.ctx.scopes):
            return VoiceReply(
                text="You don't have permission to do that. An administrator would need to.",
                state=ResultState.POLICY_DENIED, intent=intent, awake=True)
        if spec.requires_mfa and not self.ctx.mfa_verified and intent.name is not IntentName.DEPLOY:
            return VoiceReply(
                text="That's a high-risk action, so it needs a session signed in with "
                     "two-factor authentication. Sign in again with your second factor "
                     "and ask me once more.",
                state=ResultState.POLICY_DENIED, intent=intent, awake=True)

        # Ask for anything missing, and remember what was asked.
        gaps = missing_slots(intent)
        required_gaps = [g for g in gaps if g in _REQUIRED_SLOTS.get(intent.name, ())]
        if required_gaps:
            slot = required_gaps[0]
            session.pending_intent = intent.name.value
            session.pending_slots_json = json.dumps({**intent.slots, "__asked__": slot})
            return VoiceReply(text=speech.ask_for_slot(slot, spec.summary),
                              state=ResultState.PARTIAL, intent=intent, awake=True,
                              expecting=slot)

        handler = getattr(self, f"_do_{intent.name.name.lower()}", None)
        if handler is None:
            return VoiceReply(
                text=f"I understood that as {spec.summary.lower().rstrip('.')}, but I "
                     "can't do it by voice yet. It's available in the console.",
                state=ResultState.BLOCKED, intent=intent, awake=True)

        try:
            reply = handler(session, intent, seed)
        except MoError as exc:
            reply = VoiceReply(text=speech.blocked(exc.detail), state=exc.state,
                               intent=intent, awake=True)
        reply.intent = reply.intent or intent
        # Handlers default to keeping the conversation open. A handler that sets
        # sleep=True (e.g. "never mind") is saying MO should stop listening now —
        # overriding that would leave MO acting on whatever is said next.
        reply.awake = not (reply.end_session or reply.sleep)
        return reply

    # ── helpers ──────────────────────────────────────────────────────────────

    def _focus_project(self, session: VoiceSession, intent: Intent) -> Optional[BuilderProject]:
        """The project the user means: named, or the one we were just talking about."""
        name = (intent.slots.get("project") or "").strip().lower()
        q = self.db.query(BuilderProject).filter(BuilderProject.tenant_id == self.ctx.tenant_id)
        if name and name not in ("it", "that", "this", "the project", "last project",
                                 "the last project", "my project"):
            for project in q.order_by(BuilderProject.created_at.desc()).all():
                if name in project.name.lower() or name in project.slug:
                    session.focus_project_id = project.id
                    return project
        if session.focus_project_id:
            project = self.db.get(BuilderProject, session.focus_project_id)
            if project and project.tenant_id == self.ctx.tenant_id:
                return project
        latest = q.order_by(BuilderProject.created_at.desc()).first()
        if latest:
            session.focus_project_id = latest.id
        return latest

    def _no_project(self) -> VoiceReply:
        return VoiceReply(
            text="There aren't any projects yet. Tell me what to build and I'll start one.",
            state=ResultState.BLOCKED, awake=True)

    def _compiler(self):
        from ..builder.compiler import BuilderCompiler
        return BuilderCompiler(self.db, self.ctx, workspace_root=self.workspace_root)

    # ── handlers: conversation ───────────────────────────────────────────────

    def _do_help(self, session, intent, seed) -> VoiceReply:
        return VoiceReply(
            text="You can ask me to build something, like build a booking website for a "
                 "plumber. Or run the tests, show the preview, deploy to staging, check "
                 "the system health, list the agents, or tell you what it's cost so far. "
                 "Say never mind to stop.",
            state=ResultState.SUCCESS)

    def _do_repeat(self, session, intent, seed) -> VoiceReply:
        return VoiceReply(text=session.last_response or "I haven't said anything yet.",
                          state=ResultState.SUCCESS)

    def _do_cancel(self, session, intent, seed) -> VoiceReply:
        """ "Never mind" means stop listening, not "keep listening for 30 seconds". """
        self._clear_pending(session)
        return VoiceReply(text=speech.goodbye(seed), state=ResultState.CANCELLED, sleep=True)

    # ── handlers: system ─────────────────────────────────────────────────────

    def _do_system_status(self, session, intent, seed) -> VoiceReply:
        from ..modelfabric.router import get_router
        tenant = self.db.get(Tenant, self.ctx.tenant_id)
        projects = self.db.query(BuilderProject).filter(
            BuilderProject.tenant_id == self.ctx.tenant_id).count()
        pending = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.tenant_id == self.ctx.tenant_id,
            ApprovalRequest.status == "PENDING").count()
        failed = self.db.query(BuilderBuild).filter(
            BuilderBuild.tenant_id == self.ctx.tenant_id,
            BuilderBuild.state.in_(["BUILD_FAILED", "TEST_FAILED", "SECURITY_FAILED"])).count()
        models_ok = get_router().is_configured
        verdict = chain.verify_chain(self.db, self.ctx.tenant_id)

        parts = []
        if tenant is not None and tenant.safe_mode:
            parts.append("Safe mode is on, so write operations are suspended.")
        parts.append("Everything's running." if not failed else
                     f"The platform is up, but {plural_phrase(failed, 'build has', 'builds have')} failed.")
        parts.append(f"You have {speech.plural(projects, 'project')}"
                     + (f" and {speech.plural(pending, 'approval')} waiting." if pending else "."))
        parts.append("The audit trail checks out." if verdict["valid"] else
                     "Warning: the audit trail failed verification.")
        if not models_ok:
            parts.append("No AI model provider is connected, so I'm working from built-in "
                         "rules rather than a language model.")
        return VoiceReply(text=speech.join(*parts), state=ResultState.SUCCESS,
                          data={"projects": projects, "pending_approvals": pending,
                                "failed_builds": failed, "audit_valid": verdict["valid"],
                                "model_configured": models_ok})

    def _do_system_capabilities(self, session, intent, seed) -> VoiceReply:
        caps = get_voice_router().capabilities()
        return VoiceReply(
            text="I can build software from a description, run its tests in a sandbox, "
                 "show previews, and request deployments, which always need your sign-off. "
                 "I can report on health, agents, approvals and cost. Honestly, a few things "
                 "aren't connected yet: I can't recognise you by voice, and there's no AI "
                 "model or deployment provider configured.",
            state=ResultState.SUCCESS, data={"capabilities": caps})

    def _do_safe_mode_on(self, session, intent, seed) -> VoiceReply:
        tenant = self.db.get(Tenant, self.ctx.tenant_id)
        if tenant is None:
            return VoiceReply(text="I couldn't find your tenant record, so I can't change safe mode.",
                              state=ResultState.FAILED)
        if tenant.safe_mode:
            return VoiceReply(text="Safe mode is already on.", state=ResultState.SUCCESS)
        tenant.safe_mode = True
        self.db.flush()
        chain.record(self.db, self.ctx, action="system.safe_mode.enabled",
                     result_state=ResultState.SUCCESS, resource_type="tenant",
                     resource_id=tenant.id, detail="enabled by voice")
        event_fabric.publish(self.db, self.ctx, "system.safe_mode", {"enabled": True})
        return VoiceReply(
            text="Done. Safe mode is on and all write operations are suspended. "
                 "Reads still work. Turning it back off needs an approval.",
            state=ResultState.SUCCESS)

    def _do_safe_mode_off(self, session, intent, seed) -> VoiceReply:
        from ..approvals import engine as approvals
        approval = approvals.request_approval(
            self.db, self.ctx, action="security.policy.modify",
            resource_type="tenant", resource_id=self.ctx.tenant_id,
            reason="Lift safe mode (requested by voice)")
        return VoiceReply(
            text="Lifting safe mode is a critical change, so I've asked for approval. "
                 "Someone other than you needs to sign it off in the console.",
            state=ResultState.APPROVAL_REQUIRED, data={"approval_id": approval.id})

    def _do_audit_verify(self, session, intent, seed) -> VoiceReply:
        verdict = chain.verify_chain(self.db, self.ctx.tenant_id)
        if verdict["valid"]:
            return VoiceReply(
                text=f"The audit trail is intact. I checked "
                     f"{speech.plural(verdict['checked'], 'record')} and every hash matches.",
                state=ResultState.SUCCESS, data=verdict)
        return VoiceReply(
            text=f"The audit trail failed verification at record {verdict['broken_at_seq']}. "
                 "That means something was changed after it was written. This needs looking at.",
            state=ResultState.FAILED, data=verdict)

    def _do_audit_recent(self, session, intent, seed) -> VoiceReply:
        count = min(int(intent.slots.get("count", 5)), 10)
        rows = (self.db.query(AuditEvent)
                .filter(AuditEvent.tenant_id == self.ctx.tenant_id,
                        AuditEvent.action != "voice.turn")
                .order_by(AuditEvent.seq.desc()).limit(count).all())
        if not rows:
            return VoiceReply(text="Nothing has happened yet.", state=ResultState.SUCCESS)
        actions = [r.action.replace(".", " ").replace("_", " ") for r in rows]
        return VoiceReply(
            text=f"The last {speech.plural(len(rows), 'event')}: "
                 f"{speech.spoken_list(actions, limit=count)}.",
            state=ResultState.SUCCESS)

    def _do_cost_report(self, session, intent, seed) -> VoiceReply:
        projects = self.db.query(BuilderProject).filter(
            BuilderProject.tenant_id == self.ctx.tenant_id).all()
        model_usd = sum(p.cost_model_usd or 0 for p in projects)
        sandbox = sum(p.sandbox_seconds or 0 for p in projects)
        if not projects:
            return VoiceReply(text="Nothing's been spent yet, there are no projects.",
                              state=ResultState.SUCCESS)
        model_part = ("No model spend, since no AI provider is connected."
                      if model_usd == 0 else f"Model spend is {model_usd:.2f} dollars.")
        return VoiceReply(
            text=f"{model_part} Builds have used about {speech.duration(sandbox)} of sandbox "
                 f"time across {speech.plural(len(projects), 'project')}.",
            state=ResultState.SUCCESS,
            data={"model_usd": model_usd, "sandbox_seconds": sandbox})

    # ── handlers: builder ────────────────────────────────────────────────────

    def _build_throttled(self) -> Optional[VoiceReply]:
        """Sandboxed builds share the strict 'build' ceiling with the HTTP builder."""
        if hit_bucket("build", f"voice:{self.ctx.tenant_id}:{self.ctx.actor_id}"):
            return None
        return VoiceReply(
            text="I've started a lot of builds in the last minute. Give me a moment, then ask again.",
            state=ResultState.RATE_LIMITED)

    def _do_build_project(self, session, intent, seed) -> VoiceReply:
        from ..builder.intent import BuildIntent
        if (throttled := self._build_throttled()) is not None:
            return throttled
        description = intent.slots.get("description", "").strip()
        build_intent = BuildIntent(
            prompt=f"Build {description}" if not description.lower().startswith("build") else description,
            tenant_id=self.ctx.tenant_id, requested_by=self.ctx.actor_id,
            source_channel=SourceChannel.VOICE,
        )
        project, report = self._compiler().compile(build_intent, run_build=True)
        session.focus_project_id = project.id

        req = report.stages.get("REQUIREMENTS", {}).get("counts", {})
        agents = report.stages.get("AGENT_MODEL", {})
        integ = report.stages.get("INTEGRATION_MODEL", {})
        built_ok = project.status == "TESTED"

        parts = [f"{speech.acknowledge(seed)} I've built {project.name}."]
        parts.append(
            f"It has {speech.plural(req.get('modules', 0), 'module')}, "
            f"{speech.plural(req.get('models', 0), 'data model')} and "
            f"{speech.plural(req.get('pages', 0), 'page')}.")
        if built_ok:
            parts.append("It compiled, passed the security checks, and all its tests passed.")
        else:
            parts.append(f"The build didn't finish cleanly: {report.detail or project.status}.")
        if agents.get("compiled"):
            parts.append(
                f"I set up {speech.plural(agents['compiled'], 'AI agent')}, but they can't go "
                "live until an AI model is connected." if agents.get("credential_blocked")
                else f"{speech.plural(agents['compiled'], 'AI agent')} are ready.")
        creds = integ.get("credential_required") or []
        if creds:
            parts.append(f"{speech.plural(len(creds), 'integration')} still need credentials, "
                         "like payments and email.")
        parts.append("Want me to show you the preview?" if built_ok else
                     "Want me to run the build again?")
        return VoiceReply(text=speech.join(*parts),
                          state=ResultState.SUCCESS if built_ok else ResultState.PARTIAL,
                          data={"project_id": project.id, "status": project.status,
                                "report": report.to_dict()})

    def _do_list_projects(self, session, intent, seed) -> VoiceReply:
        rows = (self.db.query(BuilderProject)
                .filter(BuilderProject.tenant_id == self.ctx.tenant_id)
                .order_by(BuilderProject.created_at.desc()).limit(10).all())
        if not rows:
            return self._no_project()
        return VoiceReply(
            text=f"You have {speech.plural(len(rows), 'project')}: "
                 f"{speech.spoken_list([p.name for p in rows])}.",
            state=ResultState.SUCCESS, data={"projects": [p.id for p in rows]})

    def _do_describe_project(self, session, intent, seed) -> VoiceReply:
        project = self._focus_project(session, intent)
        if project is None:
            return self._no_project()
        status_words = {
            "TESTED": "built and passing its tests",
            "PREVIEWED": "built, tested, and has a preview up",
            "AWAITING_DEPLOY_APPROVAL": "waiting for deployment approval",
            "BUILD_FAILED": "failing to build",
            "TEST_FAILED": "failing its tests",
        }.get(project.status, project.status.lower().replace("_", " "))
        return VoiceReply(
            text=f"{project.name} is {status_words}. It's on version {project.current_version}.",
            state=ResultState.SUCCESS, data={"project_id": project.id})

    def _do_run_build(self, session, intent, seed) -> VoiceReply:
        project = self._focus_project(session, intent)
        if project is None:
            return self._no_project()
        if (throttled := self._build_throttled()) is not None:
            return throttled
        result = self._compiler().build(project)
        if result.state.is_success:
            tests = next((s for s in result.data.get("stages", []) if s["name"] == "tests"), None)
            passed = tests and tests["state"] == "PASSED"
            return VoiceReply(
                text=f"{speech.acknowledge(seed)} {project.name} compiled cleanly, passed the "
                     f"security scan{', and every test passed' if passed else ''}.",
                state=ResultState.SUCCESS, data={"project_id": project.id})
        return VoiceReply(text=f"The build of {project.name} failed. {speech.blocked(result.detail)}",
                          state=result.state, data={"project_id": project.id})

    def _do_show_preview(self, session, intent, seed) -> VoiceReply:
        project = self._focus_project(session, intent)
        if project is None:
            return self._no_project()
        result = self._compiler().preview(project)
        if result.state.is_success:
            return VoiceReply(
                text=f"The preview for {project.name} is ready. It's a preview, not "
                     "production, and it expires in a day.",
                state=ResultState.SUCCESS, data=result.data)
        return VoiceReply(text=speech.blocked(result.detail), state=result.state)

    def _do_export_source(self, session, intent, seed) -> VoiceReply:
        project = self._focus_project(session, intent)
        if project is None:
            return self._no_project()
        return VoiceReply(
            text=f"The source for {project.name} is ready to download from the console. "
                 "It's the complete project, so you're not tied to the builder.",
            state=ResultState.SUCCESS,
            data={"project_id": project.id,
                  "download": f"/api/mo/builder/projects/{project.id}/export"})

    def _do_deploy(self, session, intent, seed) -> VoiceReply:
        project = self._focus_project(session, intent)
        if project is None:
            return self._no_project()
        environment = intent.slots.get("environment", "staging")
        result = self._compiler().request_deployment(
            project, environment, "Requested by voice")
        if result.state is ResultState.APPROVAL_REQUIRED:
            tier = result.meta.get("risk_tier", "")
            second = " two people" if tier == "CRITICAL" else " someone"
            return VoiceReply(
                text=f"I've requested a {environment} deployment of {project.name}. It "
                     f"won't go out until{second} other than you signs it off in the console.",
                state=ResultState.APPROVAL_REQUIRED, data=result.meta)
        return VoiceReply(text=speech.blocked(result.detail), state=result.state)

    def _do_cancel_deploy(self, session, intent, seed) -> VoiceReply:
        from ..approvals import engine as approvals
        project = self._focus_project(session, intent)
        if project is None:
            return self._no_project()
        pending = (self.db.query(BuilderDeployment)
                   .filter(BuilderDeployment.project_id == project.id,
                           BuilderDeployment.tenant_id == self.ctx.tenant_id,
                           BuilderDeployment.state == ResultState.APPROVAL_REQUIRED.value)
                   .all())
        if not pending:
            return VoiceReply(text=f"There's no pending deployment for {project.name}.",
                              state=ResultState.SUCCESS)
        for deployment in pending:
            deployment.state = ResultState.CANCELLED.value
            deployment.detail = "Cancelled by voice."
            if deployment.approval_id and self.ctx.is_admin:
                approvals.revoke(self.db, self.ctx, deployment.approval_id, "cancelled by voice")
        self.db.flush()
        return VoiceReply(
            text=f"Stopped. I cancelled {speech.plural(len(pending), 'pending deployment')} "
                 f"for {project.name}.",
            state=ResultState.SUCCESS)

    # ── handlers: agents, approvals, tools ───────────────────────────────────

    def _agents(self) -> list[AgentManifestRecord]:
        return (self.db.query(AgentManifestRecord)
                .filter(AgentManifestRecord.tenant_id == self.ctx.tenant_id)
                .order_by(AgentManifestRecord.created_at.desc()).all())

    def _do_list_agents(self, session, intent, seed) -> VoiceReply:
        agents = self._agents()
        if not agents:
            return VoiceReply(text="There aren't any agents yet. They're created when you "
                                   "build a project that needs them.", state=ResultState.SUCCESS)
        names = sorted({a.name for a in agents})
        ready = sum(1 for a in agents if a.status in ("READY", "DEPLOYED"))
        return VoiceReply(
            text=f"You have {speech.plural(len(names), 'agent')}: {speech.spoken_list(names)}. "
                 + (f"{speech.plural(ready, 'is', 'are')} ready." if ready else
                    "None are live yet, because no AI model is connected to test them against."),
            state=ResultState.SUCCESS)

    def _find_agent(self, name: str) -> Optional[AgentManifestRecord]:
        needle = (name or "").strip().lower()
        for agent in self._agents():
            if needle and needle in agent.name.lower():
                return agent
        return None

    def _do_agent_status(self, session, intent, seed) -> VoiceReply:
        agent = self._find_agent(intent.slots.get("agent", ""))
        if agent is None:
            return VoiceReply(text="I couldn't find that agent.", state=ResultState.FAILED)
        why = ""
        if agent.test_report_json:
            report = json.loads(agent.test_report_json)
            failed = [k.replace("_", " ") for k, v in report["checks"].items() if not v["passed"]]
            if failed:
                why = f" It failed its {speech.spoken_list(failed)} check."
        return VoiceReply(text=f"The {agent.name} is {agent.status.lower()}.{why}",
                          state=ResultState.SUCCESS)

    def _do_disable_agent(self, session, intent, seed) -> VoiceReply:
        from ..builder.agents import disable_agent
        agent = self._find_agent(intent.slots.get("agent", ""))
        if agent is None:
            return VoiceReply(text="I couldn't find that agent.", state=ResultState.FAILED)
        disable_agent(self.db, self.ctx, agent, "disabled by voice")
        return VoiceReply(text=f"Done. The {agent.name} is disabled and its kill switch is set.",
                          state=ResultState.SUCCESS)

    def _do_list_approvals(self, session, intent, seed) -> VoiceReply:
        rows = (self.db.query(ApprovalRequest)
                .filter(ApprovalRequest.tenant_id == self.ctx.tenant_id,
                        ApprovalRequest.status == "PENDING").all())
        if not rows:
            return VoiceReply(text="Nothing's waiting for approval.", state=ResultState.SUCCESS)
        actions = [r.action.split(".")[-1].replace("_", " ") for r in rows]
        return VoiceReply(
            text=f"{speech.plural(len(rows), 'request')} waiting: {speech.spoken_list(actions)}. "
                 "You'll need to approve them in the console.",
            state=ResultState.SUCCESS)

    def _do_list_tools(self, session, intent, seed) -> VoiceReply:
        from ..tools.spec import get_tool_registry
        tools = get_tool_registry().list()
        blocked = [t.name for t in tools if not t.credential_satisfied]
        return VoiceReply(
            text=f"There are {speech.plural(len(tools), 'tool')} registered. "
                 + (f"{speech.plural(len(blocked), 'needs', 'need')} credentials before "
                    "they'll work." if blocked else "All of them are ready."),
            state=ResultState.SUCCESS)


def plural_phrase(n: int, singular: str, plural_form: str) -> str:
    return f"{speech.number_words(n)} {singular if n == 1 else plural_form}"


# Slots that must be present before an intent runs. Anything else is optional
# and defaults sensibly (e.g. a project defaults to the one in focus).
_REQUIRED_SLOTS: dict[IntentName, tuple[str, ...]] = {
    IntentName.BUILD_PROJECT: ("description",),
    IntentName.DEPLOY: ("environment",),
    IntentName.DISABLE_AGENT: ("agent",),
    IntentName.AGENT_STATUS: ("agent",),
}
