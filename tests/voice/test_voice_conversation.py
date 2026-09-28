"""The conversation engine: waking, follow-ups, memory, and governance."""

from datetime import datetime, timedelta

import pytest

from app.mo.context import RequestContext
from app.mo.db import AuditEvent, BuilderProject, Tenant, VoiceTurn
from app.mo.errors import MoError, ResultState
from app.mo.voice.engine import VoiceEngine

pytestmark = pytest.mark.voice


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 28, 10, 0, 0)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tenant(db, tenant_a):
    db.add(Tenant(id=tenant_a, slug=tenant_a, name="Voice Test Tenant"))
    db.flush()
    return tenant_a


@pytest.fixture
def owner(tenant):
    return RequestContext(tenant_id=tenant, actor_id="owner", is_admin=True,
                          mfa_verified=True, scopes=frozenset({"*"}))


@pytest.fixture
def mo(db, owner, workspace_root, clock):
    engine = VoiceEngine(db, owner, workspace_root=workspace_root, clock=clock)
    return engine, engine.start_session()


def talk(mo, clock, text, seconds=2):
    engine, session = mo
    clock.advance(seconds)
    return engine.handle(session, text)


# ── Waking and sleeping ─────────────────────────────────────────────────────

def test_ambient_speech_is_ignored_while_asleep(mo, clock):
    r = talk(mo, clock, "so I told my brother about the game")
    assert r["reply"] == "" and r["awake"] is False


def test_calling_the_name_wakes_mo_and_it_answers(mo, clock):
    r = talk(mo, clock, "MO")
    assert r["awake"] is True
    assert r["reply"]
    assert r["speak"]["directive"] == "speak"


def test_follow_ups_do_not_need_the_name_inside_the_window(mo, clock):
    talk(mo, clock, "MO")
    r = talk(mo, clock, "list my projects", seconds=10)
    assert r["intent"]["intent"] == "builder.list_projects"


def test_mo_goes_back_to_sleep_when_the_window_expires(mo, clock):
    talk(mo, clock, "MO")
    r = talk(mo, clock, "list my projects", seconds=31)
    assert r["reply"] == "" and r["awake"] is False


def test_each_reply_extends_the_window(mo, clock):
    talk(mo, clock, "MO")
    talk(mo, clock, "list my projects", seconds=25)
    r = talk(mo, clock, "what needs approval", seconds=25)     # 50s after waking
    assert r["intent"]["intent"] == "approval.list"


def test_wake_and_command_in_one_breath(mo, clock):
    r = talk(mo, clock, "hey MO, list my projects")
    assert r["intent"]["intent"] == "builder.list_projects"


@pytest.mark.security
def test_never_mind_stops_mo_listening_immediately(mo, clock):
    """'Never mind' must end the window, or MO acts on whatever is said next."""
    talk(mo, clock, "MO")
    r = talk(mo, clock, "never mind")
    assert r["awake"] is False
    after = talk(mo, clock, "enable safe mode", seconds=2)
    assert after["reply"] == ""
    assert after["intent"] is None


# ── Conversation memory ─────────────────────────────────────────────────────

def test_mo_asks_for_a_missing_detail_and_remembers_the_question(mo, clock, db):
    talk(mo, clock, "MO, build a booking website for a dentist")
    ask = talk(mo, clock, "deploy it")
    assert ask["expecting"] == "environment"
    assert "staging or production" in ask["reply"].lower()
    done = talk(mo, clock, "staging please")
    assert done["state"] == ResultState.APPROVAL_REQUIRED.value
    assert "staging" in done["reply"]


def test_a_follow_up_question_can_be_abandoned(mo, clock):
    talk(mo, clock, "MO")
    talk(mo, clock, "deploy it")
    r = talk(mo, clock, "never mind")
    assert r["state"] == ResultState.CANCELLED.value


def test_an_unclear_answer_gets_the_question_again(mo, clock):
    talk(mo, clock, "MO, build a booking website for a dentist")
    talk(mo, clock, "deploy it")
    r = talk(mo, clock, "purple")
    assert r["expecting"] == "environment"


def test_it_refers_to_the_project_just_discussed(mo, clock, db):
    built = talk(mo, clock, "MO, build a booking website for a plumber")
    project_id = built["data"]["project_id"]
    preview = talk(mo, clock, "show me the preview")
    assert preview["state"] == ResultState.SUCCESS.value
    assert preview["data"]["preview_id"]
    engine, session = mo
    assert session.focus_project_id == project_id


def test_repeat_returns_the_last_reply(mo, clock):
    talk(mo, clock, "MO")
    first = talk(mo, clock, "list my projects")
    again = talk(mo, clock, "repeat that")
    assert again["reply"] == first["reply"]


def test_building_by_voice_creates_a_real_project(mo, clock, db):
    r = talk(mo, clock, "MO, build a website for a plumbing company with online booking")
    project = db.get(BuilderProject, r["data"]["project_id"])
    assert project.name == "Plumbing Company Website"
    assert project.source_channel == "VOICE"
    assert project.status == "TESTED"
    assert "passed" in r["reply"]


# ── Governance: voice never gets more authority than the token ──────────────

@pytest.mark.security
def test_approving_by_voice_is_refused_even_for_an_admin(mo, clock):
    r = talk(mo, clock, "MO, approve the deployment")
    assert r["state"] == ResultState.POLICY_DENIED.value
    assert "by voice" in r["reply"]


@pytest.mark.security
def test_voice_deploy_is_approval_gated_and_never_deploys(mo, clock, db):
    talk(mo, clock, "MO, build a booking website for a dentist")
    r = talk(mo, clock, "deploy to production")
    assert r["state"] == ResultState.APPROVAL_REQUIRED.value
    assert r["data"]["risk_tier"] == "CRITICAL"
    assert "two people" in r["reply"]


@pytest.mark.security
def test_a_non_admin_cannot_trigger_safe_mode_by_voice(db, tenant, workspace_root, clock):
    staff = RequestContext(tenant_id=tenant, actor_id="staff", is_admin=False,
                           mfa_verified=True, scopes=frozenset({"builder:read", "builder:write"}))
    engine = VoiceEngine(db, staff, workspace_root=workspace_root, clock=clock)
    session = engine.start_session()
    r = engine.handle(session, "MO, enable safe mode")
    assert r["state"] == ResultState.POLICY_DENIED.value
    assert db.get(Tenant, tenant).safe_mode is False


@pytest.mark.security
def test_high_risk_voice_actions_need_an_mfa_session(db, tenant, workspace_root, clock):
    no_mfa = RequestContext(tenant_id=tenant, actor_id="owner", is_admin=True,
                            mfa_verified=False, scopes=frozenset({"*"}))
    engine = VoiceEngine(db, no_mfa, workspace_root=workspace_root, clock=clock)
    session = engine.start_session()
    r = engine.handle(session, "MO, enable safe mode")
    assert r["state"] == ResultState.POLICY_DENIED.value
    assert "two-factor" in r["reply"]


def test_safe_mode_kill_switch_works_by_voice(mo, clock, db, tenant):
    r = talk(mo, clock, "MO, emergency stop")
    assert r["state"] == ResultState.SUCCESS.value
    assert db.get(Tenant, tenant).safe_mode is True


def test_lifting_safe_mode_by_voice_only_requests_approval(mo, clock, db, tenant):
    talk(mo, clock, "MO, emergency stop")
    r = talk(mo, clock, "disable safe mode")
    assert r["state"] == ResultState.APPROVAL_REQUIRED.value
    assert db.get(Tenant, tenant).safe_mode is True


# ── Isolation and audit ─────────────────────────────────────────────────────

@pytest.mark.security
def test_another_user_cannot_continue_your_conversation(db, mo, tenant, workspace_root):
    _, session = mo
    colleague = RequestContext(tenant_id=tenant, actor_id="colleague", is_admin=True,
                               mfa_verified=True, scopes=frozenset({"*"}))
    with pytest.raises(MoError) as exc:
        VoiceEngine(db, colleague, workspace_root=workspace_root).load_session(session.id)
    assert exc.value.state is ResultState.POLICY_DENIED


@pytest.mark.security
def test_another_tenant_cannot_reach_your_conversation(db, mo, tenant_b, workspace_root):
    _, session = mo
    outsider = RequestContext(tenant_id=tenant_b, actor_id="owner", is_admin=True,
                              mfa_verified=True, scopes=frozenset({"*"}))
    with pytest.raises(MoError):
        VoiceEngine(db, outsider, workspace_root=workspace_root).load_session(session.id)


def test_every_turn_is_persisted(mo, clock, db):
    talk(mo, clock, "MO")
    talk(mo, clock, "list my projects")
    _, session = mo
    turns = db.query(VoiceTurn).filter(VoiceTurn.session_id == session.id).all()
    assert [t.seq for t in turns] == [1, 2]
    assert turns[0].wake_detected is True


def test_every_turn_is_audited_on_the_voice_channel(mo, clock, db, tenant):
    talk(mo, clock, "MO, list my projects")
    events = db.query(AuditEvent).filter(AuditEvent.tenant_id == tenant,
                                         AuditEvent.action == "voice.turn").all()
    assert events
    assert all(e.source_channel == "VOICE" for e in events)


def test_an_ended_session_cannot_be_resumed(mo, db):
    engine, session = mo
    engine.end_session(session)
    with pytest.raises(MoError) as exc:
        engine.load_session(session.id)
    assert exc.value.state is ResultState.BLOCKED
