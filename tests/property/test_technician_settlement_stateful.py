from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)
from src.domain.technician_settlement import (
    CompleteReconciliationSession,
    RecordPeriodAccountability,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import (
    SettlementEvent,
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCompleted,
)

from .stateful_helpers import FIXED_ANCHOR, normalize, settlement_view
from .strategies import AWARE_DATETIMES, SKU_MAPS, TOKEN

ACCOUNTABILITY_ID = TOKEN
SESSION_ID = TOKEN
_TECHNICIAN_ID = TechnicianId("tech-property")
_MACHINE_ID = MachineId("vm-property")


class TechnicianSettlementStateMachine(RuleBasedStateMachine):
    @initialize()
    def initialize(self) -> None:
        self.aggregate = TechnicianSettlement.empty(_TECHNICIAN_ID)
        self.durable_events: list[SettlementEvent] = []
        self.oracle_balance: dict[str, Decimal] = {}
        self.accountability_ids: set[str] = set()
        self.committed_session_ids: set[str] = set()
        self.known_session_ids: set[str] = set()

    def _record_accountability(
        self,
        accountability_id: str,
        delta: dict[str, Decimal],
        closed_at: datetime,
    ) -> None:
        already = accountability_id in self.accountability_ids
        self.aggregate.record_period_accountability(
            RecordPeriodAccountability(
                accountability_id=AccountabilityId(accountability_id),
                period_id=f"period-{accountability_id}",
                machine_id=_MACHINE_ID,
                delta_by_sku=delta,
                closed_at=closed_at,
            )
        )
        if already:
            return
        self.accountability_ids.add(accountability_id)
        for sku, quantity in delta.items():
            self.oracle_balance[sku] = self.oracle_balance.get(sku, Decimal("0")) + quantity

    def _complete_session(self, session_id: str) -> None:
        snapshot = dict(self.oracle_balance)
        already = session_id in self.committed_session_ids
        self.aggregate.complete_reconciliation_session(
            CompleteReconciliationSession(
                session_id=ReconciliationSessionId(session_id),
                mode="inventory_delta",
                anchor_at=FIXED_ANCHOR,
                period_ids=("period-a",),
                deferred_period_ids=(),
                warehouse_inventory_id="inv-1",
                warehouse_inventory_moment=FIXED_ANCHOR,
                warehouse_delta_by_sku=snapshot,
                warehouse_source="domain_technician_warehouse",
                warehouse_transfer_refs=(),
                ledger_balance_before=snapshot,
                residual_by_sku={},
                finalized_at=FIXED_ANCHOR,
                executed_at=FIXED_ANCHOR,
            )
        )
        self.known_session_ids.add(session_id)
        if already:
            return
        self.committed_session_ids.add(session_id)
        for sku, quantity in snapshot.items():
            self.oracle_balance[sku] = self.oracle_balance.get(sku, Decimal("0")) - quantity

    @rule(accountability_id=ACCOUNTABILITY_ID, delta=SKU_MAPS, closed_at=AWARE_DATETIMES)
    def record_accountability(
        self,
        accountability_id: str,
        delta: dict[str, Decimal],
        closed_at: datetime,
    ) -> None:
        self._record_accountability(accountability_id, delta, closed_at)

    @rule(session_id=SESSION_ID)
    def complete_session(self, session_id: str) -> None:
        self._complete_session(session_id)

    @rule(accountability_id=ACCOUNTABILITY_ID, delta=SKU_MAPS, closed_at=AWARE_DATETIMES)
    def record_duplicate_accountability(
        self,
        accountability_id: str,
        delta: dict[str, Decimal],
        closed_at: datetime,
    ) -> None:
        self._record_accountability(accountability_id, delta, closed_at)

    @rule(accountability_id=ACCOUNTABILITY_ID, closed_at=AWARE_DATETIMES)
    def record_empty_accountability(self, accountability_id: str, closed_at: datetime) -> None:
        self._record_accountability(accountability_id, {}, closed_at)

    @rule(session_id=SESSION_ID)
    def complete_duplicate_session_before_save(self, session_id: str) -> None:
        self._complete_session(session_id)

    @rule(session_id=SESSION_ID)
    def complete_duplicate_session_after_save(self, session_id: str) -> None:
        self.clear_pending_save_boundary()
        self._complete_session(session_id)

    @rule(session_id=SESSION_ID)
    def seed_durable_legacy_session_pair(self, session_id: str) -> None:
        if session_id in self.committed_session_ids:
            return
        self.clear_pending_save_boundary()
        snapshot = dict(self.oracle_balance)
        completed = TechnicianReconciliationSessionCompleted(
            event_id=EventId(f"legacy-completed-{session_id}"),
            session_id=ReconciliationSessionId(session_id),
            technician_id=_TECHNICIAN_ID,
            mode="inventory_delta",
            anchor_at=FIXED_ANCHOR,
            period_ids=("period-a",),
            deferred_period_ids=(),
            warehouse_inventory_id="inv-legacy",
            warehouse_inventory_moment=FIXED_ANCHOR,
            warehouse_delta_by_sku=dict(snapshot),
            warehouse_source="domain_technician_warehouse",
            warehouse_transfer_refs=(),
            ledger_balance_before=dict(snapshot),
            residual_by_sku={},
            finalized_at=FIXED_ANCHOR,
            occurred_at=FIXED_ANCHOR,
            executed_at=FIXED_ANCHOR,
        )
        cleared = TechnicianLedgerClearedByReconciliation(
            event_id=EventId(f"legacy-cleared-{session_id}"),
            session_id=ReconciliationSessionId(session_id),
            technician_id=_TECHNICIAN_ID,
            period_ids=("period-a",),
            cleared_by_sku=dict(snapshot),
            residual_by_sku={},
            occurred_at=FIXED_ANCHOR,
        )
        self.durable_events.extend([completed, cleared])
        self.aggregate = TechnicianSettlement.rehydrate(
            self.aggregate.technician_id,
            list(self.durable_events),
        )
        self.committed_session_ids.add(session_id)
        self.known_session_ids.add(session_id)
        for sku, quantity in snapshot.items():
            self.oracle_balance[sku] = self.oracle_balance.get(sku, Decimal("0")) - quantity

    @rule()
    def clear_pending_save_boundary(self) -> None:
        self.durable_events.extend(self.aggregate.collect_events())
        self.aggregate.clear_pending_events()

    @invariant()
    def ledger_matches_unique_accountability_minus_committed_clears(self) -> None:
        assert self.aggregate.net_balance_by_sku() == normalize(self.oracle_balance)

    @invariant()
    def replay_matches_live(self) -> None:
        events = [*self.durable_events, *self.aggregate.collect_events()]
        replayed = TechnicianSettlement.rehydrate(self.aggregate.technician_id, events)
        known = frozenset(self.known_session_ids)
        assert settlement_view(replayed, known) == settlement_view(self.aggregate, known)


class TestTechnicianSettlementStateMachine(TechnicianSettlementStateMachine.TestCase):
    settings = settings(
        max_examples=100,
        stateful_step_count=50,
        deadline=None,
    )


def test_duplicate_accountability_and_session_ids_have_one_ledger_effect_after_replay() -> None:
    """INV-SET-001: duplicate accountability and session ids have one ledger effect."""
    aggregate = TechnicianSettlement.empty(_TECHNICIAN_ID)
    command = RecordPeriodAccountability(
        accountability_id=AccountabilityId("id-a"),
        period_id="period-id-a",
        machine_id=_MACHINE_ID,
        delta_by_sku={"coffee": Decimal("5.000")},
        closed_at=FIXED_ANCHOR,
    )
    aggregate.record_period_accountability(command)
    aggregate.record_period_accountability(command)
    accountability_events = list(aggregate.collect_events())
    aggregate.clear_pending_events()
    aggregate.record_period_accountability(command)
    assert aggregate.collect_events() == []

    snapshot = dict(aggregate.net_balance_by_sku())
    session = CompleteReconciliationSession(
        session_id=ReconciliationSessionId("id-b"),
        mode="inventory_delta",
        anchor_at=FIXED_ANCHOR,
        period_ids=("period-a",),
        deferred_period_ids=(),
        warehouse_inventory_id="inv-1",
        warehouse_inventory_moment=FIXED_ANCHOR,
        warehouse_delta_by_sku=snapshot,
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before=snapshot,
        residual_by_sku={},
        finalized_at=FIXED_ANCHOR,
        executed_at=FIXED_ANCHOR,
    )
    aggregate.complete_reconciliation_session(session)
    aggregate.complete_reconciliation_session(session)
    session_events = list(aggregate.collect_events())
    aggregate.clear_pending_events()
    aggregate.complete_reconciliation_session(session)
    assert aggregate.collect_events() == []
    assert len(accountability_events) == 1
    assert len(session_events) == 1
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("0")

    replayed = TechnicianSettlement.rehydrate(
        aggregate.technician_id,
        [*accountability_events, *session_events],
    )
    known = frozenset({"id-b"})
    assert settlement_view(replayed, known) == settlement_view(aggregate, known)
