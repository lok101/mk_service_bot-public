from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from beartype import beartype

from src.application.master_data.location_address import effective_location_display_name
from src.application.master_data.models import (
    LOCATION_COUNTER_KEY,
    MasterLocation,
    MasterPlacement,
)
from src.application.master_data.ports import MasterDataStores
from src.application.sheets.locations_directory import (
    LocationPlacement,
    build_locations_directory_snapshot,
)
from src.domain.ids import MachineId

_REMAP_TEMP_PREFIX = "__location_remap__"
_COORDINATE_TOLERANCE = Decimal("0.00001")


@beartype
@dataclass(frozen=True, slots=True)
class PlacementMatchKey:
    machine_id: MachineId
    valid_from: date
    valid_to: date | None


@beartype
@dataclass(frozen=True, slots=True)
class LocationIdMatch:
    domain_location_id: str
    canonical_location_id: str
    machine_id: MachineId
    valid_from: date
    valid_to: date | None
    csv_name: str
    domain_name: str
    name_matches: bool


@beartype
@dataclass(frozen=True, slots=True)
class ReconcileLocationIdsReport:
    matched: tuple[LocationIdMatch, ...]
    unchanged_count: int
    extra_domain_keys: tuple[PlacementMatchKey, ...]
    errors: tuple[str, ...]
    coordinate_warnings: tuple[str, ...]
    location_id_remap: dict[str, str]

    @property
    def name_mismatches(self) -> tuple[LocationIdMatch, ...]:
        return tuple(match for match in self.matched if not match.name_matches)

    @property
    def ok(self) -> bool:
        return not self.errors


@beartype
def load_locations_directory_csv_rows(path: Path) -> list[list[str]]:
    sample = path.read_text(encoding="utf-8-sig")[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [list(row) for row in csv.reader(handle, dialect)]


@beartype
def reconcile_location_ids(
    stores: MasterDataStores,
    *,
    csv_rows: list[list[str]],
    allow_extra_domain: bool = False,
) -> ReconcileLocationIdsReport:
    directory = build_locations_directory_snapshot(csv_rows)
    domain_by_key = _index_domain_placements(stores.placements.list_all())
    matched: list[LocationIdMatch] = []
    errors: list[str] = []
    coordinate_warnings: list[str] = []
    remap: dict[str, str] = {}
    unchanged_count = 0
    matched_domain_keys: set[PlacementMatchKey] = set()

    for csv_placement in directory.placements:
        key = _placement_key_from_csv(csv_placement)
        domain_candidates = domain_by_key.get(key, ())
        if not domain_candidates:
            errors.append(
                "csv row not found in domain: "
                f"location_id={csv_placement.location_id!r} "
                f"machine_id={csv_placement.machine_id.value!r} "
                f"valid_from={key.valid_from.isoformat()} "
                f"valid_to={_format_optional_date(key.valid_to)}",
            )
            continue
        if len(domain_candidates) > 1:
            errors.append(
                "ambiguous domain placements for csv row: "
                f"location_id={csv_placement.location_id!r} "
                f"machine_id={csv_placement.machine_id.value!r} "
                f"valid_from={key.valid_from.isoformat()} "
                f"valid_to={_format_optional_date(key.valid_to)}",
            )
            continue

        domain_placement = domain_candidates[0]
        matched_domain_keys.add(key)
        domain_location = stores.locations.get(domain_placement.location_id)
        if domain_location is None:
            errors.append(
                "domain placement references missing location: "
                f"location_id={domain_placement.location_id!r} "
                f"placement_id={domain_placement.placement_id!r}",
            )
            continue

        domain_name = effective_location_display_name(
            name=domain_location.name,
            city=domain_location.city,
            street=domain_location.street,
            house=domain_location.house,
            display_name=domain_location.display_name,
        )
        name_matches = _normalize_label(csv_placement.name) == _normalize_label(domain_name)
        if not name_matches and _normalize_label(domain_location.display_name):
            name_matches = _normalize_label(csv_placement.name) == _normalize_label(
                domain_location.display_name,
            )

        coordinate_warning = _coordinate_mismatch(csv_placement, domain_location)
        if coordinate_warning is not None:
            coordinate_warnings.append(coordinate_warning)

        canonical_id = csv_placement.location_id
        domain_id = domain_placement.location_id
        if domain_id == canonical_id:
            unchanged_count += 1
        else:
            previous = remap.get(domain_id)
            if previous is not None and previous != canonical_id:
                errors.append(
                    f"inconsistent remap for domain location_id={domain_id!r}: "
                    f"{previous!r} vs {canonical_id!r}",
                )
            remap[domain_id] = canonical_id

        matched.append(
            LocationIdMatch(
                domain_location_id=domain_id,
                canonical_location_id=canonical_id,
                machine_id=csv_placement.machine_id,
                valid_from=key.valid_from,
                valid_to=key.valid_to,
                csv_name=csv_placement.name,
                domain_name=domain_name,
                name_matches=name_matches,
            ),
        )

    extra_domain_keys = tuple(
        sorted(
            (key for key in domain_by_key if key not in matched_domain_keys),
            key=_sort_match_key,
        ),
    )
    if extra_domain_keys and not allow_extra_domain:
        for key in extra_domain_keys:
            errors.append(
                "domain placement missing in csv: "
                f"machine_id={key.machine_id.value!r} "
                f"valid_from={key.valid_from.isoformat()} "
                f"valid_to={_format_optional_date(key.valid_to)}",
            )

    return ReconcileLocationIdsReport(
        matched=tuple(matched),
        unchanged_count=unchanged_count,
        extra_domain_keys=extra_domain_keys,
        errors=tuple(errors),
        coordinate_warnings=tuple(coordinate_warnings),
        location_id_remap=remap,
    )


@beartype
def apply_location_id_remap(
    stores: MasterDataStores,
    remap: dict[str, str],
) -> int:
    changed = {old_id: new_id for old_id, new_id in remap.items() if old_id != new_id}
    if not changed:
        return 0

    temp_to_final: dict[str, str] = {}
    for old_id, new_id in changed.items():
        location = stores.locations.get(old_id)
        if location is None:
            raise ValueError(f"missing domain location for remap: {old_id!r}")
        temp_id = f"{_REMAP_TEMP_PREFIX}{old_id}"
        stores.locations.upsert(replace(location, location_id=temp_id))
        stores.locations.delete(old_id)
        temp_to_final[temp_id] = new_id

    for temp_id, final_id in temp_to_final.items():
        location = stores.locations.get(temp_id)
        if location is None:
            raise ValueError(f"missing temp location during remap: {temp_id!r}")
        stores.locations.upsert(replace(location, location_id=final_id))
        stores.locations.delete(temp_id)

    for placement in stores.placements.list_all():
        new_location_id = remap.get(placement.location_id, placement.location_id)
        if new_location_id != placement.location_id:
            stores.placements.update(
                replace(placement, location_id=new_location_id),
            )

    stores.counters.set(
        LOCATION_COUNTER_KEY,
        _max_numeric_location_id(stores.locations.list_all()),
    )
    return len(changed)


@beartype
def _index_domain_placements(
    placements: tuple[MasterPlacement, ...],
) -> dict[PlacementMatchKey, tuple[MasterPlacement, ...]]:
    grouped: dict[PlacementMatchKey, list[MasterPlacement]] = {}
    for placement in placements:
        key = _placement_key_from_domain(placement)
        grouped.setdefault(key, []).append(placement)
    return {key: tuple(items) for key, items in grouped.items()}


@beartype
def _placement_key_from_csv(placement: LocationPlacement) -> PlacementMatchKey:
    return PlacementMatchKey(
        machine_id=placement.machine_id,
        valid_from=placement.installed_on,
        valid_to=placement.removed_on,
    )


@beartype
def _placement_key_from_domain(placement: MasterPlacement) -> PlacementMatchKey:
    return PlacementMatchKey(
        machine_id=placement.machine_id,
        valid_from=_utc_date(placement.valid_from),
        valid_to=None if placement.valid_to is None else _utc_date(placement.valid_to),
    )


@beartype
def _utc_date(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(UTC).date()


@beartype
def _normalize_label(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).casefold()


@beartype
def _format_optional_date(value: date | None) -> str:
    return "" if value is None else value.isoformat()


@beartype
def _sort_match_key(key: PlacementMatchKey) -> tuple[str, str, str]:
    return (
        key.machine_id.value,
        key.valid_from.isoformat(),
        _format_optional_date(key.valid_to),
    )


@beartype
def _coordinates_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= _COORDINATE_TOLERANCE


@beartype
def _coordinate_mismatch(
    csv_placement: LocationPlacement,
    domain_location: MasterLocation,
) -> str | None:
    if (
        csv_placement.latitude is not None
        and domain_location.latitude is not None
        and not _coordinates_match(csv_placement.latitude, domain_location.latitude)
    ):
        return (
            f"latitude mismatch for location_id={csv_placement.location_id!r} "
            f"csv={csv_placement.latitude} domain={domain_location.latitude}"
        )
    if (
        csv_placement.longitude is not None
        and domain_location.longitude is not None
        and not _coordinates_match(csv_placement.longitude, domain_location.longitude)
    ):
        return (
            f"longitude mismatch for location_id={csv_placement.location_id!r} "
            f"csv={csv_placement.longitude} domain={domain_location.longitude}"
        )
    return None


@beartype
def _max_numeric_location_id(locations: tuple[MasterLocation, ...]) -> int:
    max_value = 0
    for location in locations:
        try:
            max_value = max(max_value, int(location.location_id))
        except ValueError:
            continue
    return max_value
