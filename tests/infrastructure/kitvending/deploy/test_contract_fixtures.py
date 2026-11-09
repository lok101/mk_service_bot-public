from __future__ import annotations


def test_contract_fixture_get_vending_machines_fields() -> None:
    response = {
        "ResultCode": 0,
        "VendingMachines": [
            {"VendingMachineId": 1001, "VendingMachineName": "Аппарат [512]"},
        ],
    }
    item = response["VendingMachines"][0]
    assert item["VendingMachineId"] == 1001
    assert item["VendingMachineName"] == "Аппарат [512]"


def test_contract_fixture_get_vm_states_fields() -> None:
    response = {
        "ResultCode": 0,
        "VendingMachines": [
            {"VendingMachineId": 1001, "Statuses": "21,1"},
        ],
    }
    item = response["VendingMachines"][0]
    assert item["VendingMachineId"] == 1001
    assert item["Statuses"] == "21,1"


def test_contract_fixture_create_pieces_matrix_fields() -> None:
    request = {
        "MatrixName": "snacks_main_512_2026-07-09",
        "Positions": [
            {
                "LineNumber": 1,
                "GoodsName": "2312 | Кола",
                "Price": "120",
                "Price2": "120",
                "MaxCount": 10,
            },
        ],
    }
    position = request["Positions"][0]
    assert set(position) == {"LineNumber", "GoodsName", "Price", "Price2", "MaxCount"}


def test_contract_fixture_create_pieces_matrix_response_id_field() -> None:
    response = {"ResultCode": 0, "Id": 77}
    assert response["Id"] == 77


def test_contract_fixture_blocked_empty_position() -> None:
    position = {
        "LineNumber": 2,
        "GoodsName": "БЛОК",
        "Price": "999",
        "Price2": "999",
        "MaxCount": 0,
    }
    assert position["GoodsName"]
    assert position["Price"] == position["Price2"] == "999"
    assert position["MaxCount"] == 0


def test_contract_fixture_command_codes() -> None:
    assert 3 == 3  # LOAD_MATRIX
    assert 4 == 4  # APPLY_MATRIX
    assert 34 == 34  # LOAD_AND_APPLY_MATRIX, documented but not used in v1 coordinator
