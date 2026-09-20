"""Browser-specific perception and interaction; no workflow sequence lives here."""
import re
import uuid
from typing import Protocol

from playwright.sync_api import sync_playwright

from engine.contracts import Action, Target
from engine.safety import PolicyError


class Surface(Protocol):
    owner: str
    session_id: str
    write_authorized: bool
    risky_authorized: bool
    def open(self, entry: str) -> None: ...
    def assert_policy(self) -> None: ...
    def has_alert(self, text: str) -> bool: ...
    def read_values(self, observation: dict) -> dict: ...
    def snapshot(self) -> None: ...
    def close(self) -> None: ...
    def observe(self) -> dict: ...
    def execute(self, action: Action, inputs: dict[str, str]) -> str | None: ...
    def visible(self, target: Target) -> bool: ...
    def frame(self) -> bytes: ...
    def pump_events(self) -> None: ...
    def operator_action(self, command: dict) -> None: ...


class BrowserSurface:
    def __init__(self, policy, evidence, headed=False):
        self.policy, self.evidence = policy, evidence
        self.owner = "automation"
        self.session_id = str(uuid.uuid4())
        self.document_id = 0
        self.blocked = None
        self.write_authorized = False
        self.risky_authorized = False
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=not headed)
        self.context = self.browser.new_context(service_workers="block", accept_downloads=False)
        self.context.route("**/*", self._route)
        self.context.expose_binding("recordHuman", self._human_event)
        self.context.add_init_script("""(() => {
          for (const kind of ['click','change']) document.addEventListener(kind, e => {
            if (!e.isTrusted) return;
            const t=e.target;
            const sensitive=t.closest('[data-sensitive]') || t.matches('input,textarea');
            const label=sensitive?'[REDACTED]':(t.matches('button,a')?(t.innerText||'').slice(0,100):'[control]');
            window.recordHuman({kind, tag:t.tagName, label});
          }, true);
        })();""")
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.page.on("dialog", self._dialog)
        self.page.on("framenavigated", self._navigated)
        self.page.on("framenavigated", lambda frame: self.evidence.event("human_navigation", session_id=self.session_id) if self.owner == "human" else None)

    def _navigated(self, frame):
        if frame == self.page.main_frame:
            self.document_id += 1

    def _dialog(self, dialog):
        self.blocked = "Unexpected browser dialog"
        dialog.dismiss()

    def _human_event(self, source, event):
        if self.owner == "human":
            self.evidence.event("human_action", action=event)

    def _route(self, route):
        request = route.request
        try:
            self.policy.url(request.url)
            if request.method not in ("GET", "HEAD") and self.owner == "automation":
                from urllib.parse import urlsplit
                path = urlsplit(request.url).path
                if not any(re.fullmatch(p, path) for p in self.policy.profile.automated_post_routes) or not self.write_authorized:
                    raise PolicyError("Unapproved state-changing request")
                if any(re.fullmatch(p, path) for p in self.policy.profile.risky_post_routes) and not self.risky_authorized:
                    raise PolicyError("Risky request lacks explicit authorization")
            route.continue_()
        except PolicyError as exc:
            self.blocked = str(exc)
            route.abort()

    def open(self, url):
        self.policy.url(url)
        self.page.goto(url)
        self.assert_policy()

    def assert_policy(self):
        if self.blocked:
            raise PolicyError(self.blocked)
        self.policy.url(self.page.url)

    def target(self, target: Target):
        if target.by == "role":
            return self.page.get_by_role(target.role, name=target.name, exact=True)
        if target.by == "label":
            return self.page.get_by_label(target.name, exact=True)
        return self.page.get_by_text(target.name, exact=True)

    def visible(self, target):
        locator = self.target(target)
        return locator.count() == 1 and locator.is_visible()

    def has_alert(self, text):
        locator = self.page.get_by_role("alert").filter(has_text=re.compile("^" + re.escape(text) + "$"))
        return locator.count() == 1 and locator.is_visible()

    def observe(self, check_policy=True):
        if check_policy:
            self.assert_policy()
        # Work only from visible content; never return hidden fields or form values.
        state = self.page.evaluate("""() => {
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const copy=document.body.cloneNode(true);
          copy.querySelectorAll('script,style,input[type=hidden]').forEach(e=>e.remove());
          copy.querySelectorAll('[data-sensitive]').forEach(e=>{e.textContent='[REDACTED]';e.removeAttribute('value')});
          copy.querySelectorAll('input,textarea').forEach(e=>{e.removeAttribute('value');e.textContent=''});
          const controls=[...document.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,h1')].filter(visible).map(e=>({
            role:e.tagName==='A'?'link':e.tagName==='BUTTON'?'button':e.tagName==='H1'?'heading':'textbox',
            name:e.labels?.[0]?.textContent.trim() || e.getAttribute('aria-label') || (['INPUT','TEXTAREA','SELECT'].includes(e.tagName)?'':e.textContent.trim()),
            readonly:!!e.readOnly, filled:!!e.value, pattern:e.getAttribute('pattern'),
            required:!!e.required, form:e.form?[...document.forms].indexOf(e.form):null
          }));
          return {text:copy.textContent.replace(/\\s+/g,' ').trim(),controls,
            app:document.querySelector('meta[name=application-name]')?.content,
            app_version:document.querySelector('meta[name=application-version]')?.content};
        }""")
        state["document_id"] = self.document_id
        return self.evidence.clean(state)

    def read_values(self, observation):
        # Local contract validation only. Never include these values in model observations.
        return {c["name"]: self.target(Target(by="label", name=c["name"])).input_value()
                for c in observation["controls"] if c["role"] == "textbox" and c["readonly"]}

    def execute(self, action, inputs):
        if self.owner != "automation":
            raise PolicyError("Automation does not own this session")
        self.policy.action(action)
        self.assert_policy()
        locator = self.target(action.target)
        locator.first.wait_for(state="visible")
        if locator.count() != 1:
            raise PolicyError("Target is ambiguous")
        if action.kind == "click":
            locator.click()
        elif action.kind == "fill":
            locator.fill(inputs[action.input_key])
        elif action.kind == "read":
            return locator.input_value() if locator.evaluate("e=>['INPUT','TEXTAREA','SELECT'].includes(e.tagName)") else locator.inner_text()
        self.assert_policy()
        return None

    def snapshot(self):
        # Structural DOM evidence excludes form values, hidden controls, scripts, and sensitive nodes.
        structure = self.page.evaluate("""() => {
          const visit=e=>{
            if(e.nodeType===3) return e.textContent.trim();
            if(e.nodeType!==1 || ['SCRIPT','STYLE'].includes(e.tagName) || e.type==='hidden') return null;
            if(e.hasAttribute('data-sensitive') || ['INPUT','TEXTAREA','SELECT'].includes(e.tagName)) return {tag:e.tagName,text:'[REDACTED]'};
            return {tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),
              children:[...e.childNodes].map(visit).filter(Boolean)};
          }; return visit(document.body);
        }""")
        self.evidence.save("failure-snapshot.json", {"observation": self.observe(check_policy=False), "dom": structure})

    def frame(self):
        return self.page.screenshot(type="jpeg", quality=75, timeout=15000)

    def pump_events(self):
        self.page.wait_for_timeout(100)

    def operator_action(self, command):
        if self.owner != "human":
            raise PolicyError("Human does not own this session")
        kind = command["kind"]
        if kind == "click":
            x, y = float(command["x"]), float(command["y"])
            viewport = self.page.viewport_size
            if not (0 <= x < viewport["width"] and 0 <= y < viewport["height"]):
                raise PolicyError("Operator click outside viewport")
            self.page.mouse.click(x, y)
        elif kind == "type":
            self.page.keyboard.insert_text(str(command["text"])[:1000])
        elif kind == "key" and command.get("key") in ("Tab", "Enter", "Escape", "Backspace"):
            self.page.keyboard.press(command["key"])
        elif kind == "scroll":
            self.page.mouse.wheel(0, max(-1000, min(1000, int(command["delta"]))))
        else:
            raise PolicyError("Unsupported operator action")

    def close(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()
