"""Server-rendered UI. All records are synthetic; no automation task API."""
import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from demo.database import connect


def create_app(database: str | Path | None = None, scenario: str | None = None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    database = database or os.getenv("DEMO_DATABASE_URL") or os.getenv("DEMO_DATABASE", "work/customers.sqlite3")
    fault = scenario or os.getenv("DEMO_SCENARIO", "normal")
    if fault not in {"normal", "slow", "transient", "session-expired", "permission-denied", "uncertain-save"}:
        raise ValueError("Unknown demo scenario")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    sessions: dict[str, dict] = {}

    def db():
        return connect(database)

    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, name TEXT, street TEXT, city TEXT, postal TEXT, revision INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS updates (token TEXT PRIMARY KEY, customer TEXT, reference TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, customer TEXT, kind TEXT, balance INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, account TEXT, description TEXT, amount INTEGER, posted TEXT)")
        conn.executemany("INSERT INTO customers(id,name,street,city,postal) VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING", [
            ("C-104", "Alex Example", "10 Sample Lane", "Exampleton", "10001"),
            ("C-205", "Jordan Sample", "20 Demo Road", "Testville", "20002"),
            ("C-306", "Casey Demo", "30 Cedar Way", "Sampleton", "30003"),
        ])
        conn.executemany("INSERT INTO accounts VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING", [
            ("AC-4104", "C-104", "Everyday checking", 824550), ("AC-5104", "C-104", "Savings", 1523000),
            ("AC-4205", "C-205", "Everyday checking", 420075), ("AC-4306", "C-306", "Savings", 960000),
        ])
        conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING", [
            ("TX-101", "AC-4104", "Synthetic payroll deposit", 250000, "2026-09-18"),
            ("TX-102", "AC-4104", "Sample grocery purchase", -8245, "2026-09-18"),
            ("TX-103", "AC-4205", "Demo utility payment", -12500, "2026-09-17"),
            ("TX-104", "AC-4306", "Synthetic savings deposit", 100000, "2026-09-16"),
        ])

    @app.middleware("http")
    async def session(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        sid = request.cookies.get("demo_session", "")
        if sid not in sessions:
            sid = secrets.token_urlsafe(24)
            sessions[sid] = {"csrf": secrets.token_urlsafe(24), "restored": False, "draft": None, "transient": False, "scenario": fault}
        if request.url.path == "/" and request.query_params.get("scenario") in {"normal", "slow", "transient", "session-expired", "permission-denied", "uncertain-save"}:
            sessions[sid]["scenario"] = request.query_params["scenario"]
        request.state.session = sessions[sid]
        response = await call_next(request)
        response.set_cookie("demo_session", sid, httponly=True, samesite="strict")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
        return response

    def render(request, page, **context):
        return templates.TemplateResponse(request=request, name="page.html", context={
            "page": page, "csrf": request.state.session["csrf"], "scenario": request.state.session["scenario"], **context,
        })

    def guard(request):
        if request.state.session["scenario"] == "session-expired" and not request.state.session["restored"]:
            return render(request, "expired")
        return None

    async def form(request):
        data = await request.form()
        if not secrets.compare_digest(str(data.get("csrf", "")), request.state.session["csrf"]):
            return None
        return data

    @app.get("/")
    def home(request: Request):
        with db() as conn:
            directory = conn.execute("SELECT id,name FROM customers ORDER BY id").fetchall()
            total = conn.execute("SELECT SUM(balance) AS balance FROM accounts").fetchone()["balance"]
            account_count = conn.execute("SELECT COUNT(*) AS count FROM accounts").fetchone()["count"]
        return render(request, "home", directory=directory, total=total, account_count=account_count)

    @app.get("/accounts")
    def accounts(request: Request):
        with db() as conn:
            records = conn.execute("SELECT accounts.*,customers.name FROM accounts JOIN customers ON customer=customers.id ORDER BY accounts.id").fetchall()
        return render(request, "accounts", accounts=records)

    @app.get("/activity")
    def activity(request: Request):
        with db() as conn:
            records = conn.execute("SELECT * FROM transactions ORDER BY posted DESC").fetchall()
        return render(request, "activity", transactions=records)

    @app.get("/health")
    def health():
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ready"}

    @app.get("/customers")
    def customers(request: Request, customer_id: str = ""):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        if request.state.session["scenario"] == "slow":
            time.sleep(1)
        if request.state.session["scenario"] == "transient" and not request.state.session["transient"]:
            request.state.session["transient"] = True
            return render(request, "transient", customer_id=customer_id)
        with db() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return render(request, "results", customer=customer)

    @app.get("/customers/{customer_id}")
    def detail(request: Request, customer_id: str):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        with db() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return render(request, "detail" if customer else "results", customer=customer)

    @app.get("/customers/{customer_id}/edit")
    def edit(request: Request, customer_id: str):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        if request.state.session["scenario"] == "permission-denied":
            return render(request, "denied")
        with db() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return render(request, "edit" if customer else "results", customer=customer)

    @app.post("/customers/{customer_id}/review")
    async def review(request: Request, customer_id: str):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        data = await form(request)
        if data is None:
            return render(request, "denied")
        with db() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            return render(request, "results", customer=None)
        if request.state.session["scenario"] == "permission-denied":
            return render(request, "denied")
        address = {k: str(data.get(k, "")).strip() for k in ("street", "city", "postal")}
        if not all(address.values()) or len(address["postal"]) != 5 or not address["postal"].isascii() or not address["postal"].isdigit():
            return render(request, "invalid")
        draft = {**address, "customer_id": customer_id, "revision": customer["revision"], "token": secrets.token_urlsafe(24)}
        request.state.session["draft"] = draft
        return render(request, "review", draft=draft)

    @app.post("/save")
    async def save(request: Request):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        data = await form(request)
        draft = request.state.session["draft"]
        if data is None or not draft or request.state.session["scenario"] == "permission-denied":
            return render(request, "denied")
        with db() as conn:
            old = conn.execute("SELECT reference FROM updates WHERE token=?", (draft["token"],)).fetchone()
            if old:
                reference = old["reference"]
            else:
                updated = conn.execute("UPDATE customers SET street=?,city=?,postal=?,revision=revision+1 WHERE id=? AND revision=?", (draft["street"], draft["city"], draft["postal"], draft["customer_id"], draft["revision"]))
                if updated.rowcount != 1:
                    return render(request, "conflict")
                reference = "UPD-" + secrets.token_hex(6).upper()
                conn.execute("INSERT INTO updates VALUES (?,?,?)", (draft["token"], draft["customer_id"], reference))
        if request.state.session["scenario"] == "uncertain-save" and not request.state.session.get("save_interrupted"):
            request.state.session["save_interrupted"] = True
            return render(request, "uncertain", reference=reference)
        return RedirectResponse(f"/confirmation/{reference}", status_code=303)

    @app.get("/confirmation/{reference}")
    def confirmation(request: Request, reference: str):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        draft = request.state.session["draft"]
        if not draft:
            return render(request, "denied")
        with db() as conn:
            record = conn.execute("SELECT * FROM updates WHERE reference=? AND token=?", (reference, draft["token"])).fetchone()
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (draft["customer_id"],)).fetchone()
        if not record:
            return render(request, "results", customer=None)
        return render(request, "confirmation", reference=reference, customer=customer)

    @app.post("/restore")
    async def restore(request: Request):
        if await form(request) is None:
            return render(request, "denied")
        request.state.session["restored"] = True
        return RedirectResponse("/", status_code=303)

    return app
