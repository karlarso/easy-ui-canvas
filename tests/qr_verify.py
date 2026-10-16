#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Cross-check the inline JS QR encoder with independent decoders (zxing-cpp and OpenCV). usage: qr_verify.py [canvas.js] [outdir]  (default: ../assets/canvas.js and a temp dir)
Optional dependencies (not needed by the app): numpy, opencv-python, zxing-cpp, Pillow. Skips with exit 0 when they are missing."""
import json, subprocess, sys, random, os, tempfile
try:
    import numpy as np, cv2, zxingcpp
    from PIL import Image
except ImportError as error:
    print('SKIP: optional QR decoders missing (%s)' % error); sys.exit(0)
HERE = os.path.dirname(os.path.abspath(__file__))
js = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'assets', 'canvas.js')
out = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix='uic-qr-'); os.makedirs(out, exist_ok=True)
random.seed(7)
urls = [
 'http://127.0.0.1:4100/m/', 'http://203.0.113.5:4100/m/', 'http://203.0.113.5:4328/m/?rev=r1',
 'http://203.0.113.6:4876/m/', 'http://203.0.113.6:4876/m/?rev=r10', 'http://203.0.113.6:4899/m/?rev=r9',
 'http://203.0.113.5:4876/m/?rev=r33.1', 'https://host.example.test:4876/m/?rev=r10&start=goal-recommendations-c-external',
 'http://[fd12:3456:789a::1]:4100/m/?rev=r2', 'unicode test ✓ é — ñ ü ß',
]
# every version 1..10 at its exact capacity boundary (ECC M byte capacity) and one byte over
CAP = {1: 14, 2: 26, 3: 42, 4: 62, 5: 84, 6: 106, 7: 122, 8: 152, 9: 180, 10: 213}
for v, c in CAP.items():
    for n in (c, c + 1):
        if v == 10 and n == 214: continue
        urls.append('http://x/' + ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789-_/?=&.') for _ in range(n - 9)))
urls.append('A' * 214)  # too long -> must return null (version None)
json.dump(urls, open(out + '/inputs.json', 'w'), ensure_ascii=False)
subprocess.check_call(['node', os.path.dirname(os.path.abspath(__file__)) + '/qr_matrix.js', js, out + '/inputs.json', out + '/matrix.json'])
res = json.load(open(out + '/matrix.json')); ok = True; versions = set(); n_ok = 0
det = cv2.QRCodeDetector()
for i, r in enumerate(res):
    if r['version'] is None:
        good = len(r['text'].encode()) > 213; print('%s too-long -> null' % ('PASS' if good else 'FAIL'), len(r['text'])); ok &= good; continue
    rows = r['modules']; n = len(rows); q = 4; scale = 8
    img = np.full(((n + 2 * q) * scale,) * 2, 255, np.uint8)
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c == '1': img[(y + q) * scale:(y + q + 1) * scale, (x + q) * scale:(x + q + 1) * scale] = 0
    Image.fromarray(img).save('%s/qr-%02d-v%d.png' % (out, i, r['version']))
    zx = zxingcpp.read_barcodes(img)
    z = zx[0].text if zx else None
    zok = bool(zx) and zx[0].format == zxingcpp.BarcodeFormat.QRCode and z == r['text']
    cvtxt, _, _ = det.detectAndDecode(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    cok = cvtxt == r['text']
    good = zok and cok
    versions.add(r['version']); n_ok += good; ok &= good
    print('%s v%-2d mask%d len%-3d zxing=%s opencv=%s  %s' % ('PASS' if good else 'FAIL', r['version'], r['mask'], len(r['text'].encode()), zok, cok, r['text'][:60]))
print('versions covered:', sorted(versions), 'decoded ok: %d/%d' % (n_ok, sum(1 for r in res if r['version'])))
sys.exit(0 if ok else 1)
