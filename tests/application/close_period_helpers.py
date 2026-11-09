from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.application.inventory_reconciliation.ports import PeriodPartyNamesLookup
from src.application.outbox.period_reconciliation_handler import PeriodReconciliationHandler
from src.application.product_identity.models import DomainProduct
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.domain.form_submission import FormAnswer, FrozenInventoryLine, FrozenProductSpec
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.machine_sales import MachineSale
from src.domain.models import RevisionSource
from src.domain.product_catalog import ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineRevisionHistoryReader,
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

OPENED = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
INSIDE = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
MACHINE_ID = MachineId("vm-01")


@dataclass(frozen=True, slots=True)
class FakePeriodPartyNamesLookup:
    location: str | None = "Loc A"
    technician: str | None = "Tech A"

    def location_name(self, machine_id: MachineId) -> str | None:
        return self.location

    def technician_name(self, technician_id: TechnicianId) -> str | None:
        return self.technician


@dataclass(frozen=True, slots=True)
class ClosePeriodTestOptions:
    accept_opening: bool = True
    accept_closing: bool = True
    accept_loading: bool = True
    sale_occurred_at: datetime | None = CLOSED
    opening_lines: tuple[FrozenInventoryLine, ...] | None = None
    closing_quantity: str = "90"
    closing_lines: tuple[FrozenInventoryLine, ...] | None = None
    loading_packages: str = "20"
    loading_pack_size: str = "1"


def _default_coffee_bom() -> tuple[FakeDomainProductStore, InMemoryCoffeeRecipeRepository]:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="drink-default",
            number="D-DEF",
            name="Default drink",
            catalog_code=None,
            hidden=False,
            kind="coffee_drink",
            legacy_ms_code="2301",
        ),
    )
    store.insert(
        DomainProduct(
            domain_product_id="ing-coffee-1",
            number="I-DEF",
            name="Coffee",
            catalog_code="coffee-1",
            hidden=False,
            kind="coffee_ingredient",
        ),
    )
    repo = InMemoryCoffeeRecipeRepository()
    repo.upsert(
        CoffeeRecipe(
            drink_product_id="drink-default",
            name="Default drink",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id="ing-coffee-1",
                    quantity_per_unit=Decimal("1"),
                ),
            ),
        ),
    )
    return store, repo


def _default_coffee_recipe_repo() -> InMemoryCoffeeRecipeRepository:
    return _default_coffee_bom()[1]


def _default_domain_product_store() -> FakeDomainProductStore:
    return _default_coffee_bom()[0]


def loading_coffee_line(*, packages: str, pack_size: str = "1") -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee-1",
            name="Кофе",
            unit=unit,
            pack_size=Decimal(pack_size),
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(packages),
    )


def gram_revision_line(*, quantity: str) -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee-1",
            name="Кофе",
            unit=unit,
            pack_size=None,
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(quantity),
    )


def coffee_line(quantity: str) -> FrozenInventoryLine:
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee-1",
            name="Кофе",
            unit=ProductUnit.PIECE,
            pack_size=None,
            moysklad_quantity_factor=Decimal("1"),
        ),
        quantity=Decimal(quantity),
    )


def first_revision_event() -> RevisionCompleted:
    return RevisionCompleted(
        event_id=EventId("evt-rev-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MACHINE_ID,
        completed_at=OPENED,
        occurred_at=OPENED,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-rev",
        form_token="token-rev-1",
    )


def second_revision_event() -> RevisionCompleted:
    return RevisionCompleted(
        event_id=EventId("evt-rev-2"),
        revision_id=RevisionId("rev-2"),
        technician_id=TechnicianId("tech-b"),
        machine_id=MACHINE_ID,
        completed_at=CLOSED,
        occurred_at=CLOSED,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-rev",
        form_token="token-rev-2",
    )


def loading_event() -> LoadingSubmitted:
    return LoadingSubmitted(
        event_id=EventId("evt-load-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MACHINE_ID,
        submitted_at=INSIDE,
        occurred_at=INSIDE,
        form_id="form-load",
        form_token="token-load-1",
    )


def build_close_period_deps(
    *,
    options: ClosePeriodTestOptions | None = None,
) -> tuple[
    InMemoryFormSubmissionStore,
    InMemoryMachineRevisionHistoryReader,
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
]:
    opts = options or ClosePeriodTestOptions()
    form_store = InMemoryFormSubmissionStore()
    history = InMemoryMachineRevisionHistoryReader()
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()

    first_revision = first_revision_event()
    second_revision = second_revision_event()
    loading = loading_event()

    history.add_revision(first_revision)
    history.add_revision(second_revision)
    history.add_loading(loading)

    opening_lines = opts.opening_lines or (coffee_line("100"),)
    rev1_pending = form_store.save_pending(
        form_token=first_revision.form_token,
        form_id=first_revision.form_id,
        purpose="revision",
        technician_id=first_revision.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=OPENED,
        answers=(FormAnswer(title="Кофе", value=str(opening_lines[0].quantity)),),
        validated_lines=opening_lines,
    )
    if opts.accept_opening:
        form_store.mark_accepted(
            rev1_pending.submission_id,
            event_id=first_revision.event_id.value,
            occurred_at=OPENED,
            revision_id=first_revision.revision_id.value,
        )

    rev2_pending = form_store.save_pending(
        form_token=second_revision.form_token,
        form_id=second_revision.form_id,
        purpose="revision",
        technician_id=second_revision.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=CLOSED,
        answers=(
            FormAnswer(
                title="Кофе",
                value=str(
                    (opts.closing_lines or (coffee_line(opts.closing_quantity),))[0].quantity
                ),
            ),
        ),
        validated_lines=opts.closing_lines or (coffee_line(opts.closing_quantity),),
    )
    if opts.accept_closing:
        form_store.mark_accepted(
            rev2_pending.submission_id,
            event_id=second_revision.event_id.value,
            occurred_at=CLOSED,
            revision_id=second_revision.revision_id.value,
        )

    load_pending = form_store.save_pending(
        form_token=loading.form_token,
        form_id=loading.form_id,
        purpose="loading",
        technician_id=loading.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=INSIDE,
        answers=(FormAnswer(title="Кофе", value=opts.loading_packages),),
        validated_lines=(
            loading_coffee_line(
                packages=opts.loading_packages,
                pack_size=opts.loading_pack_size,
            ),
        ),
    )
    if opts.accept_loading:
        form_store.mark_accepted(
            load_pending.submission_id,
            event_id=loading.event_id.value,
            occurred_at=INSIDE,
        )

    if opts.sale_occurred_at is not None:
        sales_store.insert_if_absent(
            MachineSale(
                source_id="kv-1",
                machine_id=MACHINE_ID,
                product_code="2301",
                quantity=Decimal("30"),
                occurred_at=opts.sale_occurred_at,
                ingested_at=datetime(2026, 6, 8, 11, 0, tzinfo=UTC),
                sale_kind="coffee",
            ),
        )

    return form_store, history, sales_store, repo


def build_close_period_service(
    *,
    options: ClosePeriodTestOptions | None = None,
    party_names: PeriodPartyNamesLookup | None = None,
) -> tuple[CloseResponsibilityPeriodOnRevision, InMemoryPeriodReconciliationRepository]:
    form_store, history, sales_store, repo = build_close_period_deps(options=options)
    products, recipes = _default_coffee_bom()
    service = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=repo,
        coffee_recipe_repo=recipes,
        domain_product_store=products,
        tolerance_seconds=0,
        party_names_lookup=party_names if party_names is not None else FakePeriodPartyNamesLookup(),
    )
    return service, repo


def build_close_period_handler(
    *,
    sale_occurred_at: datetime,
) -> tuple[
    PeriodReconciliationHandler,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementRepository,
]:
    form_store, history, sales_store, repo = build_close_period_deps(
        options=ClosePeriodTestOptions(sale_occurred_at=sale_occurred_at),
    )
    event_store = InMemoryTechnicianSettlementEventStore()
    settlement_repo = InMemoryTechnicianSettlementRepository(event_store=event_store)
    products, recipes = _default_coffee_bom()
    close_period = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=repo,
        coffee_recipe_repo=recipes,
        domain_product_store=products,
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )
    handler = PeriodReconciliationHandler(
        close_period=close_period,
        post_accountability=PostPeriodAccountability(
            settlement_executor=TechnicianSettlementExecutor(repository=settlement_repo),
            reconciliation_repo=repo,
        ),
    )
    return handler, repo, settlement_repo
