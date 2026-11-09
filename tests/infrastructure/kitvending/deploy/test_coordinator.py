from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.matrix_automation import MatrixDeployPayload, MatrixDeployPayloadLine
from src.infrastructure.kitvending.deploy.coordinator import BatchMatrixDeployCoordinator
from src.infrastructure.kitvending.deploy.models import (
    KitMatrixCommandCode,
    KitVendingMachineRecord,
    KitVMStateRecord,
)


def _payload(machine_code: str = "512") -> MatrixDeployPayload:
    return MatrixDeployPayload(
        logical_matrix_name="snacks_main",
        machine_code=machine_code,
        matrix_multiplier="1.0",
        lines=(
            MatrixDeployPayloadLine(
                line_number=1,
                product_code="MS-1",
                product_name="Кола",
                deploy_price=Decimal("120"),
                capacity=10,
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


@dataclass
class _FakeDeployClient:
    """Fake Kit deploy client.

    By default VM states follow command phase: LOAD sets status 21, APPLY clears it.
    Pass ``states`` for a static poll response (e.g. permanent LOAD timeout).
    """

    machines: tuple[KitVendingMachineRecord, ...]
    states: tuple[KitVMStateRecord, ...] | None = None
    calls: list[str] = field(default_factory=list)
    _matrix_loaded: bool = False

    def get_vending_machines(self) -> list[KitVendingMachineRecord]:
        self.calls.append("get_vending_machines")
        return list(self.machines)

    def create_pieces_matrix(self, matrix_name: str, positions: object) -> int:
        self.calls.append(f"create:{matrix_name}:{len(positions)}")  # type: ignore[arg-type]
        return 77

    def apply_matrix(self, *, matrix_id: int, vending_machine_id: int) -> None:
        self.calls.append(f"bind:{matrix_id}:{vending_machine_id}")

    def send_command(self, *, vending_machine_id: int, command_code: object) -> None:
        code = int(command_code)  # type: ignore[arg-type]
        self.calls.append(f"command:{code}:{vending_machine_id}")
        if code == int(KitMatrixCommandCode.LOAD_MATRIX):
            self._matrix_loaded = True
        elif code == int(KitMatrixCommandCode.APPLY_MATRIX):
            self._matrix_loaded = False

    def get_vm_states(self) -> list[KitVMStateRecord]:
        self.calls.append("get_vm_states")
        if self.states is not None:
            return list(self.states)
        statuses = "21,1" if self._matrix_loaded else "1"
        return [
            KitVMStateRecord(
                machine.vending_machine_id,
                {
                    "VendingMachineId": machine.vending_machine_id,
                    "Statuses": statuses,
                },
            )
            for machine in self.machines
        ]


def _coordinator(*clients: _FakeDeployClient) -> BatchMatrixDeployCoordinator:
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    def fake_sleep(seconds: float) -> None:
        clock["t"] += seconds

    return BatchMatrixDeployCoordinator(
        clients=clients,
        blocking_label="БЛОК",
        display_timezone=UTC,
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
        load_timeout_seconds=1,
        apply_timeout_seconds=1,
        status_poll_interval_seconds=1,
        command_send_delay_seconds=1,
        poll_api_max_retries=1,
        retry_send_command_delay_seconds=1,
        sleep=fake_sleep,
        monotonic=monotonic,
    )


def test_deploy_success_path_preserves_input_order_and_cardinality() -> None:
    client = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    coordinator = _coordinator(client)
    result = coordinator.deploy([_payload()])
    assert [
        (item.logical_matrix_name, item.machine_code, item.status, item.reason) for item in result
    ] == [
        ("snacks_main", "512", "applied", None),
    ]
    assert client.calls[:4] == [
        "get_vending_machines",
        "create:snacks_main_512_2026-07-09:1",
        "bind:77:1001",
        f"command:{int(KitMatrixCommandCode.LOAD_MATRIX)}:1001",
    ]


def test_coordinator_success_sets_kit_matrix_id() -> None:
    client = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(client).deploy([_payload()])
    assert result[0].status == "applied"
    assert result[0].kit_matrix_id == 77
    assert result[0].vending_machine_id == 1001
    assert result[0].kit_matrix_name == "snacks_main_512_2026-07-09"


def test_machine_not_found_returns_reason() -> None:
    coordinator = _coordinator(_FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [513]"),)))
    result = coordinator.deploy([_payload("512")])
    assert result[0].status == "failed"
    assert result[0].reason == "machine_not_found_in_kit"


def test_duplicate_machine_code_returns_ambiguous_reason() -> None:
    first = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    second = _FakeDeployClient((KitVendingMachineRecord(2001, "Аппарат [512]"),))
    coordinator = _coordinator(first, second)
    result = coordinator.deploy([_payload("512")])
    assert result[0].status == "failed"
    assert result[0].reason == "ambiguous_machine_code"


def test_head_only_deploys_via_head() -> None:
    head = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(head).deploy([_payload("512")])
    assert result[0].status == "applied"
    assert any(call.startswith("create:") for call in head.calls)


def test_child_only_deploys_via_child() -> None:
    head = _FakeDeployClient((KitVendingMachineRecord(9001, "Аппарат [513]"),))
    child = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(head, child).deploy([_payload("512")])
    assert result[0].status == "applied"
    assert head.calls == ["get_vending_machines"]
    assert any(call.startswith("create:") for call in child.calls)


def test_head_shadow_deploys_via_child() -> None:
    head = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    child = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(head, child).deploy([_payload("512")])
    assert result[0].status == "applied"
    assert head.calls == ["get_vending_machines"]
    assert any(call.startswith("create:") for call in child.calls)


def test_inactive_record_ignored_active_selected() -> None:
    client = _FakeDeployClient(
        (
            KitVendingMachineRecord(9001, "[ X ] [512] старый"),
            KitVendingMachineRecord(1001, "Аппарат [512]"),
        )
    )
    result = _coordinator(client).deploy([_payload("512")])
    assert result[0].status == "applied"
    assert any(call == "bind:77:1001" for call in client.calls)


def test_only_inactive_returns_machine_not_found() -> None:
    client = _FakeDeployClient((KitVendingMachineRecord(9001, "[ X ] [512] старый"),))
    result = _coordinator(client).deploy([_payload("512")])
    assert result[0].status == "failed"
    assert result[0].reason == "machine_not_found_in_kit"


def test_duplicate_id_within_account_dedup_deploys() -> None:
    client = _FakeDeployClient(
        (
            KitVendingMachineRecord(1001, "Аппарат [512] A"),
            KitVendingMachineRecord(1001, "Аппарат [512] B"),
        )
    )
    result = _coordinator(client).deploy([_payload("512")])
    assert result[0].status == "applied"


def test_different_ids_within_account_returns_ambiguous() -> None:
    client = _FakeDeployClient(
        (
            KitVendingMachineRecord(1001, "Аппарат [512]"),
            KitVendingMachineRecord(2002, "Аппарат [512]"),
        )
    )
    result = _coordinator(client).deploy([_payload("512")])
    assert result[0].status == "failed"
    assert result[0].reason == "ambiguous_machine_code"


def test_same_active_in_multiple_children_returns_ambiguous() -> None:
    head = _FakeDeployClient(())
    child_a = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    child_b = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(head, child_a, child_b).deploy([_payload("512")])
    assert result[0].status == "failed"
    assert result[0].reason == "ambiguous_machine_code"


def test_matrix_name_uses_service_timezone_date() -> None:
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    def fake_sleep(seconds: float) -> None:
        clock["t"] += seconds

    client = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    coordinator = BatchMatrixDeployCoordinator(
        clients=(client,),
        blocking_label="БЛОК",
        display_timezone=ZoneInfo("Asia/Yekaterinburg"),
        now=lambda: datetime(2026, 7, 8, 21, 30, tzinfo=UTC),
        load_timeout_seconds=1,
        apply_timeout_seconds=1,
        status_poll_interval_seconds=1,
        command_send_delay_seconds=1,
        poll_api_max_retries=1,
        retry_send_command_delay_seconds=1,
        sleep=fake_sleep,
        monotonic=monotonic,
    )
    coordinator.deploy([_payload()])
    assert any(call.startswith("create:snacks_main_512_2026-07-09") for call in client.calls)


def test_timeout_on_one_machine_does_not_block_next_payload() -> None:
    timeout_client = _FakeDeployClient(
        (KitVendingMachineRecord(1001, "Аппарат [512]"),),
        states=(KitVMStateRecord(1001, {"VendingMachineId": 1001, "Statuses": "1"}),),
    )
    ok_client = _FakeDeployClient((KitVendingMachineRecord(2001, "Аппарат [513]"),))
    coordinator = _coordinator(timeout_client, ok_client)
    results = coordinator.deploy([_payload("512"), _payload("513")])
    assert [(item.machine_code, item.status, item.reason) for item in results] == [
        ("512", "failed", "load_timeout"),
        ("513", "applied", None),
    ]


class _FailingUploadClient(_FakeDeployClient):
    def create_pieces_matrix(self, matrix_name: str, positions: object) -> int:
        raise RuntimeError("upload down")


class _FailingBindClient(_FakeDeployClient):
    def apply_matrix(self, *, matrix_id: int, vending_machine_id: int) -> None:
        raise RuntimeError("bind down")


def test_upload_failure_returns_upload_failed() -> None:
    client = _FailingUploadClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(client).deploy([_payload()])
    assert result[0].reason == "upload_failed"
    assert result[0].status == "failed"


def test_upload_failure_logs_warning_with_error_message(caplog) -> None:
    import logging

    client = _FailingUploadClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    with caplog.at_level(logging.WARNING):
        result = _coordinator(client).deploy([_payload()])

    assert result[0].status == "failed"
    assert result[0].reason == "upload_failed"
    record = next(r for r in caplog.records if r.getMessage() == "kitvending_matrix_upload_failed")
    assert record.levelno == logging.WARNING
    assert record.machine_code == "512"
    assert record.logical_matrix_name == "snacks_main"
    assert record.exception_type == "RuntimeError"
    assert record.error_message == "upload down"
    assert not any(r.getMessage() == "kitvending_matrix_bind_failed" for r in caplog.records)
    assert all("delete" not in c for c in client.calls)


def test_bind_failure_returns_bind_failed() -> None:
    client = _FailingBindClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(client).deploy([_payload()])
    assert result[0].reason == "bind_failed"
    assert result[0].status == "failed"


def test_bind_failure_logs_warning_with_matrix_id_and_error_message(caplog) -> None:
    import logging

    client = _FailingBindClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    with caplog.at_level(logging.WARNING):
        result = _coordinator(client).deploy([_payload()])

    assert result[0].status == "failed"
    assert result[0].reason == "bind_failed"
    record = next(r for r in caplog.records if r.getMessage() == "kitvending_matrix_bind_failed")
    assert record.levelno == logging.WARNING
    assert record.machine_code == "512"
    assert record.logical_matrix_name == "snacks_main"
    assert record.matrix_id == 77
    assert record.exception_type == "RuntimeError"
    assert record.error_message == "bind down"
    assert all("delete" not in c for c in client.calls)


class _RaisingPollClient(_FakeDeployClient):
    def get_vm_states(self) -> list[KitVMStateRecord]:
        self.calls.append("get_vm_states")
        raise RuntimeError("poll down")


def test_poll_exception_on_one_machine_does_not_block_next_payload() -> None:
    failing = _RaisingPollClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    ok = _FakeDeployClient((KitVendingMachineRecord(2001, "Аппарат [513]"),))
    results = _coordinator(failing, ok).deploy([_payload("512"), _payload("513")])
    assert [(item.machine_code, item.status, item.reason) for item in results] == [
        ("512", "failed", "load_timeout"),
        ("513", "applied", None),
    ]


class _RaisingResolveClient(_FakeDeployClient):
    def get_vending_machines(self) -> list[KitVendingMachineRecord]:
        self.calls.append("get_vending_machines")
        raise RuntimeError("resolve down")


def test_resolve_exception_fails_closed_and_skips_remaining() -> None:
    broken = _RaisingResolveClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    other = _FakeDeployClient((KitVendingMachineRecord(2001, "Аппарат [512]"),))
    result = _coordinator(broken, other).deploy([_payload("512")])
    assert result[0].status == "failed"
    assert result[0].reason == "kit_machine_lookup_failed"
    # остальные аккаунты не запрашиваются; write не начинается
    assert other.calls == []
    assert "create:snacks_main_512_2026-07-09:1" not in broken.calls


class _FailFirstResolveClient(_FakeDeployClient):
    """get_vending_machines бросает на первом вызове, затем успешен (no caching)."""

    def get_vending_machines(self) -> list[KitVendingMachineRecord]:
        prior = self.calls.count("get_vending_machines")
        self.calls.append("get_vending_machines")
        if prior == 0:
            raise RuntimeError("resolve down")
        return list(self.machines)


def test_lookup_failure_isolated_per_unit() -> None:
    client = _FailFirstResolveClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    results = _coordinator(client).deploy([_payload("512"), _payload("512")])
    assert [(item.status, item.reason) for item in results] == [
        ("failed", "kit_machine_lookup_failed"),
        ("applied", None),
    ]


def test_lookup_failed_log_fields_no_credentials(caplog) -> None:
    import logging

    broken = _RaisingResolveClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    with caplog.at_level(logging.WARNING):
        _coordinator(broken).deploy([_payload("512")])
    record = next(r for r in caplog.records if r.getMessage() == "kitvending_machine_lookup_failed")
    assert record.levelno == logging.WARNING
    assert record.machine_code == "512"
    assert record.account_role == "head"
    assert record.account_index == 0
    assert record.account_ref == "head[0]"
    assert record.exception_type == "RuntimeError"
    assert record.error_message == "resolve down"
    blob = str(record.__dict__)
    assert "login" not in blob
    assert "password" not in blob


def test_resolved_log_fields(caplog) -> None:
    import logging

    head = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    child = _FakeDeployClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    with caplog.at_level(logging.INFO):
        _coordinator(head, child).deploy([_payload("512")])
    record = next(r for r in caplog.records if r.getMessage() == "kitvending_machine_resolved")
    assert record.levelno == logging.INFO
    assert record.machine_code == "512"
    assert record.vending_machine_id == 1001
    assert record.account_role == "child"
    assert record.account_index == 1
    assert record.account_ref == "child[1]"
    assert record.head_shadow is True


def test_load_wait_stops_on_wall_clock_timeout() -> None:
    sleeps: list[float] = []
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    client = _FakeDeployClient(
        (KitVendingMachineRecord(1001, "Аппарат [512]"),),
        states=(KitVMStateRecord(1001, {"VendingMachineId": 1001, "Statuses": "1"}),),
    )
    coordinator = BatchMatrixDeployCoordinator(
        clients=(client,),
        blocking_label="БЛОК",
        display_timezone=UTC,
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
        load_timeout_seconds=25,
        apply_timeout_seconds=25,
        status_poll_interval_seconds=10,
        command_send_delay_seconds=1,
        poll_api_max_retries=100,
        retry_send_command_delay_seconds=1,
        sleep=fake_sleep,
        monotonic=monotonic,
    )
    result = coordinator.deploy([_payload()])
    assert result[0].reason == "load_timeout"
    assert sum(1 for s in sleeps if s == 10) <= 3


@dataclass
class _LoadOkApplyNeverClient(_FakeDeployClient):
    """LOAD succeeds (status 21); APPLY never clears 21."""

    def get_vm_states(self) -> list[KitVMStateRecord]:
        self.calls.append("get_vm_states")
        return [
            KitVMStateRecord(
                machine.vending_machine_id,
                {"VendingMachineId": machine.vending_machine_id, "Statuses": "21,1"},
            )
            for machine in self.machines
        ]


def test_apply_timeout_returns_reason() -> None:
    client = _LoadOkApplyNeverClient((KitVendingMachineRecord(1001, "Аппарат [512]"),))
    result = _coordinator(client).deploy([_payload()])
    assert result[0].status == "failed"
    assert result[0].reason == "apply_timeout"
