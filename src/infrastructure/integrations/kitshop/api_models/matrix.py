from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class KitShopMatrixLocation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    location_id: Annotated[int, Field(validation_alias="LocationId")]
    name: Annotated[str, Field(validation_alias=AliasChoices("Name", "LocationName"))]
    location_type: Annotated[int, Field(validation_alias="Type")]


class KitShopMatrixCategory(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category_id: Annotated[int, Field(validation_alias="CategoryId")]


class KitShopMatrixTemplateProduct(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: Annotated[int, Field(validation_alias="ProductId")]
    price: Annotated[Decimal, Field(validation_alias="Price")]
    category_id: Annotated[int, Field(validation_alias="CategoryId")]
    location_id: Annotated[int, Field(validation_alias="LocationId")]
    disabled: Annotated[bool, Field(validation_alias="Disabled")]

    @field_validator("price", mode="before")
    @classmethod
    def _price_as_decimal(cls, value: Any) -> Decimal:
        return Decimal(str(value))


class KitShopMatrixTemplate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    locations: Annotated[
        list[KitShopMatrixLocation],
        Field(default_factory=list, validation_alias="Locations"),
    ]
    categories: Annotated[
        list[KitShopMatrixCategory],
        Field(default_factory=list, validation_alias="Categories"),
    ]
    products: Annotated[
        list[KitShopMatrixTemplateProduct],
        Field(default_factory=list, validation_alias="Products"),
    ]


class KitShopProductGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    group_id: Annotated[int, Field(validation_alias="GroupId")]
    group_name: Annotated[str, Field(validation_alias="GroupName")]
