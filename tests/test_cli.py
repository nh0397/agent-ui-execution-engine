"""CLI artifact decoding must not depend on the host code page."""
import json
import sys
from pathlib import Path
import pytest
from engine import cli,runtime
from engine.contracts import Result


def test_cli_preserves_unicode_targets_on_non_utf8_host(tmp_path,monkeypatch):
    source=json.loads(Path('capabilities/update-address.v1.json').read_text(encoding='utf-8'))
    source['steps'][0]['target']['name']='Open résumé →'
    artifact=tmp_path/'unicode.json'
    artifact.write_text(json.dumps(source,ensure_ascii=False),encoding='utf-8')
    original=Path.read_text
    def windows_read(self,encoding=None,errors=None):
        return original(self,encoding=encoding or 'cp1252',errors=errors)
    monkeypatch.setattr(Path,'read_text',windows_read)
    called=[]
    def replay(capability,**options):
        called.append(capability.steps[0].target.name)
        return Result(status='success',code='completed',run_id='test')
    monkeypatch.setattr(runtime,'replay',replay)
    monkeypatch.setattr(sys,'argv',['engine.cli','replay','--capability',str(artifact),'--inputs','config/inputs-b.json'])
    with pytest.raises(SystemExit) as result:cli.main()
    assert result.value.code==0
    assert called==['Open résumé →']
