"""Per-execution provenance. Reading a checkpoint never creates a receipt."""
import datetime as dt
import hashlib
import uuid
from .communication_audit import CommunicationAudit
from .data import JST
from .master import dumps
from .publication_safety import digest

class RunContext:
    def __init__(self,directory=None,run_id=None):
        self.id=run_id or uuid.uuid4().hex
        self.started_at=dt.datetime.now(JST).isoformat()
        self.journal=CommunicationAudit(self.id,directory/'communication.jsonl' if directory else None)
        self.receipts={};self.evidence={}

    def confirm(self,shop,evidence,ref,document,verified_at):
        mid=shop['master_id']
        if mid in self.receipts:raise ValueError('duplicate_current_run_receipt')
        if evidence['item_id']!=mid or evidence['extraction'].get('master_id')!=mid:raise ValueError('receipt_wrong_shop')
        if document is None:raise ValueError('document_not_audited')
        key=digest(evidence);self.evidence[key]=evidence
        self.receipts[mid]={'master_id':mid,'run_id':self.id,'source_url':evidence['url'],'fetched_at':document['at'],
            'verified_at':verified_at,'shop_sha256':digest(shop),'restored_from_previous':False,
            'evidence_ref':ref,'evidence_sha256':key,'evidence_file_sha256':hashlib.sha256(dumps(evidence).encode()).hexdigest(),
            'http_request_id':document['request_id'],'page_sha256':document['page_sha256'],
            'matches':{'identity':True,'menu':True,'booking':True}}

    def snapshot(self,browser):
        audit=self.journal.snapshot(expected_requests=browser.count)
        tracked=(getattr(browser,'communication_audit',None) is self.journal and
                 getattr(getattr(browser,'transport',None),'communication_audit',None) is self.journal)
        audit['complete']=audit['complete'] and tracked
        if not audit['complete']:audit['operations_executed']=None
        return {'id':self.id,'started_at':self.started_at,'generated_at':dt.datetime.now(JST).isoformat(),
                'receipts':self.receipts,'evidence':self.evidence,'reservation_audit':audit}
