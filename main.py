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

    # 1) Cherche une variante existante par SKU (default_code) puis par barcode
    ids = odoo.execute_kw('product.product', 'search', [[('default_code', '=', sku)]], {'limit': 1})
    if not ids:
        ids = odoo.execute_kw('product.product', 'search', [[('barcode', '=', sku)]], {'limit': 1})
    if ids:
        return ids[0]

    # 2) Sinon, crée un TEMPLATE, puis récupère la variante
    name = line.get('name') or f"Woo product {sku}"
    price = float(line.get('price') or 0.0)

    # IMPORTANT: ne pas envoyer de champ de type (évite les erreurs de version/modules)
    tmpl_id = odoo.execute_kw('product.template', 'create', [{
        'name': name,
        'default_code': sku,   # code interne
        'list_price': price,   # prix de vente
        'sale_ok': True,
        'purchase_ok': False,
    }])

    # Si possible, définir le type comme 'product' (stockable) selon le champ disponible
    try:
        flds = odoo.execute_kw('product.template', 'fields_get', [['type', 'detailed_type']])
        updates = {}
        if 'type' in flds:
            updates['type'] = 'product'
        elif 'detailed_type' in flds:
            updates['detailed_type'] = 'product'
        if updates:
            odoo.execute_kw('product.template', 'write', [[tmpl_id], updates])
    except Exception:
        # soft-fail: on laisse le type par défaut
        pass

    # Lire la variante créée automatiquement
    variant_info = odoo.execute_kw('product.template', 'read', [[tmpl_id], ['product_variant_id']])
    variant_id = variant_info[0]['product_variant_id'][0]
    return variant_id

def _create_sale_order(order):
    ext_ref = f"WOO-{order['id']}"
    existing = odoo.execute_kw('sale.order', 'search', [[('client_order_ref', '=', ext_ref)]], {'limit': 1})
    if existing:
        return existing[0]

    partner_id = _ensure_partner(order)
    lines = []
    for l in (order.get('line_items') or []):
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

    if lines:
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
    products = odoo.execute_kw(
        'product.product', 'search_read',
        [[('sale_ok', '=', True)]],
        {'fields': ['id', 'default_code', 'qty_available'], 'limit': 2000}
    )
    for p in products:
        sku = p.get('default_code') or str(p['id'])
        found = woo.get('products', params={'sku': sku})
        if not found:
            continue
        prod_id = found[0]['id']
        woo.put(f'products/{prod_id}', data={
            'manage_stock': True,
            'stock_quantity': int(p.get('qty_available') or 0)
        })
    return {'status': 'done'}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
