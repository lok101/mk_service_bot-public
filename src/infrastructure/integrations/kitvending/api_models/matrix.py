from __future__ import annotations

from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, Tag, computed_field


class BaseMatrixCell(BaseModel):
    line_number: Annotated[int, Field(validation_alias="LineNumber")]
    price: Annotated[float | None, Field(validation_alias="Price2")]


class GoodsCell(BaseMatrixCell):
    product_name: Annotated[str, Field(validation_alias="GoodsName")]
    capacity: Annotated[int | None, Field(validation_alias="MaxCount")]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def product_code(self) -> str | None:
        from src.infrastructure.integrations.kitvending.parsing.utils import extract_product_code

        return extract_product_code(self.product_name)


class RecipeCell(BaseMatrixCell):
    recipe_id: Annotated[int, Field(validation_alias="FormulationId")]


class RecipeCodeCell(BaseMatrixCell):
    model_config = ConfigDict(populate_by_name=True)

    recipe_id: int
    recipe_code: str | None


class MatrixModel(BaseModel):
    id: Annotated[int, Field(validation_alias="MatrixId")]
    name: Annotated[str, Field(validation_alias="MatrixName")]
    cells: Annotated[list[BaseMatrixCell], Field(validation_alias="Details")]


class GoodsMatrixModel(MatrixModel):
    type: Literal[1] = Field(validation_alias="MatrixType")
    cells: Annotated[list[GoodsCell], Field(validation_alias="Details")]  # type: ignore[assignment]


class RecipeMatrixModel(MatrixModel):
    type: Literal[2] = Field(validation_alias="MatrixType")
    cells: Annotated[list[RecipeCell], Field(validation_alias="Details")]  # type: ignore[assignment]


class RecipeCodeMatrixModel(BaseModel):
    id: int
    name: str
    type: Literal[2] = 2
    cells: list[RecipeCodeCell]


class ComboMatrixModel(MatrixModel):
    type: Literal[3] = Field(validation_alias="MatrixType")


MatrixType = Annotated[
    Annotated[GoodsMatrixModel, Tag(1)]
    | Annotated[RecipeMatrixModel, Tag(2)]
    | Annotated[ComboMatrixModel, Tag(3)],
    Field(discriminator="type"),
]


class MatricesKitCollection(BaseModel):
    items: Annotated[list[MatrixType], Field(validation_alias="GoodsMatrices")]

    def get_snack_matrices(self) -> list[GoodsMatrixModel]:
        return [item for item in self.items if isinstance(item, GoodsMatrixModel)]

    def get_recipes_matrices(self) -> list[RecipeMatrixModel]:
        return [item for item in self.items if isinstance(item, RecipeMatrixModel)]

    def get_all_matrices(self) -> list[MatrixModel]:
        return cast(list[MatrixModel], self.items.copy())
