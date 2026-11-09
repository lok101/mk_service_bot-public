from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AliasChoices, BaseModel, BeforeValidator, Field, computed_field

from src.infrastructure.integrations.kitvending.api_models.enums import VendingMachineKind
from src.infrastructure.integrations.kitvending.datetime_kit import KitDateTime


class SaleModel(BaseModel):
    line: Annotated[int, Field(validation_alias="LineNumber")]
    price: Annotated[float, Field(validation_alias="Sum")]
    datetime_kit: Annotated[str, Field(validation_alias="DateTime")]
    product_name: Annotated[str, Field(validation_alias="GoodsName")]

    vending_machine_id: Annotated[int, Field(validation_alias="VendingMachine")]
    vending_machine_name: Annotated[str, Field(validation_alias="VendingMachineName")]
    matrix_id: Annotated[
        int | None,
        Field(validation_alias="MatrixId"),
        BeforeValidator(lambda val: int(val) if val else None),
    ]
    company_id: Annotated[
        int | None,
        Field(default=None, validation_alias=AliasChoices("Company", "CompanyId")),
        BeforeValidator(lambda val: int(val) if val else None),
    ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timestamp(self) -> datetime:
        return KitDateTime.datetime_from_str_kit(self.datetime_kit)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vending_machine_code(self) -> str | None:
        from src.application.matrix_automation import extract_vending_machine_code

        return extract_vending_machine_code(self.vending_machine_name)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def product_code(self) -> str | None:
        from src.infrastructure.integrations.kitvending.parsing.utils import extract_product_code

        return extract_product_code(self.product_name)


class SaleResolvedModel(BaseModel):
    """Продажа с разрешённым кодом товара (без полного набора полей SaleModel)."""

    price: float
    timestamp: datetime
    product_code: str
    vending_machine_code: str
    vending_machine_type: VendingMachineKind
