"""Encode already-redacted step images. Never persist raw live browser frames."""
import json
import os
import re
import subprocess
import io
from pathlib import Path
from PIL import Image, ImageOps


def make_step_video(folder: Path, root: Path):
    destination = folder/'steps.webm'
    if destination.exists():
        return destination
    steps = json.loads((folder/'recording.json').read_text(encoding='utf-8'))
    names = [step[phase] for step in steps for phase in ('before','after')]
    if not names or len(names)>400 or any(not re.fullmatch(r'step-[0-9]{3}-(before|after)\.png', name) or not (folder/name).is_file() for name in names):
        raise ValueError('Recording images are incomplete')
    browser_root = Path(os.getenv('PLAYWRIGHT_BROWSERS_PATH', str(root/'.browsers')))
    binaries = list(browser_root.glob('ffmpeg-*/ffmpeg-win64.exe')) + list(browser_root.glob('ffmpeg-*/ffmpeg-linux'))
    if not binaries:
        raise ValueError('Video encoder is unavailable; install the Playwright browser dependencies')
    # Convert only already-masked images; no live unredacted frames enter this pipeline.
    frames = []
    for name in names:
        with Image.open(folder/name) as original:
            normalized = ImageOps.pad(original.convert('RGB'), (960,540), color='#f4f6f3')
            output = io.BytesIO()
            normalized.save(output, format='JPEG', quality=85)
            frames.append(output.getvalue())
    command = [str(binaries[0]), '-y', '-hide_banner', '-loglevel', 'error', '-f', 'image2pipe',
               '-framerate', '1', '-vcodec', 'mjpeg', '-i', 'pipe:0',
               '-an', '-c:v', 'libvpx', '-b:v', '700k', '-r', '12', str(folder/'steps.pending.webm')]
    try:
        result = subprocess.run(command, input=b''.join(frames),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
    except subprocess.TimeoutExpired:
        raise ValueError('Video encoding timed out; the step images remain available') from None
    if result.returncode:
        raise ValueError('Video encoding failed; the step images remain available')
    (folder/'steps.pending.webm').replace(destination)
    return destination
