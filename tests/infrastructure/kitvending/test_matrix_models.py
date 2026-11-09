from __future__ import annotations

from src.infrastructure.integrations.kitvending.api_models.matrix import (
    ComboMatrixModel,
    GoodsCell,
    MatricesKitCollection,
)
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel


def test_goods_cell_product_code_from_goods_name() -> None:
    cell = GoodsCell.model_validate(
        {"LineNumber": 1, "Price2": 10.0, "GoodsName": "2101 | Snack", "MaxCount": 10},
    )
    assert cell.product_code == "2101"


def test_matrices_collection_discriminates_goods_recipe_combo() -> None:
    collection = MatricesKitCollection.model_validate(
        {
            "GoodsMatrices": [
                {
                    "MatrixId": 1,
                    "MatrixName": "Snack",
                    "MatrixType": 1,
                    "Details": [
                        {
                            "LineNumber": 1,
                            "Price2": 10.0,
                            "GoodsName": "2101 | Snack",
                            "MaxCount": 5,
                        }
                    ],
                },
                {
                    "MatrixId": 2,
                    "MatrixName": "Coffee",
                    "MatrixType": 2,
                    "Details": [{"LineNumber": 1, "Price2": 50.0, "FormulationId": 7}],
                },
                {"MatrixId": 3, "MatrixName": "Combo", "MatrixType": 3, "Details": []},
            ]
        }
    )
    assert len(collection.get_snack_matrices()) == 1
    assert len(collection.get_recipes_matrices()) == 1
    assert isinstance(collection.items[-1], ComboMatrixModel)


def test_recipe_model_code_from_formulation_name() -> None:
    recipe = RecipeModel.model_validate(
        {"FormulationId": 7, "FormulationName": "2301 | Latte"},
    )
    assert recipe.code == "2301"
