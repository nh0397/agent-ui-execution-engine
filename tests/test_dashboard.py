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
            yield page
            assert not errors
            browser.close()
    finally:
        for server,thread in services: server.should_exit=True
        for server,thread in services: thread.join(timeout=10)
        for sock in sockets: sock.close()

def setup_replay(page):
    page.get_by_role('navigation').get_by_role('button',name='New workflow').click()
    page.get_by_role('button',name='Replay capability').click()
    expect(page.get_by_role('button',name='Start replay',exact=True)).to_be_enabled(timeout=15000)

def test_dashboard_executes_replay_and_verifies_live_result(dashboard):
    page=dashboard;setup_replay(page)
    page.get_by_label('Authorize the synthetic address save').check()
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.result-banner.success')).to_be_visible(timeout=45000)
    expect(page.locator('.result-banner')).to_contain_text('C-104')
    result=page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
    assert result['model_decisions']==0 and result['actions']==14
    assert result['result']['outputs']['street']=='[REDACTED]'
    page.set_viewport_size({'width':390,'height':844})
    for name in ('Overview','New workflow','Capabilities','Run history','Live session','Banking app'):
        page.get_by_role('navigation').get_by_role('button',name=name).click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),name

def test_scripted_operator_uses_same_live_session_and_resumes(dashboard):
    page=dashboard;setup_replay(page)
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.get_by_role('heading',name='Your review is needed')).to_be_visible(timeout=45000)
    before=page.request.get(page.url.rstrip('/')+'/api/runs').json()[0]
    # The review page's four navigation links precede its Save button.
    for _ in range(5): page.get_by_role('button',name='Tab',exact=True).click()
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
    page.get_by_role('navigation').get_by_role('button',name='New workflow').click()
    expect(page.get_by_role('button',name='Start discovery',exact=True)).to_be_disabled()
    page.get_by_label('Choose demo profile').click()
    page.get_by_role('button',name='Sam Rivera',exact=False).click()
    page.get_by_role('button',name='Replay capability').click()
    page.get_by_label('Runtime scenario').select_option('permission-denied')
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.result-banner.failure')).to_be_visible(timeout=45000)
    expect(page.locator('.result-banner')).to_contain_text('Permission denied')
