from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.application.micromarket_loading.shop_list_publish_journal import (
    JOURNAL_CAPACITY,
    ShopListIntendedLine,
    ShopListPublishEffects,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
    diff_shop_list_intended,
    shop_list_publish_effects_detail_lines,
    shop_list_publish_effects_summary,
    shop_list_publish_trigger_label,
)
from src.infrastructure.testing.micromarket_loading_fakes import InMemoryShopListPublishJournal

_T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def test_append_running_and_list_newest() -> None:
    journal = InMemoryShopListPublishJournal()

    journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-1",
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=_T0,
            updated_at=_T0,
        )
    )

    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].publication_id == "pub-1"
    assert rows[0].machine_code == "701"
    assert rows[0].status is ShopListPublishJournalStatus.RUNNING
    assert rows[0].trigger is None
    assert rows[0].effects == ShopListPublishEffects()


def test_update_by_publication_id_to_succeeded_and_failed() -> None:
    journal = InMemoryShopListPublishJournal()
    journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-ok",
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=_T0,
            updated_at=_T0,
            trigger=ShopListPublishTrigger.MANUAL,
            effects=ShopListPublishEffects(updated_product_codes=("n-1",)),
        )
    )
    journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-fail",
            machine_code="702",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=_T0,
            updated_at=_T0,
            trigger=ShopListPublishTrigger.INVENTORY_ZERO,
            effects=ShopListPublishEffects(disabled_product_codes=("n-2",)),
        )
    )

    t1 = _T0 + timedelta(minutes=1)
    journal.update_by_publication_id(
        "pub-ok",
        status=ShopListPublishJournalStatus.SUCCEEDED,
        now=t1,
    )
    journal.update_by_publication_id(
        "pub-fail",
        status=ShopListPublishJournalStatus.FAILED,
        error_message="timeout",
        now=t1,
    )

    by_id = {row.publication_id: row for row in journal.list_newest()}
    assert by_id["pub-ok"].status is ShopListPublishJournalStatus.SUCCEEDED
    assert by_id["pub-ok"].error_message == ""
    assert by_id["pub-ok"].updated_at == t1
    assert by_id["pub-ok"].trigger is ShopListPublishTrigger.MANUAL
    assert by_id["pub-ok"].effects.updated_product_codes == ("n-1",)
    assert by_id["pub-fail"].status is ShopListPublishJournalStatus.FAILED
    assert by_id["pub-fail"].error_message == "timeout"
    assert by_id["pub-fail"].effects.disabled_product_codes == ("n-2",)


def test_trim_drops_oldest_when_capacity_exceeded() -> None:
    journal = InMemoryShopListPublishJournal()
    for index in range(JOURNAL_CAPACITY + 1):
        created = _T0 + timedelta(seconds=index)
        journal.append(
            ShopListPublishJournalEntry(
                publication_id=f"pub-{index:03d}",
                machine_code="701",
                status=ShopListPublishJournalStatus.RUNNING,
                created_at=created,
                updated_at=created,
            )
        )

    rows = journal.list_newest()
    assert len(rows) == JOURNAL_CAPACITY
    ids = {row.publication_id for row in rows}
    assert "pub-000" not in ids
    assert f"pub-{JOURNAL_CAPACITY:03d}" in ids
    assert rows[0].publication_id == f"pub-{JOURNAL_CAPACITY:03d}"


def _line(
    code: str,
    *,
    price: str = "10",
    group: int = 1,
    off: bool = False,
) -> ShopListIntendedLine:
    return ShopListIntendedLine(
        product_code=code,
        price_rub=Decimal(price),
        kit_group_id=group,
        availability_off=off,
    )


def test_diff_no_baseline_marks_all_added_and_disabled_bucket() -> None:
    # edge: no baseline → intended → added (+ availability buckets)
    effects = diff_shop_list_intended(
        None,
        (_line("a"), _line("b", off=True)),
    )
    assert effects.added_product_codes == ("a", "b")
    assert effects.disabled_product_codes == ("b",)
    assert effects.enabled_product_codes == ()
    assert effects.removed_product_codes == ()
    assert effects.updated_product_codes == ()


def test_diff_price_change_marks_updated() -> None:
    # happy: manual vs baseline price change → updated
    baseline = (_line("a", price="10"),)
    intended = (_line("a", price="12"),)
    effects = diff_shop_list_intended(baseline, intended)
    assert effects.updated_product_codes == ("a",)
    assert effects.added_product_codes == ()
    assert effects.removed_product_codes == ()


def test_diff_availability_off_marks_disabled_and_updated() -> None:
    baseline = (_line("a", off=False),)
    intended = (_line("a", off=True),)
    effects = diff_shop_list_intended(baseline, intended)
    assert effects.disabled_product_codes == ("a",)
    assert effects.updated_product_codes == ("a",)
    assert effects.enabled_product_codes == ()


def test_diff_availability_on_marks_enabled_and_updated() -> None:
    # LOK-314 contract surface for inventory_restore / enabled_*
    baseline = (_line("a", off=True),)
    intended = (_line("a", off=False),)
    effects = diff_shop_list_intended(baseline, intended)
    assert effects.enabled_product_codes == ("a",)
    assert effects.updated_product_codes == ("a",)


def test_diff_removed_when_code_absent_from_intended() -> None:
    baseline = (_line("a"), _line("b"))
    intended = (_line("a"),)
    effects = diff_shop_list_intended(baseline, intended)
    assert effects.removed_product_codes == ("b",)


def test_trigger_labels_ru() -> None:
    assert shop_list_publish_trigger_label(ShopListPublishTrigger.MANUAL) == "Опубликовать"
    assert (
        shop_list_publish_trigger_label(ShopListPublishTrigger.INVENTORY_ZERO) == "система · нуль"
    )
    assert (
        shop_list_publish_trigger_label(ShopListPublishTrigger.INVENTORY_RESTORE)
        == "система · восстановление"
    )
    assert (
        shop_list_publish_trigger_label(ShopListPublishTrigger.PENDING_EXIT) == "система · выбытие"
    )
    assert (
        shop_list_publish_trigger_label(ShopListPublishTrigger.POST_VISIT_SQUEEZE)
        == "система · пост-визитный дожим"
    )
    assert shop_list_publish_trigger_label(None) == "публикация"


def test_effects_summary_omits_zero_segments() -> None:
    assert shop_list_publish_effects_summary(ShopListPublishEffects()) == ""
    summary = shop_list_publish_effects_summary(
        ShopListPublishEffects(
            disabled_product_codes=("a", "b"),
            enabled_product_codes=("c",),
            added_product_codes=("d",),
            removed_product_codes=("e",),
            updated_product_codes=("f",),
        )
    )
    assert summary == "снято 2 · возвращено 1 · +1 −1 ~1"


def test_effects_detail_lines_list_product_codes() -> None:
    # happy: one detail line per SKU (codes when names missing)
    lines = shop_list_publish_effects_detail_lines(
        ShopListPublishEffects(
            disabled_product_codes=("a", "b"),
            enabled_product_codes=("c",),
            added_product_codes=("d",),
            removed_product_codes=("e",),
        )
    )
    assert lines == (
        "снято: a",
        "снято: b",
        "возвращено: c",
        "добавлено: d",
        "убрано: e",
    )


def test_effects_detail_lines_empty_when_no_effects() -> None:
    # edge: empty effects → empty detail (UI placeholder)
    assert shop_list_publish_effects_detail_lines(ShopListPublishEffects()) == ()


def test_effects_detail_lines_use_catalog_names() -> None:
    # happy: disabled/updated show names; one line per SKU
    lines = shop_list_publish_effects_detail_lines(
        ShopListPublishEffects(
            disabled_product_codes=("d-10",),
            updated_product_codes=("d-103",),
        ),
        {"d-10": "Вода 0.5", "d-103": "Сок яблоко"},
        intended_lines=(_line("d-103", price="45"),),
        baseline_lines=(_line("d-103", price="40"),),
    )
    assert lines == (
        "снято: Вода 0.5",
        "изменено: Сок яблоко — цена 40→45 ₽",
    )


def test_effects_detail_lines_unknown_code_falls_back_to_code() -> None:
    # edge: unknown code → fallback to product code
    lines = shop_list_publish_effects_detail_lines(
        ShopListPublishEffects(added_product_codes=("ghost",)),
        {"other": "Имя"},
    )
    assert lines == ("добавлено: ghost",)


def test_effects_detail_lines_updated_explains_availability_and_group() -> None:
    # happy: updated bucket explains availability / kit group from intended vs baseline
    lines = shop_list_publish_effects_detail_lines(
        ShopListPublishEffects(updated_product_codes=("x", "y")),
        {"x": "Товар X", "y": "Товар Y"},
        intended_lines=(_line("x", off=True), _line("y", group=7)),
        baseline_lines=(_line("x", off=False), _line("y", group=3)),
    )
    assert lines == (
        "изменено: Товар X — доступность: снят",
        "изменено: Товар Y — группа 3→7",
    )
