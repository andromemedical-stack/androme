from typing import Dict, Any

def map_sale_line(line: Dict[str, Any]):
    qty = float(line.get('quantity') or 1)
    price = float(line.get('price') or 0.0)
    name = line.get('name')
    sku = line.get('sku') or str(line.get('product_id'))
    return {
        'name': name,
        'sku': sku,
        'product_uom_qty': qty,
        'price_unit': price,
    }
