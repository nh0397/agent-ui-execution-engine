"""Synthetic banking case intake, persistence, and state-transition checks."""
import re
from fastapi.testclient import TestClient
from demo.app import create_app
from demo.database import connect
import pytest


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)

@pytest.mark.parametrize('kind,customer,resource', [('statement','C-104','AC-4104'),('replacement','C-205','DC-205'),('dispute','C-104','TX-102')])
def test_request_review_submit_idempotence_and_status(tmp_path,kind,customer,resource):
    database=tmp_path/'bank.db'
    with TestClient(create_app(database)) as c:
        token=csrf(c.get('/requests/new/'+kind))
        form=dict(csrf=token,customer_id=customer,resource_id=resource,notes='Synthetic customer service request')
        review=c.post('/requests/review/'+kind,data=form)
        assert 'Review service request' in review.text
        draft_token=re.search(r'name="token" value="([^"]+)"',review.text).group(1)
        saved=c.post('/requests/submit',data={'csrf':token,'token':draft_token})
        assert 'Service request saved' in saved.text
        reference=saved.url.path.split('/')[-1]
        assert c.post('/requests/submit',data={'csrf':token,'token':draft_token}).url.path.endswith(reference)
        with connect(database) as db:
            assert db.execute('SELECT COUNT(*) AS n FROM service_requests WHERE id=?',(reference,)).fetchone()['n']==1
            assert db.execute('SELECT COUNT(*) AS n FROM request_events WHERE request_id=?',(reference,)).fetchone()['n']==1
        status={'csrf':token,'revision':'0','status':'In review','note':'Assigned to servicing team'}
        assert 'In review' in c.post('/requests/'+reference+'/status',data=status).text
        stale={**status,'status':'Resolved'}
        assert 'Request changed' in c.post('/requests/'+reference+'/status',data=stale).text
        assert 'Resolved' in c.post('/requests/'+reference+'/status',data={**stale,'revision':'1'}).text
    with TestClient(create_app(database)) as c:
        assert 'Resolved' in c.get('/requests/'+reference).text
        assert reference in c.get('/requests',params={'customer_id':customer,'status':'Resolved'}).text


def test_requests_reject_cross_customer_invalid_csrf_and_denied_access(tmp_path):
    database=tmp_path/'bank.db'
    with TestClient(create_app(database)) as c:
        token=csrf(c.get('/requests/new/statement'))
        values=dict(csrf=token,customer_id='C-205',resource_id='AC-4104',notes='Synthetic request')
        assert 'does not belong' in c.post('/requests/review/statement',data=values).text
        assert 'Permission denied' in c.post('/requests/review/statement',data={**values,'csrf':'wrong'}).text
        assert 'Customer not found' in c.post('/requests/review/statement',data={**values,'customer_id':'C-999'}).text
        c.get('/?scenario=permission-denied')
        assert 'Permission denied' in c.post('/requests/review/statement',data=values).text
        with connect(database) as db:
            assert db.execute('SELECT COUNT(*) AS n FROM service_requests').fetchone()['n']==3
