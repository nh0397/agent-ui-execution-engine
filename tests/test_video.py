"""Video evidence must consume only the recorder's masked image filenames."""
import json
import pytest
from engine.video import make_step_video

@pytest.mark.parametrize('before', ['../private.png', '/private.png', 'step-001-before.png'])
def test_video_rejects_external_or_missing_images(tmp_path, before):
    (tmp_path/'recording.json').write_text(json.dumps([{'before':before,'after':'step-001-after.png'}]))
    with pytest.raises(ValueError, match='incomplete'):
        make_step_video(tmp_path,tmp_path)
