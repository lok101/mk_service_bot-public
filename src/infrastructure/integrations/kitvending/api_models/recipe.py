from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, computed_field


class RecipeModel(BaseModel):
    id: Annotated[int, Field(validation_alias="FormulationId")]
    name: Annotated[str, Field(validation_alias="FormulationName")]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def code(self) -> str | None:
        from src.infrastructure.integrations.kitvending.parsing.utils import extract_product_code

        return extract_product_code(self.name)
