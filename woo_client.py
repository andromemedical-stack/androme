import os, hmac, hashlib, base64, httpx

WOO_URL = os.getenv('WOO_URL')
WOO_CK = os.getenv('WOO_CK')
WOO_CS = os.getenv('WOO_CS')
WOO_WEBHOOK_SECRET = os.getenv('WOO_WEBHOOK_SECRET')

class Woo:
    def __init__(self):
        self.base = f"{WOO_URL.rstrip('/')}/wp-json/wc/v3"

    def _client(self):
        return httpx.Client(timeout=60.0)

    def get(self, endpoint, params=None):
        p = dict(params or {})
        p.update({'consumer_key': WOO_CK, 'consumer_secret': WOO_CS})
        with self._client() as c:
            r = c.get(f"{self.base}/{endpoint.lstrip('/')}", params=p)
            r.raise_for_status()
            return r.json()

    def put(self, endpoint, data=None, params=None):
        p = dict(params or {})
        p.update({'consumer_key': WOO_CK, 'consumer_secret': WOO_CS})
        with self._client() as c:
            r = c.put(f"{self.base}/{endpoint.lstrip('/')}", params=p, json=data or {})
            r.raise_for_status()
            return r.json()

    @staticmethod
    def verify_webhook(sig_header: str, raw_body: bytes) -> bool:
        if not WOO_WEBHOOK_SECRET:
            return True
        mac = hmac.new(WOO_WEBHOOK_SECRET.encode(), msg=raw_body, digestmod=hashlib.sha256)
        expected = base64.b64encode(mac.digest())
        try:
            return hmac.compare_digest(expected, sig_header.encode())
        except Exception:
            return False
