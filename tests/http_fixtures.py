"""In-memory response for the anonymous transport tests."""
import io
from email.message import Message

class Response(io.BytesIO):
    def __init__(self,url,raw,content_type='text/html; charset=utf-8'):
        super().__init__(raw.encode())
        self.url=url;self.status=200;self.headers=Message()
        self.headers['Content-Type']=content_type
    def geturl(self):return self.url
