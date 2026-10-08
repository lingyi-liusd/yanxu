"""Public reader transport fixtures, no real network or relaxed address checks."""
import pathlib,sys,unittest
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import radar_fetch as reader


class Response:
    def __init__(self,body=b'<p>Public text</p>',media='text/html',status=200,location=None,encoding='identity'):
        self.body=body;self.status=status;self.headers={'Content-Type':media,'Content-Encoding':encoding,'Location':location}
    def getheader(self,key,default=None):return self.headers.get(key,default)
    def read(self,n):return self.body[:n]


class ReaderCase(unittest.TestCase):
    def fetch(self,responses,url='https://example.org/news'):
        responses=list(responses);self.requests=[];self.sockets=[]
        case=self
        class Connection:
            def __init__(self,*args,**kw):self.sock=None
            def request(self,method,path,headers):case.requests.append((method,path,headers,self.sock))
            def getresponse(self):return responses.pop(0)
            def close(self):pass
        def socket(address,**kw):
            case.sockets.append(address);return mock.Mock()
        with mock.patch.object(reader.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),\
             mock.patch.object(reader.socket,'create_connection',side_effect=socket),\
             mock.patch.object(reader.http.client,'HTTPConnection',Connection),\
             mock.patch.object(reader.ssl,'create_default_context') as ssl:
            ssl.return_value.wrap_socket.side_effect=lambda raw,**kw:raw
            value=reader.fetch_source(url)
            self.assertEqual(ssl.return_value.wrap_socket.call_args.kwargs['server_hostname'],'example.org')
            return value

    def test_dns_pin_html_normalization_and_no_cookies_or_credentials(self):
        value=self.fetch([Response(b'<script>ignore</script><style>hide</style><p>Public &amp; text</p>')])
        self.assertEqual(value['text'],'Public & text');self.assertEqual(len(value['hash']),64)
        self.assertEqual(self.sockets,[('8.8.8.8',443)])
        headers=self.requests[0][2]
        self.assertEqual(headers['Accept-Encoding'],'identity')
        self.assertNotIn('Cookie',headers);self.assertNotIn('Authorization',headers)

    def test_redirect_revalidates_target_and_preserves_final_url(self):
        value=self.fetch([Response(status=302,location='/new'),Response(b'new','text/plain')])
        self.assertEqual(value['url'],'https://example.org/new')
        self.assertEqual(len(self.sockets),2)
        with self.assertRaises(ValueError):self.fetch([Response(status=302,location='http://127.0.0.1/secret')])

    def test_invalid_bytes_empty_binary_compressed_large_and_http_failure(self):
        cases=[Response(b'\xff','text/plain'),Response(b'','text/plain'),Response(b'PDF','application/pdf'),
               Response(encoding='gzip'),Response(b'x'*(reader.MAX_BYTES+1),'text/plain'),
               Response(b'x'*(reader.MAX_TEXT+1),'text/plain'),Response(status=503)]
        for response in cases:
            with self.subTest(status=response.status,media=response.headers['Content-Type']):
                with self.assertRaises(ValueError):self.fetch([response])


if __name__=='__main__':unittest.main()
