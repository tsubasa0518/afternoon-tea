"""Staging-only live extraction and source-level audit. Never operates booking UI."""
import argparse
import datetime as dt
from urllib.parse import urlsplit
from .data import create_data,JST
from .master import ROOT,load_master,dumps
from .pipeline import staging_directory,protected_files,build
from .public_research import Seeds
from .research import Browser
from .extraction import apply_page

PILOT=[(1,'https://restaurant.ikyu.com/112520/'),
       (1,'https://tabelog.com/tokyo/A1302/A130202/13226051/party/232732756/'),
       (14,'https://www.tablecheck.com/en/shops/hotel-chinzanso-tokyo-jardin/reserve'),
       (4,'https://www.tablecheck.com/ja/capitolhoteltokyu-lounge'),
       (1,'https://www.tablecheck.com/en/shops/palacehoteltokyo-the-palace-lounge/reserve')]

def run(limit=5,pilot=False,seconds=300):
    protected_files();master=load_master();now=dt.datetime.now(JST)
    out=staging_directory()/('extract-'+now.strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    data=create_data(master,now.date().isoformat());data['metadata']['purpose']='research'
    seed=Seeds();seed.feed((ROOT/'docs/index.html').read_text())
    urls=[]
    if pilot:urls=PILOT
    else:
        groups={n:[u for a,u in seed.urls if a==n] for n in range(1,15)}
        for i in range(max(map(len,groups.values()),default=0)):
            for n,g in groups.items():
                if i<len(g):urls.append((n,g[i]))
    audit={'period':data['period'],'pages':[],'all_tokyo_coverage_verified':False,'publishable':False,
           'candidates':[dict(s,status='unresearched') for s in master['candidates']],
           'limitations':['Source URLs are discovery seeds. Master identity and source genre must pass strict gates.',
                          'Area list/new opening/hotel inventory searches remain incomplete.'],
           'master_status':{s['id']:{'name':s['name'],'status':'unresearched','reason':'No uniquely matched eligible public plan has been established'} for a in master['areas'] for g in a['cats'].values() for s in g['shops']}}
    browser=Browser(delay=1,timeout=8,max_requests=limit*2+8)
    def save():
        audit['requests']=browser.count;audit['blocked_operations']=browser.transport.audit
        for name,obj in [('audit.json',audit),('data_'+data['period']['start']+'.json',data)]:
            tmp=out/('.'+name+'.tmp');tmp.write_text(dumps(obj));tmp.replace(out/name)
    save();began=__import__('time').monotonic()
    for area,url in urls[:limit]:
        if __import__('time').monotonic()-began>seconds:audit['stop_reason']='time_budget';break
        row={'area':area,'url':url,'status':'unresolved'}
        try:
            raw=browser.fetch(url)
            row.update(fetch='success',extraction=apply_page(data,master,raw,url))
            if row['extraction']['status']=='confirmed':
                row['status']='confirmed';audit['master_status'][row['extraction']['master_id']]['status']='confirmed'
        except Exception as e:row.update(fetch='failed',reason=str(e))
        audit['pages'].append(row);save()
        if browser.transport.audit:audit['stop_reason']='forbidden_operation';save();break
    audit['areas']=[{'no':n,'pages':sum(p['area']==n for p in audit['pages']),'confirmed':sum(p['area']==n and p['status']=='confirmed' for p in audit['pages']),'status':'incomplete'} for n in range(1,15)]
    audit['confirmed_shops']=sum(v['status']=='confirmed' for v in audit['master_status'].values())
    audit['confirmed_plans']=sum(len(s['plans']) for a in data['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed')
    save();html=build(data);audit['html']=str(html);save();return out,audit

def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',action='store_true');p.add_argument('--limit',type=int,default=5);p.add_argument('--seconds',type=int,default=300);a=p.parse_args()
    if not 1<=a.limit<=200 or not 1<=a.seconds<=1800:p.error('bounded positive limits required')
    out,audit=run(a.limit,a.pilot,a.seconds);print(dumps({'output':str(out),'confirmed':audit['confirmed_shops'],'plans':audit['confirmed_plans'],'html':audit['html']}))
if __name__=='__main__':main()
