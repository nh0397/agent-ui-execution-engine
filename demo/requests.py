"""Service-request intake and tracking in the existing synthetic bank."""
import secrets
from datetime import datetime, timezone
from fastapi import Request
from fastapi.responses import RedirectResponse

KINDS = {
    'statement': ('Statement copy', 'Account ID', 'accounts', 'AC-[0-9]+'),
    'replacement': ('Card replacement', 'Card ID', 'cards', 'DC-[0-9]+'),
    'dispute': ('Transaction dispute', 'Transaction ID', 'transactions', 'TX-[0-9]+'),
}
TRANSITIONS = {'New': 'In review', 'In review': 'Resolved'}

def register_requests(app, db, render, guard, form):
    def now():
        return datetime.now(timezone.utc).isoformat(timespec='seconds')

    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS service_requests (id TEXT PRIMARY KEY, token TEXT UNIQUE, customer TEXT, kind TEXT, resource TEXT, notes TEXT, status TEXT, revision INTEGER DEFAULT 0, created TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS request_events (id TEXT PRIMARY KEY, request_id TEXT, status TEXT, note TEXT, created TEXT)")
        for reference,customer,kind,resource,notes in [
            ('REQ-DEMO01','C-104','statement','AC-4104','Sample request: September statement copy.'),
            ('REQ-DEMO02','C-205','replacement','DC-205','Sample request: damaged debit card.'),
            ('REQ-DEMO03','C-104','dispute','TX-102','Sample request: customer questions grocery charge.'),
        ]:
            inserted = conn.execute("INSERT INTO service_requests VALUES (?,?,?,?,?,?,?,0,?) ON CONFLICT(id) DO NOTHING", (reference,reference,customer,kind,resource,notes,'New',now()))
            if inserted.rowcount:
                conn.execute("INSERT INTO request_events VALUES (?,?,?,?,?)", (secrets.token_hex(16),reference,'New','Seeded synthetic example',now()))

    def failure(request, message):
        return render(request, 'service_error', message=message)

    def owned(conn, customer, kind, resource):
        if kind == 'dispute':
            return conn.execute("SELECT transactions.id FROM transactions JOIN accounts ON transactions.account=accounts.id WHERE transactions.id=? AND accounts.customer=?", (resource,customer)).fetchone()
        table = KINDS[kind][2]  # Fixed application constants, never user SQL.
        return conn.execute(f"SELECT id FROM {table} WHERE id=? AND customer=?", (resource,customer)).fetchone()

    @app.get('/requests')
    def listing(request: Request, customer_id: str = '', status: str = '', page_number: int = 1):
        blocked = guard(request)
        if blocked is not None: return blocked
        page_number = max(1,min(10000,page_number))
        if status and status not in {'New','In review','Resolved'}:
            return failure(request,'Unknown request status')
        with db() as conn:
            rows = conn.execute("SELECT * FROM service_requests WHERE (?='' OR customer=?) AND (?='' OR status=?) ORDER BY created DESC,id DESC LIMIT 21 OFFSET ?", (customer_id,customer_id,status,status,(page_number-1)*20)).fetchall()
        return render(request,'request_list',requests=rows[:20],has_more=len(rows)>20,page_number=page_number,customer_filter=customer_id,status_filter=status,kinds=KINDS)

    @app.get('/requests/new/{kind}')
    def new(request: Request, kind: str, customer_id: str = ''):
        blocked = guard(request)
        if blocked is not None: return blocked
        if kind not in KINDS: return failure(request,'Unknown request type')
        return render(request,'request_new',kind=kind,kind_info=KINDS[kind],customer_id=customer_id)

    @app.post('/requests/review/{kind}')
    async def review(request: Request, kind: str):
        blocked = guard(request)
        if blocked is not None: return blocked
        data = await form(request)
        if data is None or request.state.session['scenario']=='permission-denied': return render(request,'denied')
        request.state.session.pop('request_draft',None)
        if kind not in KINDS: return failure(request,'Unknown request type')
        customer, resource, notes = (str(data.get(k,'')).strip() for k in ('customer_id','resource_id','notes'))
        if not 5 <= len(notes) <= 500: return failure(request,'Describe the request using 5 to 500 characters')
        with db() as conn:
            if not conn.execute('SELECT id FROM customers WHERE id=?',(customer,)).fetchone(): return failure(request,'Customer not found')
            if not owned(conn,customer,kind,resource): return failure(request,'The selected item does not belong to this customer')
        draft = dict(customer=customer,kind=kind,resource=resource,notes=notes,token=secrets.token_hex(16),reference='REQ-'+secrets.token_hex(6).upper())
        request.state.session['request_draft']=draft
        return render(request,'request_review',draft=draft,kind_info=KINDS[kind])

    @app.post('/requests/submit')
    async def submit(request: Request):
        blocked = guard(request)
        if blocked is not None: return blocked
        data=await form(request)
        draft=request.state.session.get('request_draft')
        if data is None or not draft or request.state.session['scenario']=='permission-denied': return render(request,'denied')
        if not secrets.compare_digest(str(data.get('token','')),draft['token']): return failure(request,'Review expired; review the request again')
        with db() as conn:
            if not owned(conn,draft['customer'],draft['kind'],draft['resource']): return failure(request,'The selected item does not belong to this customer')
            inserted=conn.execute("INSERT INTO service_requests VALUES (?,?,?,?,?,?,?,0,?) ON CONFLICT(token) DO NOTHING",(draft['reference'],draft['token'],draft['customer'],draft['kind'],draft['resource'],draft['notes'],'New',now()))
            if inserted.rowcount:
                conn.execute('INSERT INTO request_events VALUES (?,?,?,?,?)',(secrets.token_hex(16),draft['reference'],'New','Submitted by demo staff',now()))
        return RedirectResponse('/requests/'+draft['reference'],status_code=303)

    @app.get('/requests/{reference}')
    def detail(request: Request, reference: str):
        blocked=guard(request)
        if blocked is not None:return blocked
        with db() as conn:
            item=conn.execute('SELECT * FROM service_requests WHERE id=?',(reference,)).fetchone()
            events=conn.execute("SELECT * FROM request_events WHERE request_id=? ORDER BY created, CASE status WHEN 'New' THEN 0 WHEN 'In review' THEN 1 ELSE 2 END",(reference,)).fetchall()
        if not item:return failure(request,'Request not found')
        return render(request,'request_detail',item=item,events=events,kind_info=KINDS[item['kind']],next_status=TRANSITIONS.get(item['status']))

    @app.post('/requests/{reference}/status')
    async def update(request: Request, reference: str):
        blocked=guard(request)
        if blocked is not None:return blocked
        data=await form(request)
        if data is None or request.state.session['scenario']=='permission-denied':return render(request,'denied')
        note=str(data.get('note','')).strip()
        if not 5 <= len(note) <= 500:return failure(request,'A status note of 5 to 500 characters is required')
        try: revision=int(str(data.get('revision','')))
        except ValueError:return failure(request,'Invalid request revision')
        with db() as conn:
            item=conn.execute('SELECT * FROM service_requests WHERE id=?',(reference,)).fetchone()
            if not item:return failure(request,'Request not found')
            desired=TRANSITIONS.get(item['status'])
            if not desired:return failure(request,'Request is already resolved')
            if str(data.get('status',''))!=desired:return failure(request,'Invalid status transition')
            changed=conn.execute('UPDATE service_requests SET status=?,revision=revision+1 WHERE id=? AND revision=?',(desired,reference,revision))
            if not changed.rowcount:return failure(request,'Request changed; reload before updating')
            conn.execute('INSERT INTO request_events VALUES (?,?,?,?,?)',(secrets.token_hex(16),reference,desired,note,now()))
        return RedirectResponse('/requests/'+reference,status_code=303)
