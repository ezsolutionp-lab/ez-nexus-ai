"""
MO NEXUS OMEGA — Browser adapter (Playwright + Chromium).

  browser.read_page   LOW-medium: open a page and return its title, visible text and links. Read-only.
  browser.submit_form HIGH (approval-gated by construction): fill fields and click a submit control.

Safety, in layers:
  * a fresh, incognito context per call: no cookies, storage or profile survive
  * only http(s); the SSRF guard checks the entry URL AND every sub-request the page makes (scripts, frames,
    images, redirects), so a page cannot pivot to an internal address
  * downloads, permissions prompts, and file:// are refused; time, request count and output size are capped
  * everything read from a page is untrusted: it is screened for prompt-injection markers and flagged, never
    executed or obeyed
  * submit_form never logs field values (they can be credentials); only field selectors are recorded

Needs the optional `playwright` package and a Chromium build (PLAYWRIGHT_BROWSERS_PATH). Without them the tools
answer PROVIDER_UNAVAILABLE.
"""

from __future__ import annotations

import glob
import os
from typing import Any, Optional
from urllib.parse import urlparse

from ..context import RequestContext
from ..errors import MoResult, ResultState
from ..guards import injection
from ..protocols.netguard import check_url
from ..tools.spec import RiskLevel, ToolRegistry, ToolSpec

MAX_TEXT = 200_000
MAX_LINKS = 200
MAX_REQUESTS = 60
NAV_TIMEOUT_MS = 20_000


def _chromium_path() -> Optional[str]:
    explicit = os.getenv("MO_BROWSER_EXECUTABLE", "").strip()
    if explicit:
        return explicit if os.path.exists(explicit) else None
    root = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    hits = sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-linux*", "chrome")))
    return hits[-1] if hits else None


def available() -> tuple[bool, str]:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, "the 'playwright' package is not installed (pip install playwright)"
    if _chromium_path() is None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                return os.path.exists(p.chromium.executable_path), "no Chromium build found (set PLAYWRIGHT_BROWSERS_PATH)"
        except Exception as exc:                                # pragma: no cover
            return False, f"Playwright could not start: {type(exc).__name__}"
    return True, ""


def _entry_problem(url: Any) -> Optional[str]:
    if not isinstance(url, str) or not url:
        return "A 'url' is required."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Only http and https pages can be opened."
    return check_url(url)


class _Session:
    """One incognito browser context with request-level SSRF enforcement."""

    def __init__(self) -> None:
        self.blocked: list[str] = []
        self.requests = 0

    def __enter__(self) -> "_Session":
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        args = ["--disable-dev-shm-usage"]
        if os.getenv("MO_BROWSER_NO_SANDBOX") == "1":
            args.append("--no-sandbox")
        exe = _chromium_path()
        self.browser = self._pw.chromium.launch(headless=True, args=args, **({"executable_path": exe} if exe else {}))
        self.context = self.browser.new_context(accept_downloads=False, java_script_enabled=True, service_workers="block",
                                                permissions=[], ignore_https_errors=False)
        self.context.route("**/*", self._route)
        self.page = self.context.new_page()
        self.page.set_default_timeout(NAV_TIMEOUT_MS)
        return self

    def _route(self, route, request) -> None:
        self.requests += 1
        url = request.url
        if self.requests > MAX_REQUESTS:
            self.blocked.append("request budget exceeded")
            return route.abort()
        if url.startswith(("data:", "blob:", "about:")):
            return route.continue_()
        problem = _entry_problem(url)
        if problem:
            self.blocked.append(f"{urlparse(url).netloc or url[:60]}: {problem}")
            return route.abort()
        route.continue_()

    def __exit__(self, *exc: Any) -> None:
        for closer in (lambda: self.context.close(), lambda: self.browser.close(), lambda: self._pw.stop()):
            try:
                closer()
            except Exception:                                    # pragma: no cover
                pass


def _open(session: _Session, url: str) -> Optional[MoResult]:
    from playwright.sync_api import Error as PwError, TimeoutError as PwTimeout
    try:
        resp = session.page.goto(url, wait_until="load")
    except PwTimeout:
        return MoResult(ResultState.TIMEOUT, f"The page did not load within {NAV_TIMEOUT_MS // 1000}s.")
    except PwError as exc:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"The page could not be opened: {str(exc).splitlines()[0][:160]}")
    if resp is not None and resp.status >= 400:
        return MoResult(ResultState.FAILED, f"The site answered HTTP {resp.status}.", data={"status": resp.status})
    return None


def _wrap(payload_text: str, **extra: Any) -> dict[str, Any]:
    verdict = injection.screen(payload_text)
    return {"injection_screen": verdict.verdict, "injection_signals": verdict.signals, **extra}


def read_page(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    url = payload.get("url")
    if (problem := _entry_problem(url)):                        # policy first: the verdict must not depend on the browser
        return MoResult(ResultState.POLICY_DENIED if problem != "A 'url' is required." else ResultState.FAILED, problem)
    ok, why = available()
    if not ok:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"Browser tools are unavailable: {why}.")
    with _Session() as s:
        if (err := _open(s, url)):
            err.meta["blocked_requests"] = s.blocked
            return err
        selector = payload.get("selector")
        text = (s.page.inner_text(selector) if selector else s.page.inner_text("body"))[:MAX_TEXT]
        links = s.page.eval_on_selector_all(
            "a[href]", "els => els.map(e => ({text: (e.innerText||'').trim().slice(0,120), href: e.href}))")[:MAX_LINKS]
        links = [l for l in links if urlparse(l["href"]).scheme in ("http", "https")]
        return MoResult.ok(
            {"url": s.page.url, "title": s.page.title(), "text": text, "links": links,
             **_wrap(text, blocked_requests=s.blocked, requests=s.requests)}, untrusted=True)


def submit_form(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    url, fields, submit = payload.get("url"), payload.get("fields") or {}, payload.get("submit_selector")
    if (problem := _entry_problem(url)):
        return MoResult(ResultState.POLICY_DENIED if problem != "A 'url' is required." else ResultState.FAILED, problem)
    if not isinstance(fields, dict) or not fields or len(fields) > 30 or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items()):
        return MoResult(ResultState.FAILED, "fields must be an object of 1-30 selector -> text entries.")
    if not isinstance(submit, str) or not submit:
        return MoResult(ResultState.FAILED, "submit_selector is required.")
    ok, why = available()
    if not ok:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"Browser tools are unavailable: {why}.")
    from playwright.sync_api import Error as PwError, TimeoutError as PwTimeout
    with _Session() as s:
        if (err := _open(s, url)):
            return err
        try:
            for selector, value in fields.items():
                s.page.fill(selector, value, timeout=5000)        # values are deliberately never logged
        except (PwTimeout, PwError) as exc:
            return MoResult(ResultState.FAILED, f"A form field could not be filled (selector not found or not editable): "
                            f"{str(exc).splitlines()[0][:120]}. Nothing was submitted.", data={"fields": sorted(fields)})
        if s.page.query_selector(submit) is None:
            return MoResult(ResultState.FAILED, "The submit control was not found. Nothing was submitted.", data={"fields": sorted(fields)})
        try:
            with s.page.expect_navigation(wait_until="load", timeout=NAV_TIMEOUT_MS):
                s.page.click(submit, timeout=5000)
        except PwTimeout:
            return MoResult(ResultState.PARTIAL, "The submit control was clicked, but no navigation followed; the outcome is unconfirmed.",
                            data={"fields": sorted(fields), "url": s.page.url})
        except PwError as exc:
            return MoResult(ResultState.FAILED, f"The form could not be submitted: {str(exc).splitlines()[0][:160]}",
                            data={"fields": sorted(fields)})
        text = s.page.inner_text("body")[:2000]
        return MoResult.ok({"submitted": True, "fields": sorted(fields), "final_url": s.page.url,
                            "title": s.page.title(), "response_excerpt": text,
                            **_wrap(text, blocked_requests=s.blocked)}, untrusted=True)


def register_browser_tools(registry: ToolRegistry) -> None:
    if registry.get("browser.read_page"):
        return
    registry.register(ToolSpec(
        name="browser.read_page", description="Open a web page in an isolated headless browser and return its text and links (read-only).",
        handler=read_page, risk_level=RiskLevel.MEDIUM, required_scopes=("browser:read",), rate_limit_per_minute=20, timeout_seconds=45,
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": {"url": {"type": "string"}, "selector": {"type": "string"}}, "required": ["url"]}))
    registry.register(ToolSpec(
        name="browser.submit_form", description="Fill and submit a web form. An external side effect, so it needs an approved grant.",
        handler=submit_form, risk_level=RiskLevel.HIGH, required_scopes=("browser:act",), rate_limit_per_minute=10, timeout_seconds=60,
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": {"url": {"type": "string"}, "fields": {"type": "object"}, "submit_selector": {"type": "string"}},
                      "required": ["url", "fields", "submit_selector"]}))
