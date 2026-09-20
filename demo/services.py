"""Bank servicing routes. Workflows use these HTML screens, never a task API."""
import secrets

from fastapi import Request
from fastapi.responses import RedirectResponse


def register_services(app, db, render, guard, form):
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, customer TEXT, last_four TEXT, status TEXT, revision INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS card_events (token TEXT PRIMARY KEY, reference TEXT UNIQUE, card TEXT, status TEXT)")
        conn.executemany("INSERT INTO cards(id,customer,last_four,status) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING", [
            ("DC-104", "C-104", "4104", "Active"), ("DC-205", "C-205", "4205", "Active"),
            ("DC-306", "C-306", "4306", "Active"),
        ])

    @app.get("/accounts/search")
    def search_account(request: Request, account_id: str = ""):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        with db() as conn:
            account = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return render(request, "account_results", account=account)

    @app.get("/accounts/{account_id}")
    def account_detail(request: Request, account_id: str):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        with db() as conn:
            account = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            transactions = conn.execute("SELECT * FROM transactions WHERE account=? ORDER BY posted DESC", (account_id,)).fetchall()
        return render(request, "account_detail" if account else "account_results", account=account, transactions=transactions)

    @app.get("/cards")
    def cards(request: Request, page_number: int = 1):
        page_number = max(1, min(page_number, 10000))
        blocked = guard(request)
        if blocked is not None:
            return blocked
        with db() as conn:
            cards = conn.execute("SELECT cards.*, customers.name FROM cards JOIN customers ON cards.customer=customers.id ORDER BY cards.id LIMIT 20 OFFSET ?", ((page_number-1)*20,)).fetchall()
            count = conn.execute("SELECT COUNT(*) AS count FROM cards").fetchone()["count"]
        return render(request, "cards", cards=cards, page_number=page_number, more=page_number*20 < count, listing_path="/cards")

    @app.get("/cards/search")
    def search_card(request: Request, card_id: str = ""):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        with db() as conn:
            card = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        return render(request, "card_detail", card=card)

    @app.post("/cards/review")
    async def review_card(request: Request):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        data = await form(request)
        if data is None or request.state.session["scenario"] == "permission-denied":
            return render(request, "denied")
        desired = str(data.get("status", ""))
        if desired not in {"Frozen", "Active"}:
            return render(request, "denied")
        with db() as conn:
            card = conn.execute("SELECT * FROM cards WHERE id=?", (str(data.get("card_id", "")),)).fetchone()
        if not card:
            return render(request, "card_detail", card=None)
        if card["status"] == desired:
            return render(request, "service_error", message="Card already in requested state")
        draft = {"card_id": card["id"], "status": desired, "revision": card["revision"], "token": secrets.token_urlsafe(24)}
        request.state.session["card_draft"] = draft
        return render(request, "card_review", draft=draft, card=card)

    @app.post("/cards/save")
    async def save_card(request: Request):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        data = await form(request)
        draft = request.state.session.get("card_draft")
        if data is None or not draft or request.state.session["scenario"] == "permission-denied":
            return render(request, "denied")
        with db() as conn:
            old = conn.execute("SELECT reference FROM card_events WHERE token=?", (draft["token"],)).fetchone()
            if old:
                reference = old["reference"]
            else:
                changed = conn.execute("UPDATE cards SET status=?,revision=revision+1 WHERE id=? AND revision=?", (draft["status"], draft["card_id"], draft["revision"]))
                if changed.rowcount != 1:
                    return render(request, "conflict")
                reference = "CRD-" + secrets.token_hex(6).upper()
                conn.execute("INSERT INTO card_events VALUES (?,?,?,?)", (draft["token"], reference, draft["card_id"], draft["status"]))
        return RedirectResponse(f"/cards/confirmation/{reference}", status_code=303)

    @app.get("/cards/confirmation/{reference}")
    def card_confirmation(request: Request, reference: str):
        blocked = guard(request)
        if blocked is not None:
            return blocked
        draft = request.state.session.get("card_draft")
        if not draft:
            return render(request, "denied")
        with db() as conn:
            event = conn.execute("SELECT * FROM card_events WHERE token=? AND reference=?", (draft["token"], reference)).fetchone()
        return render(request, "card_confirmation", event=event) if event else render(request, "denied")
