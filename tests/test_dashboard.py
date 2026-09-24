"""Full-stack UI tests. Operator commands here are scripted, not genuine human evidence."""
import os,socket,threading,time
from pathlib import Path
import pytest,uvicorn
from playwright.sync_api import sync_playwright,expect
from demo.app import create_app as bank_app
from engine.api import create_app as api_app
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def dashboard(tmp_path,monkeypatch):
    if not (ROOT/'frontend/dist/index.html').exists(): pytest.skip('Build frontend first')
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.browsers'))
    sockets=[]
    for _ in range(2):
        sock=socket.socket();sock.bind(('127.0.0.1',0));sockets.append(sock)
    bank_url=f'http://127.0.0.1:{sockets[0].getsockname()[1]}'
    api_url=f'http://127.0.0.1:{sockets[1].getsockname()[1]}'
    monkeypatch.setenv('DEMO_ENTRY',bank_url)
    monkeypatch.setenv('DASHBOARD_ORIGINS',api_url)
    monkeypatch.setenv('DASHBOARD_STORAGE',str(tmp_path/'execution'))
    services=[]
    for app,sock in zip([bank_app(tmp_path/'bank.sqlite3'),api_app()],sockets):
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start();services.append((server,thread))
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(api_url,wait_until='networkidle')
            expect(page.get_by_text('Live API connected',exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_label('Message your assistant')).to_be_visible()
            yield page
            assert not errors
            browser.close()
    finally:
        for server,thread in services: server.should_exit=True
        for server,thread in services: thread.join(timeout=10)
        for sock in sockets: sock.close()

def setup_replay(page):
    page.locator('.chat-tools > summary').click()
    page.get_by_role('button',name='Learn a new workflow',exact=True).click()
    page.get_by_role('button',name='Replay capability').click()
    expect(page.get_by_role('button',name='Start replay',exact=True)).to_be_enabled(timeout=15000)


def test_chat_trace_header_works_with_legacy_body_validation(dashboard, monkeypatch, trace_capture):
    """A legacy server rejects extra body fields before reaching any model call."""
    import uuid
    import engine.catalog_agent as agent
    async def match(*args): return {'matches':['example'],'model_used':True}
    async def inputs(*args): return {'customer_id':'C-205','street':'73 Maple Street','city':'Fremont','postal':'94538'}
    monkeypatch.setattr(agent,'match_capabilities',match)
    monkeypatch.setattr(agent,'extract_inputs',inputs)
    page=dashboard
    captured=[]
    def legacy_validation(route):
        req=route.request
        if req.method=='POST':
            body=req.post_data_json
            captured.append((req.url,body,req.headers.get('x-conversation-id')))
            if 'conversation_id' in body:
                route.fulfill(status=422,json={'detail':[{'loc':['body','conversation_id'],'type':'extra_forbidden'}]})
                return
        route.continue_()
    page.route('**/api/agent/*',legacy_validation)
    page.route('**/api/runs',legacy_validation)
    page.get_by_label('Message your assistant').fill('Update the mailing address for customer C-205 to 73 Maple Street, Fremont, postal code 94538.')
    page.get_by_role('button',name='Send message',exact=True).click()
    page.get_by_role('button',name='Use this workflow',exact=True).click()
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_be_visible()
    page.get_by_label('Authorize changes for this synthetic run').check()
    page.get_by_role('button',name='Run workflow',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=30000)
    assert len(captured)==3  # Match, extract, execute. No automatic resubmission.
    identifiers={str(uuid.UUID(identifier)) for _,_,identifier in captured}
    assert len(identifiers)==1
    assert all('conversation_id' not in body for _,body,_ in captured)
    root=next(s for s in trace_capture if s.operation=='workflow.replay')
    assert root.record['extra']['metadata']['conversation_id']==identifiers.pop()
    assert root.record['outputs']['model_calls']==0


@pytest.mark.parametrize('matched', [False, True])
def test_agent_search_offers_recording_or_parameterized_replay(dashboard, monkeypatch, matched):
    import engine.catalog_agent as agent
    async def scripted_match(message, catalog, model):
        if 'address-discovery' in catalog: return {'matches': [], 'model_used': True}
        assert message == 'Update the mailing address' and 'example' in catalog
        return {'matches': ['example'] if matched else [], 'model_used': True}
    monkeypatch.setattr(agent, 'match_capabilities', scripted_match)
    async def scripted_inputs(message, capability, model):
        return {'C-205':{'customer_id':'C-205'},'92 Chat Lane':{'street':'92 Chat Lane'},'Exampleton':{'city':'Exampleton'},'23456':{'postal':'23456'}}.get(message,{})
    monkeypatch.setattr(agent, 'extract_inputs', scripted_inputs)
    page = dashboard
    page.get_by_label('Message your assistant').fill('Update the mailing address')
    page.get_by_role('button', name='Send message', exact=True).click()
    if not matched:
        expect(page.get_by_text("I don’t have a saved workflow for that yet.", exact=False)).to_be_visible(timeout=10000)
        assert page.request.get(page.url.rstrip('/')+'/api/runs').json() == []
        for _ in range(50):
            chats=page.request.get(page.url.rstrip('/')+'/api/conversations').json()
            if chats and page.request.get(page.url.rstrip('/')+'/api/conversations/'+chats[0]['id']).json().get('teaching_mode')=='choose': break
            page.wait_for_timeout(100)
        else: raise AssertionError('Method question was not saved')
        page.reload()
        page.get_by_role('button', name='Learn it for me', exact=True).click()
        expect(page.get_by_text('I can currently learn address changes on my own.',exact=False)).to_be_visible()
        page.get_by_role('button', name='I’ll record the steps', exact=True).click()
        expect(page.get_by_role('button',name='Start recording',exact=True)).to_have_count(0)
        page.get_by_role('button',name='Return result details',exact=True).click()
        expect(page.get_by_role('button',name='Start recording',exact=True)).to_be_visible()
        return
    page.get_by_role('button', name='Use this workflow', exact=True).click()
    assert page.request.get(page.url.rstrip('/')+'/api/runs').json() == []
    expect(page.get_by_role('button',name='Working\u2026',exact=True)).to_have_count(0,timeout=10000)
    for value in ('C-205','92 Chat Lane','Exampleton','23456'):
        page.get_by_label('Message your assistant').fill(value)
        page.get_by_role('button',name='Send message',exact=True).click()
        expect(page.get_by_role('button',name='Working\u2026',exact=True)).to_have_count(0,timeout=10000)
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_be_visible()
    page.get_by_label('Authorize changes for this synthetic run').check()
    page.get_by_role('button',name='Run workflow',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=30000)
    assert page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]['model_decisions'] == 0
    expect(page.get_by_role('log',name='Conversation')).to_contain_text('Done — I updated the mailing address',timeout=10000)


def test_dashboard_executes_replay_and_verifies_live_result(dashboard):
    page=dashboard;setup_replay(page)
    page.get_by_label('Authorize changes for this synthetic run').check()
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=45000)
    expect(page.locator('.result-banner')).to_contain_text('C-104')
    result=page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
    assert result['model_decisions']==0 and result['actions']==14
    assert result['result']['outputs']['street']=='[REDACTED]'
    page.set_viewport_size({'width':390,'height':844})
    for name in ('Back to chat','Past runs'):
        page.locator('.chat-tools > summary').click()
        page.get_by_role('button',name=name,exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),name


def test_langsmith_status_and_run_link(trace_capture, dashboard, monkeypatch):
    from engine import telemetry
    # Export is a test double; execution below uses the actual UI and browser engine.
    link = 'https://smith.langchain.com/test/project/run'
    def exported(span):
        trace_capture.append(span)
        telemetry.update(span.cfg, span.id, 'exported', url=link)
    monkeypatch.setattr(telemetry, '_submit', exported)
    page = dashboard
    page.locator('.model-status > summary').click()
    expect(page.get_by_text('LangSmith tracing', exact=True)).to_be_visible()
    expect(page.locator('.tracing-status')).to_contain_text('On. Only safe metadata')
    setup_replay(page)
    page.get_by_label('Authorize changes for this synthetic run').check()
    page.get_by_role('button', name='Start replay', exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=45000)
    page.get_by_role('button', name='Inspect result', exact=False).click()
    expect(page.get_by_role('link', name='View LangSmith trace')).to_have_attribute('href', link)
    run = page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
    assert run['trace']['state'] == 'exported'
    assert run['trace']['id'] == trace_capture[0].id
    assert trace_capture[0].record['extra']['metadata']['job_id'] == run['id']
    assert trace_capture[0].record['outputs']['model_calls'] == 0
    assert 'test-private-key' not in str(run)


def test_run_explanation_is_readable_without_langsmith(dashboard):
    page = dashboard
    setup_replay(page)
    page.get_by_label('Runtime scenario').select_option('permission-denied')
    page.get_by_role('button', name='Start replay', exact=True).click()
    expect(page.locator('.result-banner.failure')).to_be_visible(timeout=45000)
    story = page.get_by_role('region', name='Run explanation')
    expect(story).to_contain_text('The application denied access')
    expect(story).to_contain_text('Click Edit mailing address')
    expect(story).to_contain_text('4 / 4 attempted')
    expect(story).to_contain_text('0 during replay')
    expect(story).to_contain_text('No protected write was attempted.')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

def test_scripted_operator_uses_same_live_session_and_resumes(dashboard):
    page=dashboard;setup_replay(page)
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.get_by_role('heading',name='Your review is needed')).to_be_visible(timeout=45000)
    before=page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
    # The review page's six navigation links precede its Save button.
    for _ in range(7): page.get_by_role('button',name='Tab',exact=True).click()
    page.get_by_role('button',name='Enter',exact=True).click()
    for _ in range(60):
        record=page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
        if any(e['event']=='human_action' and e.get('action',{}).get('label')=='Save address' for e in record['events']): break
        page.wait_for_timeout(200)
    else: raise AssertionError('Scripted operator did not activate Save')
    page.get_by_role('button',name='Resume automation',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=45000)
    after=page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
    assert after['live']['session_id']==before['live']['session_id']
    assert after['result']['human_assisted'] is True and after['model_decisions']==0
    assert [e['owner'] for e in after['events'] if e['event']=='ownership']==['human','automation']

def test_viewer_and_runtime_failure(dashboard):
    page=dashboard
    page.get_by_label('Choose demo profile').click()
    page.get_by_role('button',name='Taylor Morgan',exact=False).click()
    page.locator('.chat-tools > summary').click()
    expect(page.get_by_role('button',name='Learn a new workflow',exact=True)).to_be_disabled()
    page.locator('.chat-tools > summary').click()
    expect(page.get_by_role('button',name='Send message',exact=True)).to_be_disabled()
    page.get_by_label('Choose demo profile').click()
    page.get_by_role('button',name='Sam Rivera',exact=False).click()
    page.locator('.chat-tools > summary').click()
    page.get_by_role('button',name='Learn a new workflow',exact=True).click()
    page.get_by_role('button',name='Replay capability').click()
    page.get_by_label('Runtime scenario').select_option('permission-denied')
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.result-banner.failure')).to_be_visible(timeout=45000)
    expect(page.locator('.result-banner')).to_contain_text('Permission denied')


def test_dashboard_records_reviews_publishes_and_replays(dashboard, monkeypatch):
    """Scripted UI gestures, not a genuine human recording demonstration."""
    import io, zipfile
    import engine.recording as recording
    from engine.surface import BrowserSurface
    coords = {}
    frame_number = 0
    class InspectedSurface(BrowserSurface):
        def frame(self):
            nonlocal coords, frame_number
            # Read-only test instrumentation locates image click positions; all task
            # actions still travel through the dashboard's real control API.
            coords = self.page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('input,button,a')].map(e=>{
                const r=e.getBoundingClientRect();const name=e.labels?.[0]?.textContent.trim()||e.innerText?.trim();
                return [name,{x:r.x+r.width/2,y:r.y+r.height/2}];}).filter(([name,p])=>name && p.x>0 && p.y>0))""")
            result = super().frame()
            frame_number += 1
            return result
    monkeypatch.setattr(recording,'BrowserSurface',InspectedSurface)
    page=dashboard
    page.locator('.chat-tools > summary').click()
    page.get_by_role('button',name='Learn a new workflow',exact=True).click()
    page.get_by_role('button',name='Record workflow',exact=False).click()
    page.get_by_label('Workflow name').fill('Manual address update')
    page.get_by_role('button',name='Start recording',exact=True).click()
    expect(page.get_by_role('heading',name='You are recording')).to_be_visible(timeout=15000)
    page.get_by_text('Advanced field entry',exact=True).click()
    base=page.url.rstrip('/')
    def wait_steps(count):
        for _ in range(150):
            job=page.request.get(base+'/api/runs').json()[0]
            if job.get('recording',{}).get('error'):
                raise AssertionError(job['recording']['error'])
            if len(job.get('recording',{}).get('steps',[]))>=count and frame_number >= count+1:return job
            page.wait_for_timeout(100)
        raise AssertionError('Recording command was not documented')
    gestures=[('click','Customer ID'),('fill','customer_id','C-104'),('click','Search customers'),
        ('click','Open customer'),('click','Edit mailing address'),('click','Street address'),
        ('fill','street','71 Recording Road'),('click','City'),('fill','city','Exampleton'),
        ('click','Postal code'),('fill','postal','34567'),('click','Review changes'),('click','Save address')]
    for count,item in enumerate(gestures,1):
        if item[0]=='click':
            point=coords[item[1]]
            screen=page.locator('.live-screen')
            screen.evaluate('(e) => e.decode()')
            box=screen.bounding_box()
            screen.click(position={'x':point['x']*box['width']/1280,'y':point['y']*box['height']/720})
        else:
            page.get_by_label('Parameter name',exact=True).fill(item[1])
            page.get_by_label('Example value',exact=True).fill(item[2])
            page.get_by_role('button',name='Fill parameter',exact=True).click()
        job=wait_steps(count)
    page.get_by_label('Success heading').select_option('Address updated')
    for label,key in [('Saved customer ID','customer_id'),('Saved street address','street'),('Saved city','city'),('Saved postal code','postal'),('Confirmation reference','confirmation_reference')]:
        page.get_by_label('Output key for '+label,exact=True).fill(key)
    page.get_by_role('button',name='Finish and review recording').click()
    publish=page.get_by_role('button',name='Publish reviewed workflow')
    expect(publish).to_be_visible(timeout=15000)
    doc=page.request.get(base+'/api/runs/'+job['id']+'/document')
    assert doc.status==200
    with zipfile.ZipFile(io.BytesIO(doc.body())) as archive:
        assert 'WORKFLOW.md' in archive.namelist()
        assert len([n for n in archive.namelist() if n.endswith('.png')])==26
    page.get_by_role('button',name='Create playback video').click()
    video = page.get_by_label('Recorded workflow video')
    expect(video).to_be_visible(timeout=30000)
    video.evaluate('(v) => v.load()')
    assert video.evaluate('(v) => v.duration') > 20
    video.evaluate('(v) => { v.muted = true; return v.play(); }')
    video.evaluate('(v) => v.pause()')
    publish.click()
    expect(page.get_by_role('button',name='Published to capabilities')).to_be_disabled(timeout=10000)
    page.get_by_role('button',name='Replay this new capability').click()
    expect(page.get_by_label('Input customer_id')).to_have_value('C-205')
    page.get_by_label('Authorize changes for this synthetic run').check()
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=30000)
    replayed=page.request.get(base+'/api/runs').json()[0]
    assert replayed['mode']=='replay' and replayed['model_decisions']==0 and replayed['actions']==14


def test_mouse_wheel_scrolls_managed_browser_not_dashboard(dashboard, monkeypatch):
    import engine.recording as recording
    from engine.surface import BrowserSurface
    observed = {'y':0}
    class ScrollSurface(BrowserSurface):
        def open(self, entry):
            super().open(entry)
            # Explicit fixture makes scrolling observable independently of bank content.
            self.page.evaluate("document.body.style.minHeight = '3000px'")
        def pump_events(self):
            super().pump_events()
            observed['y'] = self.page.evaluate('window.scrollY')
    monkeypatch.setattr(recording, 'BrowserSurface', ScrollSurface)
    page = dashboard
    page.locator('.chat-tools > summary').click()
    page.get_by_role('button',name='Learn a new workflow',exact=True).click()
    page.get_by_role('button',name='Record workflow',exact=False).click()
    page.get_by_role('button',name='Start recording',exact=True).click()
    screen = page.get_by_alt_text('Current automation browser')
    expect(screen).to_be_visible(timeout=15000)
    screen.evaluate('(e) => e.decode()')
    screen.hover()
    outer_y = page.evaluate('window.scrollY')
    page.mouse.wheel(0,600)
    for _ in range(60):
        if observed['y'] > 0: break
        page.wait_for_timeout(100)
    assert observed['y'] > 0
    assert page.evaluate('window.scrollY') == outer_y
    page.get_by_role('button',name='Cancel run',exact=True).click()


def test_inline_recording_infers_inputs_and_stops_for_review(dashboard, monkeypatch):
    import engine.recording as recording
    import engine.catalog_agent as agent
    async def match(*args): return {'matches':[], 'model_used':False}
    monkeypatch.setattr(agent,'match_capabilities',match)
    from engine.surface import BrowserSurface
    coords = {}
    class LocatedSurface(BrowserSurface):
        def frame(self):
            nonlocal coords
            coords = self.page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('input,button,a')].map(e=>{const r=e.getBoundingClientRect();return [e.labels?.[0]?.textContent.trim()||e.innerText?.trim(),{x:r.x+r.width/2,y:r.y+r.height/2}]}))""")
            return super().frame()
    monkeypatch.setattr(recording,'BrowserSurface',LocatedSurface)
    page=dashboard
    page.get_by_label('Message your assistant').fill('Check an account balance')
    page.get_by_role('button',name='Send message',exact=True).click()
    page.get_by_role('button',name='I’ll record the steps',exact=True).click()
    page.get_by_role('button',name='Just confirm it’s done',exact=True).click()
    page.get_by_role('button',name='Start recording',exact=True).click()
    expect(page.get_by_role('heading',name='You are recording')).to_be_visible(timeout=15000)
    base=page.url.rstrip('/')
    def click_bank(label):
        for _ in range(100):
            if label in coords: break
            page.wait_for_timeout(100)
        point=coords[label];screen=page.locator('.live-screen')
        screen.evaluate('(e) => e.decode()')
        box=screen.bounding_box()
        # During an img source refresh Chromium can briefly report zero intrinsic
        # dimensions while the previous pixels are still visible. Mapping must use
        # the last loaded frame, including a click that occurs during that interval.
        if label=='Account ID':
            screen.evaluate("e => { for(const k of ['naturalWidth','naturalHeight']) Object.defineProperty(e,k,{value:0,configurable:true}); }")
        screen.click(position={'x':point['x']*box['width']/1280,'y':point['y']*box['height']/720})
        if label=='Account ID':
            screen.evaluate("e => { delete e.naturalWidth; delete e.naturalHeight; }")
    click_bank('Accounts')
    click_bank('Account ID')
    editor=page.get_by_role('textbox',name='Type Account ID',exact=True)
    expect(editor).to_be_visible(timeout=15000)
    editor.fill('AC-4104')
    editor.press('Enter')
    for _ in range(100):
        draft_job=page.request.get(base+'/api/runs').json()[0]
        if 'account_id' in draft_job.get('recording',{}).get('parameters',{}):break
        page.wait_for_timeout(100)
    editor.fill('AC-4205')
    # Blur commits the value, then the following click must execute after that fill.
    click_bank('Search accounts')
    click_bank('Open account')
    for _ in range(100):
        job=page.request.get(base+'/api/runs').json()[0]
        if 'Account balance verified' in job.get('recording',{}).get('headings',[]):break
        page.wait_for_timeout(100)
    page.get_by_role('button',name='Stop recording & review',exact=True).click()
    expect(page.get_by_role('button',name='Continue recording',exact=True)).to_be_visible(timeout=15000)
    expect(page.get_by_role('textbox',name='Type Account ID',exact=True)).to_have_count(0)
    expect(page.get_by_label('Success heading')).to_have_value('Account balance verified')
    expect(page.get_by_label('Output key for Verified account ID')).to_have_value('account_id')
    page.get_by_label('Reusable input name for account_id').fill('selected_account')
    page.get_by_role('button',name='Finish and review recording',exact=True).click()
    publish=page.get_by_role('button',name='Publish reviewed workflow',exact=True)
    expect(publish).to_be_visible(timeout=15000)
    job=page.request.get(base+'/api/runs').json()[0]
    assert set(job['draft']['inputs']) == {'selected_account'}
    assert job['draft']['outputs']['account_id']['equals_input']=='selected_account'
    assert job['draft']['return_details'] is False
    assert job['draft']['name'] == 'Account balance verified'
    import json
    assert 'AC-4205' not in json.dumps(job)
    assert [a['input_key'] for a in job['draft']['steps'] if a['kind']=='fill']==['selected_account']
    publish.click()
    page.get_by_role('button',name='Replay this new capability',exact=True).click()
    page.get_by_label('Input selected_account').fill('AC-4306')
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=30000)
    replay_job=page.request.get(base+'/api/runs').json()[0]
    reply=page.request.get(base+'/api/runs/'+replay_job['id']+'/answer').json()['message']
    assert reply=='Done — I completed and verified the task.'
    assert replay_job['model_decisions']==0


def test_chat_model_failure_allows_manual_recovery_without_execution(dashboard, monkeypatch):
    import httpx
    import engine.catalog_agent as agent
    async def fail(*args):
        raise httpx.ConnectError('provider-private-data')
    monkeypatch.setattr(agent,'match_capabilities',fail)
    monkeypatch.setattr(agent,'extract_inputs',fail)
    page=dashboard
    page.get_by_label('Message your assistant').fill('Update my mailing address')
    page.get_by_role('button',name='Send message',exact=True).click()
    expect(page.get_by_role('button',name='Retry last message')).to_be_visible()
    expect(page.get_by_text('I cannot reach the local model service.',exact=False)).to_be_visible()
    name=page.request.get(page.url.rstrip('/')+'/api/capabilities').json()[0]['capability']['name']
    page.get_by_role('button',name=name,exact=True).click()
    expect(page.get_by_label('Workflow input customer_id')).to_be_visible()
    for key,value in {'customer_id':'C-205','street':'92 Recovery Lane','city':'Exampleton','postal':'23456'}.items():
        page.get_by_label('Workflow input '+key,exact=True).fill(value)
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_be_enabled()
    assert 'provider-private-data' not in page.locator('body').inner_text()
    assert page.request.get(page.url.rstrip('/')+'/api/runs').json()==[]


def test_chat_keyboard_and_new_request_keep_execution_explicit(dashboard, monkeypatch):
    import engine.catalog_agent as agent
    seen=[]
    async def match(message, catalog, model):
        if 'address-discovery' not in catalog: seen.append(message)
        return {'matches':[], 'model_used':False}
    monkeypatch.setattr(agent,'match_capabilities',match)
    page=dashboard
    editor=page.get_by_label('Message your assistant')
    editor.fill('Check an account')
    editor.press('Shift+Enter')
    editor.press('a')
    assert seen==[]
    editor.press('Enter')
    expect(page.get_by_text("I don’t have a saved workflow for that yet.",exact=False)).to_be_visible()
    assert seen==['Check an account\na']
    page.get_by_role('button',name='New request',exact=True).click()
    expect(editor).to_be_empty()
    expect(editor).to_be_focused()
    expect(page.get_by_role('log',name='Conversation').locator('article')).to_have_count(0)
    assert page.request.get(page.url.rstrip('/')+'/api/runs').json()==[]


def test_conversation_reload_restores_details_without_write_approval(dashboard,monkeypatch):
    import engine.catalog_agent as agent
    async def match(*args):return {'matches':['example'],'model_used':False}
    async def extract(*args):return {'customer_id':'C-205','street':'92 Persistent Lane','city':'Exampleton','postal':'23456'}
    monkeypatch.setattr(agent,'match_capabilities',match)
    monkeypatch.setattr(agent,'extract_inputs',extract)
    page=dashboard;base=page.url.rstrip('/')
    page.get_by_label('Message your assistant').fill('Change my address')
    page.get_by_role('button',name='Send message',exact=True).click()
    page.get_by_role('button',name='Use this workflow',exact=True).click()
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_be_enabled()
    page.get_by_label('Authorize changes for this synthetic run').check()
    for _ in range(50):
        chats=page.request.get(base+'/api/conversations').json()
        if chats and page.request.get(base+'/api/conversations/'+chats[0]['id']).json()['values'].get('street')=='92 Persistent Lane':break
        page.wait_for_timeout(100)
    else:raise AssertionError('Conversation was not saved')
    page.reload()
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_be_enabled(timeout=10000)
    expect(page.locator('.agent-match dd').get_by_text('92 Persistent Lane',exact=True)).to_be_visible()
    expect(page.get_by_label('Authorize changes for this synthetic run')).not_to_be_checked()
    assert page.request.get(base+'/api/runs').json()==[]


@pytest.mark.parametrize("missing_postal", [False, True])
@pytest.mark.parametrize("explicit_discovery", [False, True])
def test_chat_prepares_discovery_and_requires_confirmation(dashboard, monkeypatch, missing_postal, explicit_discovery):
    # Model and dispatch doubles verify UI behavior, not genuine discovery evidence.
    import engine.catalog_agent as agent
    async def match(message, catalog, model):
        return {"matches": ["address-discovery"] if "address-discovery" in catalog else (["example"] if explicit_discovery else []), "model_used":True, "intent":"discover" if explicit_discovery else "use_workflow"}
    async def extract(message, spec, model):
        if message == "94538": return {"postal":"94538"}
        return {"customer_id":"C-104", "street":"28 Maple Street", "city":"Fremont", **({} if missing_postal else {"postal":"94538"})}
    monkeypatch.setattr(agent, "match_capabilities", match)
    monkeypatch.setattr(agent, "extract_inputs", extract)
    async def setup(message, stage, model):
        return 'learn' if stage=='method' else 'details'
    monkeypatch.setattr(agent, 'interpret_setup_reply', setup)
    page=dashboard
    page.get_by_label("Message your assistant").fill(("Learn a new workflow from scratch: " if explicit_discovery else "") + "Update C-104 to 28 Maple Street, Fremont" + ("" if missing_postal else ", 94538"))
    page.get_by_role("button",name="Send message",exact=True).click()
    if not explicit_discovery:
        expect(page.get_by_role('button',name='Learn it for me',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='Confirm and start discovery',exact=True)).to_have_count(0)
        # A free-text choice follows the same path as the buttons.
        page.get_by_label('Message your assistant').fill('You figure out the steps for me')
        page.get_by_role('button',name='Send message',exact=True).click()
    if missing_postal:
        expect(page.get_by_role("log",name="Conversation")).to_contain_text("I still need postal",timeout=10000)
        expect(page.get_by_role("button",name="Confirm and start discovery")).to_have_count(0)
        page.get_by_label("Message your assistant").fill("94538")
        page.get_by_role("button",name="Send message",exact=True).click()
    confirm=page.get_by_role("button",name="Confirm and start discovery",exact=True)
    expect(page.get_by_role('button',name='Return result details',exact=True)).to_be_visible()
    expect(confirm).to_have_count(0)
    page.get_by_label('Message your assistant').fill('Yes, show me the result details')
    page.get_by_role('button',name='Send message',exact=True).click()
    expect(confirm).to_be_visible(timeout=10000)
    expect(page.get_by_role("button",name="Use this workflow",exact=True)).to_have_count(0)
    expect(page.get_by_label("Workflow input customer_id")).to_have_count(0)
    assert page.request.get(page.url.rstrip('/')+'/api/runs').json()==[]
    for _ in range(50):
        chats=page.request.get(page.url.rstrip('/')+'/api/conversations').json()
        if chats:
            saved=page.request.get(page.url.rstrip('/')+'/api/conversations/'+chats[0]['id']).json()
            if saved['values'].get('postal')=='94538' and saved.get('return_details') is True: break
        page.wait_for_timeout(100)
    else: raise AssertionError('Discovery draft not saved')
    page.reload()
    expect(confirm).to_be_visible(timeout=10000)
    expect(page.get_by_label("Authorize changes for this synthetic run")).not_to_be_checked()
    submitted=[]
    def dispatch(route):
        if route.request.method == "POST":
            submitted.append(route.request.post_data_json)
            route.fulfill(status=202,content_type="application/json",body='{"id":"test-dispatch"}')
        else: route.continue_()
    page.route("**/api/runs",dispatch)
    page.get_by_label("Authorize changes for this synthetic run").check()
    confirm.click()
    expect(page.get_by_role("log",name="Conversation")).to_contain_text("I’m learning",timeout=10000)
    assert submitted[0]["mode"]=="discovery"
    assert submitted[0]["inputs"]=={"customer_id":"C-104","street":"28 Maple Street","city":"Fremont","postal":"94538"}
    assert submitted[0]["approve_writes"] is True
    assert submitted[0]['return_details'] is True


@pytest.mark.parametrize('supported', [True, False])
def test_chat_can_switch_replay_draft_to_discovery_in_english(dashboard, monkeypatch, supported):
    import engine.catalog_agent as agent
    values = {'customer_id':'C-104','street':'75 Pine Street','city':'Fremont','postal':'94538'}
    seen = []
    async def match(message, catalog, model):
        if 'address-discovery' in catalog:
            seen.append(message)
            return {'matches':['address-discovery'] if supported else [],'model_used':True}
        return {'matches':['example'],'model_used':True,'intent':'discover' if 'from scratch' in message else 'use_workflow'}
    async def extract(*args): return values
    monkeypatch.setattr(agent,'match_capabilities',match)
    monkeypatch.setattr(agent,'extract_inputs',extract)
    page=dashboard
    page.get_by_label('Message your assistant').fill('Update C-104 to 75 Pine Street, Fremont, postal 94538')
    page.get_by_role('button',name='Send message',exact=True).click()
    page.get_by_role('button',name='Use this workflow',exact=True).click()
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_be_visible()
    page.get_by_label('Authorize changes for this synthetic run').check()
    page.get_by_label('Message your assistant').fill('Learn it from scratch instead')
    page.get_by_role('button',name='Send message',exact=True).click()
    if supported:
        page.get_by_role('button',name='Just confirm it’s done',exact=True).click()
        expect(page.get_by_role('button',name='Confirm and start discovery',exact=True)).to_be_visible()
        expect(page.get_by_label('Authorize changes for this synthetic run')).not_to_be_checked()
        for value in values.values():
            expect(page.locator('.agent-match dd').get_by_text(value,exact=True)).to_be_visible()
    else:
        expect(page.get_by_role('log',name='Conversation')).to_contain_text('I can’t discover this task yet')
        expect(page.get_by_role('button',name='Confirm and start discovery',exact=True)).to_have_count(0)
    assert '75 Pine Street' in seen[0] and 'Latest user message: Learn it from scratch instead' in seen[0]
    expect(page.get_by_role('button',name='Run workflow',exact=True)).to_have_count(0)
    expect(page.get_by_label('Workflow input street',exact=True)).to_have_count(0)
    assert page.request.get(page.url.rstrip('/')+'/api/runs').json()==[]


def test_balance_answer_uses_real_replay_and_stays_out_of_evidence(dashboard, monkeypatch):
    import json
    import httpx
    import engine.catalog_agent as agent
    from tests.test_replies import balance_capability
    cap=balance_capability()
    storage=Path(os.environ['DASHBOARD_STORAGE'])
    (storage/'capabilities'/'balance-test.json').write_text(cap.model_dump_json(),encoding='utf-8')
    async def match(*args): return {'matches':['balance-test'],'model_used':False}
    async def extract(*args): return {'account_id':'AC-4205'}
    monkeypatch.setattr(agent,'match_capabilities',match)
    monkeypatch.setattr(agent,'extract_inputs',extract)
    # The executor really operates the isolated bank. Any model transport is blocked.
    monkeypatch.setattr(httpx.Client,'send',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('No model calls allowed')))
    page=dashboard; base=page.url.rstrip('/')
    for _ in range(30):
        if any(c['id']=='balance-test' for c in page.request.get(base+'/api/capabilities').json()):break
        page.wait_for_timeout(100)
    page.wait_for_timeout(700)
    page.get_by_label('Message your assistant').fill("What's the balance of account AC-4205?")
    page.get_by_role('button',name='Send message',exact=True).click()
    page.get_by_role('button',name='Use this workflow',exact=True).click()
    page.get_by_role('button',name='Run workflow',exact=True).click()
    expect(page.get_by_role('log',name='Conversation')).to_contain_text('$4,200.75 USD',timeout=30000)
    runs=page.request.get(base+'/api/runs').json(); job=runs[0]
    assert job['model_decisions']==0
    assert job['result']['outputs']=={'returned_account':'[REDACTED]','amount':'[REDACTED]'}
    assert '4200.75' not in json.dumps(job) and '4,200.75' not in json.dumps(job)
    evidence=page.request.get(base+'/api/runs/'+job['id']+'/evidence').text()
    assert '4200.75' not in evidence and '4,200.75' not in evidence
    assert '$4,200.75' in page.request.get(base+'/api/runs/'+job['id']+'/answer').json()['message']
    for _ in range(50):
        chats=page.request.get(base+'/api/conversations').json()
        if chats:
            chat=page.request.get(base+'/api/conversations/'+chats[0]['id']).json()
            if any(m.get('run_id')==job['id'] for m in chat['messages']):break
        page.wait_for_timeout(100)
    else: raise AssertionError('Answer not saved to private conversation')
    page.reload()
    expect(page.get_by_role('log',name='Conversation')).to_contain_text('$4,200.75 USD',timeout=10000)
    assert page.get_by_role('log',name='Conversation').get_by_text('$4,200.75',exact=False).count()==1
    for profile in ('sam','taylor'):
        page.request.post(base+'/api/session',headers={'Origin':base},data={'profile_id':profile})
        assert page.request.get(base+'/api/runs/'+job['id']+'/answer').status==404
    for path in storage.glob('job-*.json'):
        assert '4,200.75' not in path.read_text() and '4200.75' not in path.read_text()
