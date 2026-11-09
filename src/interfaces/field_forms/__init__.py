from __future__ import annotations

from src.interfaces.field_forms.coffee_forms import (
    CoffeeFieldFormDeps,
    register_coffee_field_form_routes,
)
from src.interfaces.field_forms.micromarket_inventory_now import (
    MicromarketInventoryNowFieldFormDeps,
    register_micromarket_inventory_now_field_form_routes,
)
from src.interfaces.field_forms.technician_warehouse_inventory import (
    TechnicianWarehouseInventoryFieldFormDeps,
    register_technician_warehouse_inventory_field_form_routes,
)

__all__ = [
    "CoffeeFieldFormDeps",
    "MicromarketInventoryNowFieldFormDeps",
    "TechnicianWarehouseInventoryFieldFormDeps",
    "register_coffee_field_form_routes",
    "register_micromarket_inventory_now_field_form_routes",
    "register_technician_warehouse_inventory_field_form_routes",
]
