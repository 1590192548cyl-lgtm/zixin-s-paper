"""Configure/copy a separate workspace only. Never executes research programs."""
from pathlib import Path
import argparse,ast,hashlib,json,shutil,sys

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def read_config(file):
    file=Path(file).resolve();c=json.loads(file.read_text());base=Path(c['package_root'])
    if not base.is_absolute():base=file.parent/base
    c['_base']=base.resolve()
    target=Path(c['working_root']);c['_target']=(target if target.is_absolute() else c['_base']/target).resolve()
    assert c.get('execute_analysis') is False,'This tool cannot execute analysis.'
    return c

def replacements(target):
    return [
      ('/Users/macpro/Desktop/2008年控制变量下载清单_20261104',str(target/'baseline_2008')),
      ('/Users/macpro/Desktop/控制变量',str(target/'thesis/控制变量')),
      ('/Users/macpro/Desktop/毕业论文',str(target/'thesis')),
      ('/Users/macpro/Documents/New project',str(target/'workspace')),
    ]

def translate(old,target):
    for a,b in replacements(target):
        if old==a or old.startswith(a+'/'):return Path(b+old[len(a):])
    return None

def safe(base,rel):
    p=(base/rel).resolve();assert p.is_relative_to(base.resolve()),rel;return p

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',default=str(Path(__file__).with_name('rebuild_paths.json')))
    ap.add_argument('--materialize',action='store_true',help='Copy checked inputs to a NEW isolated directory; never run models.')
    args=ap.parse_args();c=read_config(args.config);base=c['_base'];target=c['_target']
    registry=json.loads((Path(args.config).resolve().parent/'REBUILD_INPUT_REGISTER.json').read_text())
    problems=[]
    for r in registry:
        p=safe(base,r['package_path'])
        if not p.is_file():problems.append(dict(role=r['role'],path=str(p),issue='missing; download/extract the named old and new archives first'))
        elif p.stat().st_size!=r['bytes'] or digest(p)!=r['sha256']:problems.append(dict(role=r['role'],path=str(p),issue='size or SHA256 differs; do not substitute another version'))
    if problems:
        print(json.dumps(dict(status='INPUT_CHECK_FAILED',problems=problems),ensure_ascii=False,indent=2));return 2
    if not args.materialize:
        print(json.dumps(dict(status='INPUT_CHECK_PASS',registered_inputs=len(registry),working_root=str(target),writes=0,analysis_runs=0),ensure_ascii=False,indent=2));return 0
    assert not target.exists(),'Working root already exists. Pick a NEW directory; never overwrite snapshots.'
    assert not base.is_relative_to(target),'Working root must not contain the package root.'
    target.mkdir(parents=True);changes=[];copied={}
    def copy(p,dst,h):
        assert dst.is_relative_to(target)
        if dst.exists():assert digest(dst)==h;return
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst);assert digest(dst)==h
        copied[str(dst.relative_to(target))]=h
    # Fully restored archival workspace. Raw snapshots in base/analysis_data never change.
    am=base/'ANALYSIS_DATA_MANIFEST.json'
    if am.is_file():
        m=json.loads(am.read_text());canonical={r['source_relative_path']:r for r in m['files']}
        for r in m['files']:
            rel=r['source_relative_path']
            if rel.startswith('workspace/'):
                p=safe(base,'analysis_data/'+rel)
                if p.is_file():copy(p,target/rel,r['sha256'])
        for r in m['aliases']:
            if r['original'].startswith('workspace/'):
                p=safe(base,'analysis_data/'+r['identical_content'])
                if p.is_file():copy(p,target/r['original'],r['sha256'])
    for r in registry:
        dest=translate(r['original_path'],target)
        if dest:copy(safe(base,r['package_path']),dest,r['sha256'])
    # Working-code copies receive ONLY explicit absolute-path-prefix replacements.
    # Original code remains byte-identical in downloaded archives and analysis_data.
    for p in sorted((target/'workspace').rglob('*')):
        if not p.is_file() or p.suffix not in {'.py','.do'}:continue
        before=p.read_text();after=before
        for a,b in replacements(target):after=after.replace(a,b)
        if before!=after:
            if p.suffix=='.py':ast.parse(after)
            changes.append(dict(file=str(p.relative_to(target)),source_sha256=digest(p),replacements='absolute directory prefixes only',research_program_executed=False))
            p.write_text(after)
    (target/'PATH_CONFIGURATION_RECEIPT.json').write_text(json.dumps(dict(raw_inputs_copied=len(copied),path_adapted_code=changes,analysis_runs=0,warning='Historical completion guards and source self-hashes remain. Do not bypass them or run archival launch scripts automatically.'),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='ISOLATED_WORKSPACE_PREPARED',working_root=str(target),raw_inputs_copied=len(copied),path_adapted_scripts=len(changes),analysis_runs=0),ensure_ascii=False,indent=2));return 0

if __name__=='__main__':sys.exit(main())
