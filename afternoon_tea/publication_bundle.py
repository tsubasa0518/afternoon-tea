"""Hash-bound publication preview and isolated overwrite rehearsal.

There is intentionally no production Pages client. Only .staging may be written.
Approval context is supplied by tests/trusted future workflow, never a CLI flag.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from .master import ROOT,load_master
from .pipeline import protected_files
from .publication_quality import evaluate,DEFAULTS,report_destination
from .publication_safety import current_evidence
from .research_store import atomic_json
from .validation import load_json,validate_data
from .html_validation import validate_html

FILES=('data.json','audit.json','quality_report.json','index.html')
def sha(content):return hashlib.sha256(content).hexdigest()

def prepare(data_path,audit_path,html_path,baseline_path,destination,run_id,commit_sha):
    protected_files()
    destination=report_destination(Path(destination)/'manifest.json').parent
    if destination.exists() and any(destination.iterdir()):raise ValueError('bundle_destination_not_empty')
    data=load_json(data_path);audit=load_json(audit_path);html=Path(html_path).read_text()
    validate_data(data,load_master());validate_html(html,data)
    if audit.get('current_run',{}).get('id')!=run_id:raise ValueError('run_identity_not_verified')
    # Research quality only; trusted authorization is independently required by rehearse.
    policy={**DEFAULTS,'require_first_migration_approval':False}
    report=evaluate(data,audit,html,Path(baseline_path).read_text(),policy)
    destination.mkdir(parents=True,exist_ok=True)
    for name,content in [('data.json',Path(data_path).read_bytes()),('audit.json',Path(audit_path).read_bytes()),('index.html',Path(html_path).read_bytes())]:
        (destination/name).write_bytes(content)
    atomic_json(destination/'quality_report.json',report)
    manifest={'schema':1,'run_id':run_id,'commit_sha':commit_sha,'files':{n:sha((destination/n).read_bytes()) for n in FILES},'baseline_sha256':sha(Path(baseline_path).read_bytes()),'production_enabled':False}
    atomic_json(destination/'manifest.json',manifest)
    return manifest

def verify(bundle,expected_run,expected_commit):
    bundle=Path(bundle);m=load_json(bundle/'manifest.json')
    if m.get('schema')!=1 or m.get('run_id')!=expected_run or m.get('commit_sha')!=expected_commit:raise ValueError('manifest_identity_mismatch')
    if set(m.get('files',{}))!=set(FILES):raise ValueError('manifest_files_invalid')
    for name in FILES:
        p=bundle/name
        if p.is_symlink() or sha(p.read_bytes())!=m['files'][name]:raise ValueError('artifact_hash_mismatch:'+name)
    data=load_json(bundle/'data.json');audit=load_json(bundle/'audit.json');quality=load_json(bundle/'quality_report.json')
    validate_data(data,load_master());validate_html((bundle/'index.html').read_text(),data)
    if audit.get('current_run',{}).get('id')!=expected_run or not current_evidence(data,audit):raise ValueError('fresh_evidence_required')
    if quality.get('status')!='APPROVED_FOR_PUBLICATION' or quality.get('publishable') is not True:raise ValueError('quality_not_approved')
    return m

def rehearse(bundle,target,run_id,commit_sha,flags,authorization,ci_passed,after_replace=None):
    """Isolated tests only. Refuse all repository/public destinations outside .staging."""
    target=report_destination(target);protected_files()
    if flags!={'WEEKLY_RESEARCH_ENABLED':True,'WEEKLY_PUBLICATION_ENABLED':True}:raise ValueError('publication_disabled')
    if ci_passed is not True:raise ValueError('ci_not_verified')
    m=verify(bundle,run_id,commit_sha)
    # This context must eventually come from a required-reviewer Environment job,
    # not user-authored artifact JSON. No CLI exposes it in this implementation.
    expected={'run_id':run_id,'html_sha256':m['files']['index.html'],'data_sha256':m['files']['data.json']}
    if authorization.get('kind') not in ('initial_environment_approval','successful_migration_receipt'):raise ValueError('approval_missing')
    if any(authorization.get(k)!=v for k,v in expected.items()):raise ValueError('approval_identity_mismatch')
    if authorization.get('kind')=='initial_environment_approval' and authorization.get('required_reviewers_verified') is not True:raise ValueError('reviewers_not_verified')
    previous=target.read_bytes() if target.exists() else None
    target.parent.mkdir(parents=True,exist_ok=True)
    content=(Path(bundle)/'index.html').read_bytes()
    def replace_bytes(value):
        fd,name=tempfile.mkstemp(dir=target.parent,prefix='.publication-')
        try:
            with os.fdopen(fd,'wb') as f:f.write(value);f.flush();os.fsync(f.fileno())
            os.replace(name,target)
        finally:
            if os.path.exists(name):os.unlink(name)
    try:
        if previous is not None and sha(previous)!=m['baseline_sha256']:raise ValueError('baseline_changed')
        replace_bytes(content)
        if sha(target.read_bytes())!=m['files']['index.html']:raise ValueError('published_hash_mismatch')
        if after_replace:after_replace(target)
    except BaseException:
        if previous is not None:replace_bytes(previous)
        elif target.exists():target.unlink()
        raise
    return {'run_id':run_id,'commit_sha':commit_sha,'html_sha256':sha(content),'sandbox_only':True}
