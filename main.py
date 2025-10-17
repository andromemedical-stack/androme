import os
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from odoo_client import OdooRPC
from woo_client import Woo
from mapping import map_sale_line

app = FastAPI(title='Woo ↔ Odoo SaaS Bridge')
odoo = OdooRPC()
woo = Woo()

class Ping(BaseModel):
    ok: bool = True

@app.get('/ping', response_model=Ping)
async def ping():
    return {'ok': True}

def _ensure_partner(order):
    billing = order.get('billing') or {}
    email = billing.get('email') or f"guest+{order['id']}@example.com"
    partner_ids = odoo.execute_kw('res.partner', 'search', [[('email', '=', email)]], {'limit': 1})
    if partner_ids:
        return partner_ids[0]
    vals = {
        'name': f"{billing.get('first_name','')} {billing.get('last_name','')}".strip() or email,
        'email': email,
        'phone': billing.get('phone'),
        'street': billing.get('address_1'),
        'street2': billing.get('address_2'),
        'city': billing.get('city'),
        'zip': billing.get('postcode'),
    }
    return odoo.execute_kw('res.partner', 'create', [vals])

def _find_or_create_product(line):
    sku = line.get('sku') or str(line.get('product_id'))
    ids = odoo.execute_kw('product.product', 'search', [[('default_code', '=', sku)]], {'limit': 1})
    if not ids:
        ids = odoo.execute_kw('product.product', 'search', [[('barcode', '=', sku)]], {'limit': 1})
    if ids:
        return ids[0]
    return odoo.execute_kw('product.product', 'create', [{
        'name': line.get('name') or f"Woo product {sku}",
        'default_code': sku,
        'lst_price': float(line.get('price') or 0.0),
        'type': 'product',
    }])

def _create_sale_order(order):
    ext_ref = f"WOO-{order['id']}"
    existing = odoo.execute_kw('sale.order', 'search', [[('client_order_ref', '=', ext_ref)]], {'limit': 1})
    if existing:
        return existing[0]
    partner_id = _ensure_partner(order)
    lines = []
    for l in order.get('line_items', []):
        pid = _find_or_create_product(l)
        m = map_sale_line(l)
        lines.append((0, 0, {
            'product_id': pid,
            'name': m['name'],
            'product_uom_qty': m['product_uom_qty'],
            'price_unit': m['price_unit'],
        }))
    so_id = odoo.execute_kw('sale.order', 'create', [{
        'partner_id': partner_id,
        'client_order_ref': ext_ref,
        'origin': 'WooCommerce',
    }])
    odoo.execute_kw('sale.order', 'write', [[so_id], {'order_line': lines}])
    if os.getenv('AUTO_CONFIRM_SALE', 'false').lower() == 'true':
        odoo.execute_kw('sale.order', 'action_confirm', [[so_id]])
    return so_id

@app.post('/webhook/woo/order')
async def woo_order_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get('X-WC-Webhook-Signature', '')
    if not Woo.verify_webhook(sig, raw):
        raise HTTPException(status_code=401, detail='Invalid webhook signature')
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')
    _create_sale_order(payload)
    return {'status': 'ok'}

@app.post('/sync/stock')
async def sync_stock():
    products = odoo.execute_kw('product.product', 'search_read', [[('sale_ok','=',True)]], {'fields': ['id','default_code','qty_available'], 'limit': 2000})
    for p in products:
        sku = p.get('default_code') or str(p['id'])
        found = woo.get('products', params={'sku': sku})
        if not found:
            continue
        prod_id = found[0]['id']
        woo.put(f'products/{prod_id}', data={'manage_stock': True, 'stock_quantity': int(p.get('qty_available') or 0)})
    return {'status': 'done'}
