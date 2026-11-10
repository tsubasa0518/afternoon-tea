"""Portable, bounded text evidence tied to a subject and hash-chained HTTP audit."""
import base64
import hashlib
import json
from pathlib import Path
import zlib
from .common import digest
from .read_only import check_url

MAX_TEXT_BYTES=256_000
MAX_BUNDLE_BYTES=1_500_000


def text_of(document):
    try:
        packed=base64.b64decode(document['text_zlib'],validate=True)
        if len(packed)>MAX_TEXT_BYTES: raise ValueError('evidence_archive_too_large')
        decoder=zlib.decompressobj()
        raw=decoder.decompress(packed,MAX_TEXT_BYTES+1)
        if len(raw)>MAX_TEXT_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError('evidence_text_too_large_or_invalid')
        if hashlib.sha256(raw).hexdigest()!=document['text_sha256']:
            raise ValueError('evidence_text_hash_mismatch')
        text=raw.decode('utf-8')
        from .routine_site import scan
        scan(raw)
        return text
    except (KeyError,TypeError,zlib.error,UnicodeError) as error:
        raise ValueError('invalid_evidence_text') from error


def save_document(campaign,subject,url,text,checked_at,page_sha256,audit_id,hosts=()):
    raw=text.encode('utf-8')
    if len(raw)>MAX_TEXT_BYTES: raise ValueError('evidence_text_too_large')
    check_url(url,public_hosts=hosts)
    document={'subject_id':subject,'url':url,'checked_at':checked_at,'page_sha256':page_sha256,
              'audit_id':audit_id,'text_sha256':hashlib.sha256(raw).hexdigest(),
              'public_hosts':sorted(hosts),'text_zlib':base64.b64encode(zlib.compress(raw)).decode('ascii')}
    text_of(document)
    key=digest(document)
    bundle=campaign.setdefault('documents',{})
    if len(json.dumps({**bundle,key:document}).encode())>MAX_BUNDLE_BYTES:
        raise ValueError('evidence_bundle_full_checkpoint_required')
    bundle[key]=document
    return key


def restore_documents(campaign,directory):
    """Restore exact acquired plain text in a fresh cloud checkout, never refetch."""
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    if root.is_symlink(): raise ValueError('unsafe_evidence_directory')
    for key,document in campaign.get('documents',{}).items():
        if key!=digest(document): raise ValueError('evidence_id_mismatch')
        text=text_of(document)
        target=root/(key+'.txt')
        if target.is_symlink(): raise ValueError('unsafe_evidence_file')
        target.write_text(text,encoding='utf-8')


def validate_audit(snapshot):
    """Verify chain and real request/response/document relationships, not flags alone."""
    try:
        if snapshot['complete'] is not True or snapshot['violations'] or snapshot['operations_executed']!=0:
            raise ValueError('research_audit_failed')
        previous=None;pending=set();successful=set();documents={};requests=0;request_resources={}
        events=snapshot['events']
        if not events: raise ValueError('research_audit_empty')
        for index,event in enumerate(events):
            if (event['seq']!=index or event['run_id']!=snapshot['run_id'] or event['previous']!=previous
                or event['sha256']!=digest({k:v for k,v in event.items() if k!='sha256'})):
                raise ValueError('research_audit_chain_invalid')
            previous=event['sha256']
            if event.get('violation') or event.get('status')=='forbidden':
                raise ValueError('research_audit_violation')
            if event['event']=='request':
                request=event['request_id']
                if request in pending or request in successful or event['method']!='GET':
                    raise ValueError('research_audit_request_invalid')
                pending.add(request);requests+=1;request_resources[request]=event['resource']['url_sha256']
            elif event['event']=='response':
                request=event['request_id']
                if request not in pending: raise ValueError('research_audit_response_invalid')
                pending.remove(request)
                if event['status']=='http_success':successful.add(request)
            elif event['event'] in ('document','evidence'):
                if event.get('status')!='success' or event['request_id'] not in successful:
                    raise ValueError('research_document_without_successful_request')
                if event['resource']['url_sha256']!=request_resources[event['request_id']]:
                    raise ValueError('research_audit_resource_mismatch')
                if event['event']=='evidence':documents[event['sha256']]=event
        if pending or requests!=snapshot['requests'] or previous!=snapshot['chain_sha256']:
            raise ValueError('research_audit_incomplete')
        return documents
    except (KeyError,TypeError) as error:
        raise ValueError('research_audit_schema_invalid') from error


def source_document(campaign,source,subject,audited_documents):
    try:
        document=campaign['documents'][source['document_id']]
        if digest(document)!=source['document_id']: raise ValueError('evidence_id_mismatch')
        if document['subject_id']!=subject or document['url']!=source['url']:
            raise ValueError('evidence_subject_or_url_mismatch')
        if document['checked_at']!=source['checked_at']: raise ValueError('evidence_timestamp_mismatch')
        check_url(source['url'],public_hosts=document.get('public_hosts',[]))
        event=audited_documents[document['audit_id']]
        if (event['resource']['url_sha256']!=hashlib.sha256(source['url'].encode()).hexdigest()
            or event['page_sha256']!=document['page_sha256'] or event.get('text_sha256')!=document['text_sha256']
            or event.get('subject_id')!=subject or event.get('fetched_at',event.get('at'))!=document['checked_at']):
            raise ValueError('evidence_acquisition_mismatch')
        text=text_of(document)
        if not isinstance(source['basis'],str) or not source['basis'].strip() or source['basis'] not in text:
            raise ValueError('evidence_basis_not_in_document')
        return text
    except (KeyError,TypeError) as error:
        raise ValueError('evidence_source_missing') from error


def archive_acquired_text(campaign,journal,subject,url,text,page_sha256,hosts=()):
    """Archive normalized text from an already audited download, with its original time.

    Also usable for official discovery pages: pass the collector's saved text,
    raw-page digest and the *same* acquisition journal. No download is performed.
    """
    url_sha=hashlib.sha256(url.encode()).hexdigest()
    origin=next((e for e in reversed(journal.events) if e['event']=='document' and
                 e.get('status')=='success' and e.get('page_sha256')==page_sha256 and
                 e.get('resource',{}).get('url_sha256')==url_sha),None)
    if origin is None:raise ValueError('audited_acquisition_missing')
    event=journal.record('evidence',status='success',request_id=origin['request_id'],
                         resource=origin['resource'],page_sha256=page_sha256,
                         subject_id=subject,text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                         fetched_at=origin['at'])
    key=save_document(campaign,subject,url,text,origin['at'],page_sha256,event['sha256'],hosts)
    campaign.setdefault('audit_segments',{})[journal.run_id]=journal.snapshot()
    return key
