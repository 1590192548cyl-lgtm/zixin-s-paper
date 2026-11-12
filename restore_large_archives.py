"""Verify/rejoin local data archives only. Never run analysis or contact a server."""
from pathlib import Path
import hashlib,json,shutil
root=Path(__file__).resolve().parent
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
m=json.loads((root/'ANALYSIS_DATA_MANIFEST.json').read_text())
for a in m['archives']:
    target=root/a['file']
    if a['parts']:
        for p in a['parts']:
            assert digest(root/p['file'])==p['sha256'],p['file']
        if not target.exists():
            with target.open('xb') as out:
                for p in a['parts']:
                    with (root/p['file']).open('rb') as src:shutil.copyfileobj(src,out,1048576)
    assert target.stat().st_size==a['bytes'] and digest(target)==a['sha256'],a['file']
    print('PASS',a['file'])
print('All archives verified. Extract ZIP files into the same directory; no models were run.')
