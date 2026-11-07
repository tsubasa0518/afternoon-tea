"""Decode bounded public JSON-LD without executing scripts or requesting resources."""
import json
from html.parser import HTMLParser
from urllib.parse import urlsplit

class LD(HTMLParser):
    def __init__(self,raw):
        super().__init__();self.active=False;self.parts=[];self.documents=[];self.oversized=False;self.feed(raw)
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.active=dict(attrs).get('type','').lower()=='application/ld+json';self.parts=[];self.oversized=False
    def handle_data(self,data):
        if self.active:
            if sum(map(len,self.parts))+len(data)>200000:self.oversized=True
            elif not self.oversized:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            if self.oversized:self.active=False;return
            text=''.join(self.parts)
            try:self.documents.append((json.loads(text),text))
            except (ValueError,RecursionError):pass
            self.active=False

def identity(raw,url):
    found=[];page=urlsplit(url)
    def walk(obj,quote,depth=0):
        if depth>12:return
        if isinstance(obj,list):
            for item in obj[:100]:walk(item,quote,depth+1)
        elif isinstance(obj,dict):
            types=obj.get('@type',[]);types=[types] if isinstance(types,str) else types
            if isinstance(types,list) and set(types)&{'Restaurant','CafeOrCoffeeShop','Hotel'}:
                target=urlsplit(obj.get('url',''))
                # Corroborate the entity with this exact document or its Ikyu restaurant root.
                same=(target.hostname==page.hostname and (target.path.rstrip('/')==page.path.rstrip('/') or
                      page.hostname=='restaurant.ikyu.com' and target.path.strip('/').isdigit() and page.path.startswith('/'+target.path.strip('/')+'/')))
                if same and isinstance(obj.get('name'),str) and isinstance(obj.get('address'),dict):
                    found.append({'name':obj['name'],'alternateName':obj.get('alternateName',[]),'address':obj['address'],
                                  'servesCuisine':obj.get('servesCuisine'), 'types':types,'quote':quote})
            if '@graph' in obj:walk(obj['@graph'],quote,depth+1)
    for obj,quote in LD(raw).documents:walk(obj,quote)
    return found[0] if len(found)==1 else None
