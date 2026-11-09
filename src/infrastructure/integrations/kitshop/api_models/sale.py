from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class KitShopSalePosition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    position_id: Annotated[int, Field(validation_alias="PositionId")]
    product_id: Annotated[int, Field(validation_alias="ProductId")]
    quantity: Annotated[int, Field(validation_alias="Quantity")]
    price: Annotated[float, Field(validation_alias="Price")]


class KitShopSale(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sale_id: Annotated[int, Field(validation_alias="SaleId")]
    company_id: Annotated[int, Field(validation_alias="CompanyId")]
    shop_id: Annotated[int, Field(validation_alias="ShopId")]
    device_id: Annotated[int, Field(validation_alias="DeviceId")]
    sale_datetime: Annotated[str, Field(validation_alias="SaleDateTime")]
    positions: Annotated[
        list[KitShopSalePosition],
        Field(default_factory=list, validation_alias="Positions"),
    ]
