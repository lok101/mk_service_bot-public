from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class KitShopShop(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    shop_id: Annotated[int, Field(validation_alias="ShopId")]
    shop_name: Annotated[str, Field(validation_alias="ShopName")]
    company_id: Annotated[int, Field(validation_alias="CompanyId")]
    product_base_template_id: Annotated[
        int | None,
        Field(default=None, validation_alias="ProductBaseTemplateId"),
    ]
