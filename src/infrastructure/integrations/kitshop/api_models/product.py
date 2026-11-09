from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class KitShopProduct(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: Annotated[int, Field(validation_alias="ProductId")]
    product_name: Annotated[str, Field(validation_alias="ProductName")]
    vendor_code: Annotated[str | None, Field(default=None, validation_alias="VendorCode")]
    is_deleted: Annotated[bool, Field(default=False, validation_alias="IsDeleted")]
