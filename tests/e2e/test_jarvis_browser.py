"""
End to end: the real backend, the real built console, and a real Chromium — with a scripted microphone and speaker.

The browser's speech engines are replaced by small fakes (a recogniser we can feed transcripts, a synthesiser that records
what it was asked to say and which voice it used). Everything else is real: the login token, the HTTP API, the voice
engine, the database, the builder. It cannot prove how a particular microphone or voice sounds; it proves the whole
conversation loop works and behaves the way the assistant is meant to.

Skipped where Playwright, Chromium, Node or the frontend dependencies are missing (for example the CI backend job).
"""

import functools
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"
sys.path.insert(0, str(BACKEND))

try:
    from app.mo.browser.adapter import _chromium_path, available
    HAVE_BROWSER = available()[0] and _chromium_path() is not None
except Exception:                                            # pragma: no cover
    HAVE_BROWSER = False

pytestmark = [pytest.mark.slow, pytest.mark.voice,
              pytest.mark.skipif(not HAVE_BROWSER or shutil.which("npm") is None or not (FRONTEND / "node_modules").exists(),
                                 reason="needs Playwright + Chromium + npm + frontend dependencies")]

PASSWORD = "E2e-Password-12345"

INIT = """
(() => {
  window.__spoken = [];
  class FakeRec { constructor(){ window.__rec = this; } start(){ this.on = true } stop(){ this.on = false; this.onend && this.onend() } abort(){} }
  window.SpeechRecognition = FakeRec; window.webkitSpeechRecognition = FakeRec;
  window.__say = (text) => { const res = [{transcript: text}]; res.isFinal = true; window.__rec.onresult({resultIndex: 0, results: [res]}); };
  const synth = { speaking:false,
    getVoices(){ return [{name:'Samantha',lang:'en-US',localService:true},{name:'Daniel',lang:'en-GB',localService:true}] },
    speak(u){ window.__spoken.push({text:u.text, voice:u.voice && u.voice.name, rate:u.rate, pitch:u.pitch}); this.speaking = true;
              u.onstart && u.onstart(); setTimeout(() => { this.speaking = false; u.onend && u.onend() }, 30) },
    cancel(){ this.speaking = false }, addEventListener(){} };
  Object.defineProperty(window, 'speechSynthesis', {value: synth});
  window.SpeechSynthesisUtterance = function(text){ this.text = text };
  Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: () => Promise.reject(new Error('no microphone'))}});
})();
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"{url} never came up")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    work = tmp_path_factory.mktemp("e2e")
    api_port, web_port = _free_port(), _free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{work / 'e2e.db'}", "SECRET_KEY": "e2e-secret-key-0123456789-0123456789-abcdef",
           "DEFAULT_ADMIN_PASSWORD": PASSWORD, "INITIAL_ADMIN_PASSWORD_FILE": str(work / ".pw"),
           "MO_BUILDER_WORKSPACE": str(work / "ws")}
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        env.pop(var, None)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(api_port)], cwd=BACKEND, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dist = work / "dist"
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(dist), "--emptyOutDir"], cwd=FRONTEND, check=True, capture_output=True,
                   env={**os.environ, "VITE_API_URL": f"http://127.0.0.1:{api_port}"})
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    handler.log_message = lambda *a, **k: None
    web = http.server.ThreadingHTTPServer(("127.0.0.1", web_port), handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        _wait_http(f"http://127.0.0.1:{api_port}/")
        form = urllib.parse.urlencode({"username": "ez.nexusai@gmail.com", "password": PASSWORD}).encode()
        login = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{api_port}/auth/login", data=form)))
        yield {"api": f"http://127.0.0.1:{api_port}", "web": f"http://127.0.0.1:{web_port}", "login": login}
    finally:
        web.shutdown()
        api.terminate()
        try:
            api.wait(10)
        except subprocess.TimeoutExpired:
            api.kill()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=_chromium_path(), args=["--no-sandbox"])
        yield b
        b.close()


def open_console(browser, stack, *, prefs=None, tz="America/New_York"):
    ctx = browser.new_context(timezone_id=tz)
    ctx.add_init_script(INIT)
    login = stack["login"]
    ctx.add_init_script(f"localStorage.setItem('ez_token', {json.dumps(login['access_token'])});"
                        f"localStorage.setItem('ez_user', {json.dumps(json.dumps(login['user']))});"
                        + (f"localStorage.setItem('jv_prefs', {json.dumps(json.dumps(prefs))});" if prefs else ""))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(stack["web"])
    page.get_by_text("Talk to MO").first.click()
    page.wait_for_selector(".jv-orb")
    time.sleep(1.2)                                            # the session request
    page.click(".jv-orb")
    page.errors = errors
    return page


def say(page, text, wait=1.0):
    page.evaluate("t => window.__say(t)", text)
    time.sleep(wait)


def spoken(page):
    return page.evaluate("window.__spoken")


def wait_spoken(page, n, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if len(spoken(page)) >= n:
            return spoken(page)
        time.sleep(0.1)
    raise AssertionError(f"expected {n} spoken replies, got {spoken(page)}")


def test_a_full_jarvis_conversation(browser, stack):
    page = open_console(browser, stack)
    say(page, "just some background chatter about lunch")
    assert spoken(page) == []                                    # asleep: ambient speech is ignored, silently

    say(page, "Jarvis")
    first = wait_spoken(page, 1)[0]
    assert first["text"].startswith(("Good evening, boss.", "Good morning, boss.", "Good afternoon, boss."))
    assert "All systems are running normally" in first["text"]
    assert first["voice"] == "Daniel" and first["rate"] < 1.0 and first["pitch"] < 1.0      # the calm British male, a touch lower

    say(page, "run diagnostics")
    diag = wait_spoken(page, 2)[1]["text"]
    assert diag.startswith("Diagnostics complete.") and "No language model is connected" in diag

    say(page, "what time is it")
    assert ", boss." in wait_spoken(page, 3)[2]["text"] and " in the " in spoken(page)[2]["text"]

    say(page, "build me a booking website for a plumber", wait=1)
    built = wait_spoken(page, 4, timeout=60)[3]["text"]
    assert "Shall I bring up the preview, boss?" in built and "compiled" in built
    say(page, "yes please")
    preview = wait_spoken(page, 5)[4]["text"]
    assert "preview" in preview.lower() and "not production" in preview

    say(page, "approve the deployment")
    assert wait_spoken(page, 6)[5]["text"].startswith("I'm afraid I can't do that by voice, boss.")   # governance unchanged

    say(page, "thank you")
    say(page, "that will be all")
    n = len(wait_spoken(page, 8))
    say(page, "what time is it")                                                                      # asleep again
    assert len(spoken(page)) == n
    assert page.errors == []
    assert "Standing by" in page.inner_text(".jv-log") or "Very well" in page.inner_text(".jv-log") or "Understood" in page.inner_text(".jv-log")


def test_utterances_that_arrive_together_are_all_answered(browser, stack):
    page = open_console(browser, stack)
    say(page, "Jarvis")
    wait_spoken(page, 1)
    page.evaluate("() => { window.__say('what time is it'); window.__say('what is the date today'); window.__say('run diagnostics'); }")
    replies = wait_spoken(page, 4)
    texts = " | ".join(r["text"] for r in replies[1:])
    assert " in the " in texts and "September" in texts and "Diagnostics complete" in texts     # none was dropped


def test_the_users_form_of_address_and_voice_are_honoured(browser, stack):
    page = open_console(browser, stack, prefs={"address": "sir", "voice": "Samantha", "rate": 1.1, "pitch": 1.0})
    say(page, "hey Jarvis")
    reply = wait_spoken(page, 1)[0]
    assert reply["text"].startswith(("Good evening, sir.", "Good morning, sir.", "Good afternoon, sir."))
    assert reply["voice"] == "Samantha" and reply["rate"] == 1.1


def test_typed_commands_use_the_same_persona(browser, stack):
    page = open_console(browser, stack)
    page.fill(".jv-type input", "Jarvis")
    page.press(".jv-type input", "Enter")
    assert ", boss." in wait_spoken(page, 1)[0]["text"]
    page.fill(".jv-type input", "who are you")
    page.press(".jv-type input", "Enter")
    who = wait_spoken(page, 2)[1]["text"]
    assert "I'm MO" in who and "software" in who
