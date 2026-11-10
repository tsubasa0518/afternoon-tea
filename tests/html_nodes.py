"""Inspect locally generated HTML in renderer tests; never fetch a page."""
import re
from html.parser import HTMLParser
VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
class Node:
    def __init__(self,tag='',attrs=None): self.tag=tag;self.attrs=attrs or {};self.children=[];self.parent=None
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
        node=Node(tag,dict(attrs));node.parent=self.stack[-1];self.stack[-1].children.append(node)
        if tag not in VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs): self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag: self.stack=self.stack[:i];break
    def handle_data(self,data):
        if not any(n.tag in ('script','style','noscript','template') for n in self.stack):self.stack[-1].children.append(data)
