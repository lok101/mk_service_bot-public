"""Conventions for MoySklad JSON API ``expand`` in this package.

Prefer ``expand`` over N+1 ``GET`` of linked entities (stores, agents, …).
Per-entity GETs in a list window burn the account rate limit (HTTP 429 / code
1049) — that is what broke technician-warehouse ``sync-transfers`` when
resolving every ``sourceStore`` / ``targetStore`` via ``/entity/store/{id}``.

API rules (Remap 1.2 — keep ``limit`` ≤ :data:`EXPAND_MAX_LIMIT` or the server
**silently ignores** ``expand``):

https://dev.moysklad.ru/doc/api/remap/1.2/#/general#4-na-expand-dejstvuyut-sleduyushie-pravila

- ``expand`` allowed only when sample size ``limit`` ≤ 100
- Max nesting depth: 3
- Also applies to create/update response expansions

**``/entity/move`` store codes**

Use :data:`MOVE_LIST_STORE_EXPAND` on the move list so each row embeds store
objects (including ``code``). Read codes from the expanded payload; do **not**
default to ``GET /entity/store/{id}`` for every unique store in the window.

- Expanded store with empty / missing ``code`` → soft-skip that endpoint (see
  technician-warehouse soft-resolve); **no** fallback GET.
- Linked field still meta-only (not expanded) → optional single-id fallback GET.
- If ``expand`` looks ignored for the whole window (all endpoints meta-only) →
  fail fast (`MoySkladUnavailable`), do **not** fall back to mass GET.

When adding a new list reader that needs fields of a linked entity, add an
``expand=…`` constant here and wire it into the list request first.

Audit snapshot (N+1 / expand / rate-limit) — 2026-07-21
=======================================================

**Must fix (active or broken contract):**

_(none)_

**Fixed:**

- ``technician_warehouse_transfer_reader._resolve_store_codes`` — expand list +
  read ``code`` + guards (expand dead / meta-only cap / conflict); fallback GET
  only for meta-only ids ≤ ``META_ONLY_FALLBACK_CAP``.
- ``MoySkladClient.get_inventory_positions`` — paginates with
  ``expand=assortment`` and ``limit≤EXPAND_MAX_LIMIT`` (was ``limit=1000``,
  which silently dropped expand).

**Fixed (LOK-178):**

- ``technician_warehouse_transfer_reader`` — after store filter, positions via
  batched ``GET /entity/move?filter=id=…&expand=positions.assortment``
  (chunks ``limit≤EXPAND_MAX_LIMIT``); no per-move ``GET …/positions``.

**Watch / document (volume or latent; not the same N+1-store bug):**

- ``ensure_supply_store_codes_exist`` — 1 GET filter/store code; N is env size
  (usually tiny). Keep batch/filter if list grows.
- ``MoySkladPurchasePricesHttpClient`` — 1 supply GET per product card with
  concurrency cap (``MATRIX_SUPPLY_FETCH_CONCURRENCY``); known matrix risk.
- ``MoySkladHttpTransport`` — network/timeout retries + process-local async
  rate limit / 429 backoff + one in-request retry
  (docs/specs/2026-09-11-moysklad-rate-limit-design.md · LOK-177).
  Volume still matters: prefer ``expand``.
- ``resolve_assortments_by_codes`` — 3 batch list GETs (product/variant/bundle);
  watch filter length on huge code sets.
- ``get_stock_report_bystore`` — paginated report (``limit=1000`` + ``offset``),
  no expand; covers warehouses with more than one page of stock rows.
- Single ``get_store_id_by_code`` in registrars (inventory/loading/stock) —
  O(1) per write; fine.
"""

from __future__ import annotations

# Server ignores ``expand`` when limit > this value.
EXPAND_MAX_LIMIT = 100

# Depth-1 expand on move list: full store objects (id, name, code, …).
MOVE_LIST_STORE_EXPAND = "sourceStore,targetStore"

# Max unique meta-only store ids eligible for per-id GET when expand is alive.
# Breach → MoySkladUnavailable (see technician warehouse transfer reader).
META_ONLY_FALLBACK_CAP = 5

# Positions expand (move / inventory). Always pair with limit ≤ EXPAND_MAX_LIMIT.
POSITIONS_ASSORTMENT_EXPAND = "assortment"

# Batch re-fetch of tech-relevant moves after store filter (LOK-178).
MOVE_POSITIONS_EXPAND = "positions.assortment"

# Nested productFolder chain for supply-order category (depth ≤3).
PRODUCT_FOLDER_ANCESTOR_EXPAND = "productFolder.productFolder.productFolder"

# Product list expand for category facts sync (attrs + folder ancestors).
SUPPLY_ORDER_CATEGORY_PRODUCT_EXPAND = f"attributes,{PRODUCT_FOLDER_ANCESTOR_EXPAND}"
