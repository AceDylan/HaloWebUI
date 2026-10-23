#!/usr/bin/env python3
"""Check committed sample formats, full decoding, motion, and poster dimensions."""
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image
from render import SAMPLES, ROOT

root = ROOT / 'static/video-presets/v1'
for key, _, _ in SAMPLES:
    path = root / f'{key}.mp4'
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    assert len(info['streams']) == 1, (key, 'samples must be silent')
    stream = info['streams'][0]
    assert (stream['codec_name'], stream['width'], stream['height'], stream['pix_fmt'], stream['nb_frames']) == ('h264', 640, 360, 'yuv420p', '120'), key
    assert abs(float(info['format']['duration']) - 8) < .01, key
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-threads', '1', '-i', str(path), '-f', 'null', '-'], check=True)
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path), '-vf', 'fps=1,scale=160:90', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-threads', '1', '-'])
    size = 160 * 90 * 3
    assert len({hashlib.sha256(raw[i:i+size]).digest() for i in range(0, len(raw), size)}) >= 6, (key, 'insufficient motion')
    with Image.open(root / f'{key}.jpg') as poster:
        assert poster.size == (640, 360), key
    print(f'{key}: format, 8s duration, full decoding, motion and poster OK')
print(f'{len(SAMPLES)} samples verified')
