"""Conservative site adapters: observations are not confirmation until identity/policy gates pass."""
import datetime as dt
import hashlib
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit
from .data import unknown_plan
from .validation import normalize, allowed_url

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
class Node:
    def __init__(self,tag='',attrs=None): self.tag=tag;self.attrs=attrs or {};self.children=[]
    @property
    def text(self): return re.sub(r'\s+',' ',' '.join(c if isinstance(c,str) else c.text for c in self.children)).strip()
    def find(self,tag=None,cls=None):
        result=[]
        for c in self.children:
            if isinstance(c,Node):
                if (tag is None or c.tag==tag) and (cls is None or cls in c.attrs.get('class','').split()):result.append(c)
                result.extend(c.find(tag,cls))
        return result
class Document(HTMLParser):
    def __init__(self,raw):
        super().__init__(convert_charrefs=True);self.root=Node();self.stack=[self.root];self.feed(raw)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,dict(attrs));self.stack[-1].children.append(node)
        if tag not in VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs): self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag: self.stack=self.stack[:i];break
    def handle_data(self,data):
        if not any(n.tag in ('script','style','noscript','template') for n in self.stack):self.stack[-1].children.append(data)
def first(nodes):return nodes[0].text if nodes else ''
def observation(value,quote,url,checked):
    return {'value':value,'url':url,'checked_on':checked,'quote':quote,'status':'observed'}
def extract(raw,url,checked):
    allowed_url(url);root=Document(raw).root;host=urlsplit(url).hostname
    site='ik' if host=='restaurant.ikyu.com' else ('tb' if host=='tabelog.com' else 'tc')
    text=root.text;identity={};blocks=[]
    # Identity comes from dedicated identity fields, never footer recommendations.
    for tr in root.find('tr'):
        th=first(tr.find('th'));td=first(tr.find('td'))
        if th in ('店名','住所','交通手段','ジャンル'):identity[th]=td
    if site=='tb':
        blocks=root.find(cls='course-dtl')
        identity.setdefault('店名',first(root.find(cls='display-name')))
    elif site=='tc':
        blocks=root.find(cls='menu-item')
        title=first(root.find('title'));identity['店名']=title.split(' - TableCheck')[0]
    else:
        # Only explicit plan detail pages; overview text cannot establish a plan.
        if re.fullmatch(r'/\d+/plan\d+/?',urlsplit(url).path):
            headings=root.find('h1');blocks=[root] if any('アフタヌーンティー' in h.text for h in headings) else []
        identity['店名']=first(root.find('h1'))
    result={'site':site,'url':url,'checked_on':checked,'sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'identity':identity,'plans':[],'status':'unresolved','reasons':[]}
    seen=set()
    for block in blocks:
        b=block.text
        title=(first(block.find(cls='course-dtl__course-title')) if site=='tb' else
               first(block.find(cls='menu-item-name')) if site=='tc' else first([h for h in block.find('h1') if 'アフタヌーンティー' in h.text]))
        if not re.search(r'アフタヌーンティー|afternoon tea',title,re.I):continue
        plan=unknown_plan();fields={}
        def put(key,value,quote):
            if quote and quote in b:
                plan[key]=value;fields[key]=observation(value,quote,url,checked)
        put('theme',title,title)
        menu=first(block.find(cls='course-dtl__desc')) if site=='tb' else first(block.find(cls='menu-item-description'))
        if site=='ik':
            m=re.search(r'メニュー (.+?) (?:プラン紹介|キャンセルポリシー)',b);menu=m.group(1) if m else ''
        # Specific menu content is required; generic AT/booking words are insufficient.
        menu_ok=bool(menu and re.search('スコーン|マカロン|ケーキ|サンド|タルト|セイボリー',menu))
        booking_nodes=(block.find(cls='course-dtl__reserve-btn') if site=='tb' else
                       block.find(cls='menu-item-order-select') if site=='tc' else
                       [n for n in block.find('button') if 'このプランを予約する' in n.text])
        booking=bool(booking_nodes)
        price=first(block.find(cls='course-dtl__price-num')) if site=='tb' else first(block.find(cls='menu-item-price'))
        if site=='ik':
            m=re.search(r'(?:通常価格|税サ込)\s*[¥￥]?\s*[\d,]+\s*円',b);price=m.group() if m else ''
        # Never convert tax-exclusive prices or choose between competing prices.
        if price and not re.search('税抜|割引|OFF|オフ|→',price,re.I) and re.search('税サ込|税・サービス料込|税金・サービス料込み',price):
            nums=re.findall(r'[0-9][0-9,]*',price)
            if len(nums)==1 and (not re.search('割引|OFF|オフ',title,re.I) or '通常価格' in price):
                put('price_min',int(nums[0].replace(',','')),price);put('price_text',price,price)
        table={first(tr.find('th')):first(tr.find('td')) for tr in block.find('tr')}
        days=table.get('利用可能曜日') or first(block.find(cls='menu-item-days'))
        if days:put('days_text',days,days)
        if days and re.search('平日|月.*金',days):put('wd','on',days)
        if days and re.search('土.*日.*祝',days):put('we','on',days)
        times=table.get('利用可能時間')
        if times:put('time_text',times,times)
        # ISO-year dates only, and only inside explicitly labelled offering-period text.
        m=re.search(r'(?:提供期間|ご提供期間|販売期間)\s*[:：]?\s*(\d{4}[-/]\d{2}[-/]\d{2})\s*[～〜~]\s*(\d{4}[-/]\d{2}[-/]\d{2})',b)
        if m:
            try:
                st,en=(dt.date.fromisoformat(v.replace('/','-')) for v in m.groups())
                if st<=en:put('start',str(st),m.group());put('end',str(en),m.group())
            except ValueError:pass
        tags=[k for k,w in [('macaron','マカロン'),('scone','スコーン'),('parfait','パフェ')] if w in menu]
        if tags and not re.search('追加|オプション|別料金',menu):put('sw',tags,menu)
        meal=None
        if site=='ik':
            # Meal band must be explicit adjacent to the plan heading; unrelated lunch links do not qualify.
            m=re.search(r'(ランチ|朝食|ディナー|ティー)\s*'+re.escape(title),b)
            meal={'ランチ':'lunch','朝食':'breakfast'}.get(m.group(1)) if m else None
        eligible=menu_ok and booking and (site!='ik' or meal in ('lunch','breakfast'))
        key=(normalize(title),plan['start'],plan['end'],plan['price_min'],plan['days_text'],plan['time_text'],menu)
        if key in seen:continue
        seen.add(key)
        result['plans'].append({'plan':plan,'fields':fields,'menu':observation(menu,menu,url,checked),
                                'booking':observation(booking,first(booking_nodes),url,checked),'meal':meal,
                                'eligible_document':eligible,'unknown_fields':[k for k,v in plan.items() if v is None]})
    if not result['plans']:result['reasons'].append('supported_plan_structure_not_found')
    return result

def match_master(result,source):
    """Exact identity plus station evidence; separate hotel lounges must both match."""
    name=normalize(result['identity'].get('店名',''));expected=source['name']
    parts=re.split('[（(]',expected);base=normalize(parts[0])
    if not base or name not in (base,normalize(expected)):return False
    if len(parts)>1:
        lounge=normalize(parts[1].rstrip('）)'))
        if lounge and name != normalize(expected) and lounge not in normalize(result['identity'].get('住所','')):return False
    return normalize(source['station']) in normalize(result['identity'].get('交通手段',''))

def apply_page(dataset,master,raw,url):
    """Re-extract original HTML before promotion; caller cannot supply fabricated observations."""
    from .validation import expected_category
    result=extract(raw,url,dataset['generated'])
    matches=[(a,c,s) for a in master['areas'] for c,g in a['cats'].items() for s in g['shops'] if match_master(result,s)]
    if len(matches)!=1:
        result['reasons'].append('identity_not_uniquely_matched');return result
    area,cat,source=matches[0]
    genres=re.split('[、／/]',result['identity'].get('ジャンル',''))
    spec=__import__('pathlib').Path(__file__).resolve().parents[1]/'research_spec.md'
    banned=[]
    for line in spec.read_text().splitlines():
        if line.startswith('- ') and ('系：' in line or line.startswith('- その他：')):banned.extend(line.split('：',1)[1].split('／'))
    if any(g in banned for g in genres):
        result['reasons'].append('excluded_genre');return result
    if not any(g in ('カフェ','ラウンジ','喫茶','スイーツ','アフタヌーンティー') for g in genres):
        result['reasons'].append('classification_not_verified');return result
    plans=[p for p in result['plans'] if p['eligible_document']]
    start,end=dataset['period']['start'],dataset['period']['end']
    plans=[p for p in plans if not (p['plan']['end'] and p['plan']['end']<start or p['plan']['start'] and p['plan']['start']>end)]
    if not plans:
        result['reasons'].append('no_eligible_plan_document');return result
    group_area=dataset['areas'][area['no']-1]
    shop=next((s for g in group_area['cats'].values() for s in g['shops'] if s.get('master_id')==source['id']),None)
    if shop is None or shop['research']['status']=='confirmed':
        result['reasons'].append('already_processed_or_missing_master');return result
    # Hotel/lounges require explicit hotel identity as well as source match.
    in_hotel=cat!='cafe'
    if in_hotel and 'ホテル' not in result['identity'].get('店名',''):
        result['reasons'].append('hotel_identity_not_verified');return result
    shop['plans']=[p['plan'] for p in plans];shop['links']=[{'site':result['site'],'url':url}];shop['links_note']='確認済み'
    evidence={}
    for i,p in enumerate(plans):
        for k,v in p['fields'].items():evidence[f'/plans/{i}/{k}']={k2:v[k2] for k2 in ('url','checked_on','quote')}
    p=plans[0]
    evidence['reservation']={'url':url,'checked_on':dataset['generated'],'quote':p['menu']['quote'],'booking_quote':p['booking']['quote'],'booking':True,'menu':True,'meal':p['meal']}
    evidence['classification']={'url':url,'checked_on':dataset['generated'],'quote':result['identity']['ジャンル']}
    shop['research'].update(status='confirmed',checked_on=dataset['generated'],in_hotel=in_hotel,error=None,evidence=evidence,genres=genres)
    target=expected_category(shop)
    for g in group_area['cats'].values():
        if shop in g['shops']:g['shops'].remove(shop)
    group_area['cats'][target]['shops'].append(shop)
    for g in group_area['cats'].values():
        states=[s['research']['status'] for s in g['shops']]
        if 'confirmed' in states:g.update(status='ok',research={'status':'confirmed' if all(x=='confirmed' for x in states) else 'partial','checks':{}})
    result['status']='confirmed';result['master_id']=source['id']
    return result
