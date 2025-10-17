import os

# .strip() = supprime les espaces, retours à la ligne, tabulations...
ODOO_URL    = (os.getenv("ODOO_URL") or "").strip()
ODOO_DB     = (os.getenv("ODOO_DB") or "").strip()
ODOO_LOGIN  = (os.getenv("ODOO_LOGIN") or "").strip()
ODOO_API_KEY= (os.getenv("ODOO_API_KEY") or "").strip()
JSONRPC_ENDPOINT = f"{ODOO_URL}/jsonrpc"

class OdooRPC:
    def __init__(self):
        self.uid = None

    def _jsonrpc(self, service, method, args):
        payload = {
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'service': service, 'method': method, 'args': args}
        }
        with httpx.Client(timeout=60.0) as client:
            r = client.post(JSONRPC_ENDPOINT, json=payload)
            r.raise_for_status()
            res = r.json()
            if 'error' in res:
                raise RuntimeError(res['error'])
            return res['result']

    def authenticate(self):
        self.uid = self._jsonrpc('common', 'authenticate', [ODOO_DB, ODOO_LOGIN, ODOO_API_KEY, {}])
        if not self.uid:
            raise RuntimeError('Odoo auth failed')
        return self.uid

    def execute_kw(self, model, method, args=None, kwargs=None):
        if self.uid is None:
            self.authenticate()
        return self._jsonrpc('object', 'execute_kw', [ODOO_DB, self.uid, ODOO_API_KEY, model, method, args or [], kwargs or {}])
