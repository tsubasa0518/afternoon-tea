"""Bounded, anonymous public-document confirmation pilot. No booking interaction."""
import datetime as dt
from .data import create_data,JST
from .master import load_master,dumps
from .pipeline import staging_directory,protected_files,build
from .research import Browser
from .extraction import apply_page
from .read_only import ForbiddenOperation

TARGETS=[('master-070','https://www.tablecheck.com/ja/shops/hotel-chinzanso-tokyo-jardin/reserve'),
         ('master-010','https://www.tablecheck.com/ja/shops/palacehoteltokyo-the-palace-lounge/reserve')]

def diagnosis(result):
    codes=[];reasons=result.get('reasons',[])
    if 'identity_not_uniquely_matched' in reasons:codes.append('C')
    if 'excluded_genre' in reasons:codes.append('D')
    if 'supported_plan_structure_not_found' in reasons:codes.append('I')
    plans=[]
    for p in result.get('plans',[]):
        pc=[];v=p['plan']
        if not p['menu_verified']:pc.append('B')
        if not p['booking_verified']:pc.append('E')
        if v['price_min'] is None:pc.append('F')
        if v['start'] is None or v['end'] is None:pc.append('G')
        if v['time_text'] is None or (v['wd']=='off' and v['we']=='off'):pc.append('H')
        if not p['eligible_document'] and p['menu_verified'] and p['booking_verified']:pc.append('I')
        plans.append({'theme':v['theme'],'codes':pc,'eligible_document':p['eligible_document']})
    return {'page_codes':codes,'plans':plans}

def run():
    protected_files();master=load_master();now=dt.datetime.now(JST)
    out=staging_directory()/('step9-'+now.strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    data=create_data(master,str(now.date()));data['metadata']['purpose']='research'
    audit={'started_at':now.isoformat(),'period':data['period'],'pages':[],
           'all_area_research_complete':False,'publishable':False,'reservation_operations':0,
           'limitations':['Only known public source URLs are tested. Ikyu/Tabelog discovery for these venues is unresolved; no absence claim is made.',
                          'This pilot does not complete source-priority discovery, all-area lists, new shops, or hotel inventory.']}
    browser=Browser(delay=1,timeout=8,max_requests=8)
    def save():
        for name,obj in [('audit.json',audit),('data_'+data['generated']+'.json',data)]:
            tmp=out/('.'+name);tmp.write_text(dumps(obj));tmp.replace(out/name)
    save()
    for mid,url in TARGETS:
        row={'master_id':mid,'url':url,'priority_attempts':[
            {'site':'ik','status':'unresolved','reason':'No supported public discovery entry found; not proof of absence'},
            {'site':'tb','status':'unresolved','reason':'No supported public discovery entry found; not proof of absence'},
            {'site':'tc','status':'attempted','url':url}]}
        try:
            raw=browser.fetch(url);(out/(mid+'.html')).write_text(raw)
            r=apply_page(data,master,raw,url);row.update(fetch='success',extraction=r,diagnosis=diagnosis(r))
        except ForbiddenOperation as error:
            row.update(fetch='blocked',reason=str(error),forbidden=True,diagnosis={'page_codes':['A'],'plans':[]})
        except Exception as error:row.update(fetch='failed',reason=str(error),diagnosis={'page_codes':['A'],'plans':[]})
        audit['pages'].append(row);save()
        if row.get('forbidden') or browser.transport.audit:audit['stop_reason']='forbidden_operation_detected';break
    unknown=[s for a in data['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']!='confirmed']
    confirmed=[s for a in data['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed']
    data['notes']['status']='調査未完了。確認済み店舗でも価格・期間・曜日・評価の不明値は保持。未確認店舗：'+'／'.join(s['name'] for s in unknown)
    audit.update(confirmed_shops=len(confirmed),confirmed_plans=sum(len(s['plans']) for s in confirmed),
                 unresolved_master=[{'master_id':s['master_id'],'name':s['master_name'],'reason':'Full eligible source verification not completed'} for s in unknown],
                 candidates=[dict(c,status='unresearched') for c in master['candidates']],
                 areas=[{'no':a['no'],'confirmed':sum(s['research']['status']=='confirmed' for g in a['cats'].values() for s in g['shops']),'status':'incomplete'} for a in data['areas']],
                 requests=browser.count,blocked_operations=browser.transport.audit)
    save();protected_files()
    # A zero-card HTML is not accepted as a successful Step 9 artifact.
    if not confirmed:
        audit['result']='no_confirmed_stores';save();return out,audit
    html=build(data);audit.update(result='confirmed_store_html_generated',html=str(html));save();return out,audit

if __name__=='__main__':
    out,audit=run();print(dumps({'output':str(out),'confirmed':audit['confirmed_shops'],'plans':audit['confirmed_plans'],'result':audit['result'],'html':audit.get('html')}))
