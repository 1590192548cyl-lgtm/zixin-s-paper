"""Verify and restore raw-source archive only; no variables or models are created."""
from pathlib import Path
import hashlib,json,shutil,zipfile
P=Path(__file__).resolve().parent
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
m=json.loads((P/'MINIMAL_REBUILD_ARCHIVE.json').read_text())
for r in m['parts']:assert sha(P/r['file'])==r['sha256'],r['file']
archive=P/m['archive']
if not archive.exists():
    with archive.open('xb') as out:
        for r in m['parts']:
            with (P/r['file']).open('rb') as f:shutil.copyfileobj(f,out,1048576)
assert sha(archive)==m['archive_sha256']
with zipfile.ZipFile(archive) as z:
    for r in m['source_files']:
        n=r['package_path'];dest=(P/n).resolve();assert dest.is_relative_to(P)
        if dest.exists():assert sha(dest)==r['sha256'];continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        with z.open(n) as src,dest.open('xb') as out:shutil.copyfileobj(src,out,1048576)
        assert sha(dest)==r['sha256']
print('PASS: verified original source files restored; no SYN, control construction or regression run.')
