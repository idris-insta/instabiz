# Batch → Production → Serial Traceability — Design

**Date:** 2026-09-10
**Status:** Proposed — decisions locked ("assume the best"), spec ready for build
**Supersedes/extends:** `2026-08-20-container-import-labels-design.md`

---

## Goal

One scannable chain from imported raw material to the box on the customer's dock:

```
Container Import → RM Batch → Work Order(s) → FG Batch → FG Serial (per box/roll)
                → Manufacture Stock Entry → Delivery Note → Customer
```

Scan any serial or batch → full forward + backward genealogy in one screen.
Recall / complaint → scan the box → instant customer + supplier lot.

---

## Locked decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Serial granularity = one Serial No per physical shipping unit** (roll / carton / box). | It's the thing that gets a label and physically moves. Matches the existing per-box label loop. |
| 2 | **Use native ERPNext `Batch` + `Serial No`.** No custom doctypes for these. | Free integration: Stock Ledger, serial-wise valuation, native DN serial picking, batch expiry, `Serial and Batch Bundle`. Container Import already creates native `Batch`. |
| 3 | **Phase 3 (real Manufacture Stock Entries) is in scope.** Ledger-true genealogy is the target end state, delivered last, behind a phased rollout. | Only a real Stock Entry makes the chain provable and enables native DN serial selection + valuation. Phases 1–2 give scannable traceability as annotation in the meantime. |
| 4 | **Batch** on all stockable non-internal groups. **Serial** on roll/sheet FG groups only. | See group table below. Aerosols/sealants ship as cartons-of-many-units → batch is enough; per-carton serial is a later optional add. |
| 5 | **QR payload = trace deep-link** `https://{host}/app/ib-trace?id={serial_or_batch}`. **Code128 barcode = bare serial string** (for laser scanners). | Phone camera → opens the trace page. Handheld scanner → emits the serial into the scan field. Both work. |
| 6 | Assume **hundreds–low-thousands of units/month.** Serials generated in one bulk insert per final-stage completion via `Serial and Batch Bundle`. | Native handles this volume comfortably; no batching/queue needed. |

### Item-group tracking matrix

| Group | Batch | Serial |
|---|---|---|
| PLASTIC, FOAM, FOAM - PE, PAPER, PVC, CLOTH, FOIL, FOIL - ALUMINIUM, REFLECTIVE | ✅ | ✅ (roll/sheet) |
| AEROSOL-* (PAINT/CLEANER/LUBRICANT/MULTI/PU FOAM), SEALANT-ACRYLIC, SEALANT-SILICONE, ADHESIVE-HOTMELT | ✅ | ❌ (carton of many units) |
| PACKAGING (CORE, CTN, LABELS, SHRINK-FILM), Services | ❌ | ❌ |

Driven by two module constants in `instabiz/overrides/item.py`:
`_BATCH_ITEM_GROUPS`, `_SERIAL_ITEM_GROUPS`. `set_batch_no_for_fg` (currently a no-op)
is re-activated to set `has_batch_no` / `has_serial_no` on `before_insert` / `before_save`
from these sets. Existing items backfilled once by group.

---

## Current state (verified in code, 2026-09-10)

- **Container Import** (`ib_container_import.py`) already creates a real native `Batch` per
  batch-tracked row (`_make_batch`), `reference_doctype`/`reference_name` → back to the
  container. Posts a Material Receipt `Stock Entry` on submit. Barcode per row resolved to
  `item_code` (Code128), written onto `Item.barcodes`. Backfill button (2026-09-10) put a
  barcode on all 525 real stock SKUs.
- **`set_batch_no_for_fg`** — body is `pass`. Batch auto-enable is off.
- **Production** (`IB Work Order` / `IB Order Sheet`, `overrides/production.py`) is JIT and
  posts **no** manufacturing stock entries. No RM consumption, no FG receipt in the ledger.
  `IB Production Entry` unused. WO advance through stages is the only source of truth.
- **Serial No** — not used anywhere.
- **Labels** (`IB Container Label` print format) — per box, loop `for row in doc.items` →
  `for box_no in range(1, no_of_boxes+1)`. Shows SKU barcode + QR-of-SKU + `ROLL NO i / N`.
  No unique per-box identifier.
- **Scan** (`ib-stock-scan`, `stock_scan.py`) — resolves a scanned barcode to an Item via
  `Item Barcode`, then Add / Deduct posts a Stock Entry. No batch/serial awareness.

---

## Target data model

### Native `Batch` — custom fields (fixtures)

| Field | Type | Source |
|---|---|---|
| `custom_container_import` | Link → IB Container Import | set by `_make_batch` |
| `custom_container_no` | Data | container row |
| `custom_supplier_lot` | Data | container row (new field on `IB Container Import Item`) |
| `custom_gsm` | Float | `Item.gsm` at receipt |
| `custom_width_mm` | Float | `Item.width_mm` at receipt |
| `custom_received_date` | Date | container `import_date` |
| `custom_batch_kind` | Select: `Raw Material` / `Finished Good` | `Raw Material` from Container Import; `Finished Good` from production |
| `custom_parent_batches` | Small Text (JSON list) | FG batch → the RM batch names it consumed |
| `custom_work_order` | Link → IB Work Order | FG batch only |

### Native `Serial No` — custom fields (fixtures)

| Field | Type |
|---|---|
| `custom_work_order` | Link → IB Work Order |
| `custom_order_sheet` | Link → IB Order Sheet |
| `custom_sales_order` | Link → Sales Order |
| `custom_source_batch` | Link → Batch (RM) |
| `custom_fg_batch` | Link → Batch (FG) |
| `custom_produced_on` | Datetime |
| `custom_width_mm` / `custom_length_mtr` / `custom_gsm` | Float |
| `custom_box_no` | Int (i of N in its production run) |
| `custom_delivery_note` | Data (stamped on DN submit) |
| `custom_customer` | Link → Customer (stamped on DN submit) |

### `IB Work Order` — new fields

| Field | Type | Notes |
|---|---|---|
| `source_batch` | Link → Batch | primary RM batch; set when the first stage starts, threaded to child stages |
| `fg_batch` | Link → Batch | created at final-stage completion |
| `produced_serials` | Int (read-only) | count generated |

Multi-input: child table **`IB WO Batch Consumption`** (`batch`, `qty`, `item_code`) on
`IB Work Order` for the case where one WO draws from more than one RM batch.

### New doctype — none for tracking. One new **Page**: `ib-trace`.

### Serial naming

`{item_code}::{YYMMDD}::{seq04}` — e.g. `IS-51210V-029TRNANL::260910::0007`.
Deterministic, human-readable, sortable. `seq` resets per (item, day). Code128 barcode =
this exact string. QR = `{host}/app/ib-trace?id=<serial>`.

---

## Genealogy chain

```
IB Container Import  ──creates──▶  Batch (kind=Raw Material)
      │                                  │
      │ Material Receipt Stock Entry     │ referenced by
      ▼                                  ▼
   stock in                        IB Work Order.source_batch
                                         │  (threaded stage → stage)
                                         ▼
                             final stage complete
                                         │
              ┌──────────────────────────┼───────────────────────────┐
              ▼                          ▼                           ▼
     Batch (kind=Finished Good)   N × Serial No            Manufacture Stock Entry   (Phase 3)
     custom_parent_batches=[RM]   custom_source_batch=RM   RM batch qty  OUT
     custom_work_order=WO         custom_fg_batch=FG       FG batch+serials IN
                                  custom_work_order=WO
                                         │
                                         ▼
                              Delivery Note (serial selection)
                                         │ on submit: stamp
                                         ▼
                     Serial No.custom_delivery_note / custom_customer
```

Backward trace from a serial: serial → `custom_fg_batch` → `custom_parent_batches` →
RM `Batch.custom_container_import` → supplier + lot.
Forward trace from a container: container → its RM batches → WOs with that `source_batch`
→ their FG batches → serials → DNs → customers.

---

## Phased implementation

### Phase 1 — Batch genealogy (annotation only, no ledger change)

**Deliverables**
1. Re-activate `set_batch_no_for_fg` → set `has_batch_no=1` for `_BATCH_ITEM_GROUPS` on
   `before_insert`/`before_save`. One-time backfill by group (script, not migrate).
2. `Batch` custom fields (above). `IB Container Import Item.custom_supplier_lot` (Data).
   `_make_batch` enriched to populate them + `custom_batch_kind="Raw Material"`.
3. `IB Work Order.source_batch` + `IB WO Batch Consumption` child table.
   `production.py`: when a stage starts, if `source_batch` is blank, resolve it —
   from the Sales Order's originating Container Import if one exists, else prompt in the
   start dialog (new optional "RM Batch" field). Threaded to the stage's downstream WOs.
4. **`ib-trace` page (read-only)** — input a Batch or WO → render the chain built so far
   (Container → RM Batch → WO stages). Serial section shows "not yet produced".
5. `ib-stock-scan`: if the scanned code resolves to a `Batch` (not just an Item barcode),
   show batch detail + link to `ib-trace`.

**Files:** `overrides/item.py`, `overrides/production.py`,
`doctype/ib_container_import/*`, `doctype/ib_work_order/*`, new
`doctype/ib_wo_batch_consumption/*`, new `page/ib_trace/*`, `page/ib_stock_scan/*`,
`fixtures/custom_field.json`, `hooks.py`.

**Risk:** Low. No stock-posting change. `has_batch_no=1` on an item with existing stock is
safe in ERPNext (existing ledger entries stay batch-null; new ones require a batch).
**Rollback:** set the group constants to empty, re-run backfill to clear flags on
zero-transaction items; `ib-trace` / scan changes are additive.
**Test:** run a real Container Import → confirm enriched RM batch; start a WO → confirm
`source_batch` threads to child-stage WOs; `ib-trace` renders the partial chain.

---

### Phase 2 — FG serials at production

**Deliverables**
1. `has_serial_no=1` for `_SERIAL_ITEM_GROUPS` (backfill by group).
2. `Serial No` custom fields (above).
3. `production.py` final-stage `complete_work_order()` / `advance_to_next_stage()`:
   - Create the FG `Batch` (`custom_batch_kind="Finished Good"`,
     `custom_parent_batches=[source_batch, …]`, `custom_work_order`).
   - Generate **N Serial No** (N = actual boxes/rolls from the completion `actual_qty`
     already captured 2026-08-30) via one `Serial and Batch Bundle`, each stamped with WO /
     order sheet / SO / batches / dimensions / `custom_box_no`.
   - Write `fg_batch` + `produced_serials` back on the WO (post-`apply_workflow`
     `db.set_value`, same pattern the file already uses for `completed_at`).
4. **New label format `IB Serial Label`** (doctype `IB Work Order`, A6, per-serial loop):
   unique serial Code128 + QR(trace URL) + item / dims / batch / box i-of-N / WO / date.
   WO panel + Stages tab gain a "Print Serial Labels" action once a stage is Completed.
   `IB Container Label` stays for imported/traded goods that skip production.
5. `ib-stock-scan`: scanning a serial → item + FG batch + WO + warehouse + status, link to
   `ib-trace`.
6. `ib-trace` page: serial section now populated; supports serial as the input id;
   forward + backward both rendered.

**Files:** `overrides/item.py`, `overrides/production.py`,
`doctype/ib_work_order/*`, new `print_format/ib_serial_label/*`,
`public/js/ib_production_dashboard.js` (WO panel + Stages actions),
`page/ib_stock_scan/*`, `page/ib_trace/*`, `fixtures/custom_field.json`.

**Risk:** Medium. Serial generation adds N inserts per completion — bounded by a per-run
cap (reuse `_MAX_LABEL_COUNT = 2000`). If serial creation fails, the WO completion still
succeeds (serials generated in a `try` with `frappe.log_error`, ret/re-print action to
recover). No valuation impact yet (Phase 3).
**Rollback:** empty `_SERIAL_ITEM_GROUPS`, disable the generation block; labels + trace are
additive.
**Test:** disposable WO through the full route → confirm FG batch + N serials with correct
genealogy fields; print `IB Serial Label` (`pdfinfo`/`pdftotext` page-count + content);
scan a generated serial on `ib-stock-scan`; `ib-trace` full chain both directions.

---

### Phase 3 — Real Manufacture Stock Entries (ledger-true)

**Deliverables**
1. Final-stage completion posts a `Stock Entry` (`stock_entry_type = "Manufacture"`):
   - **Consume:** `source_batch` (+ `IB WO Batch Consumption` rows) qty from the WIP/RM
     warehouse.
   - **Produce:** FG `item_code` + FG `Batch` + the N `Serial No` into the location's FG
     warehouse, at a `basic_rate` derived from consumed RM valuation + a configurable
     conversion cost (new singleton `IB Production Cost Setting`, or flat 0 to start).
   - Linked back: `IB Work Order.custom_stock_entry`.
2. `on_cancel` of the WO / Order Sheet reverses it (cancel the Manufacture Stock Entry,
   which unwinds batch + serial ledger).
3. Container Import for **manufactured** input items switches from Material Receipt into the
   FG warehouse → Material Receipt into an **RM warehouse** (new per-location RM warehouses,
   or reuse floor sub-warehouses from `IB Production Floor`, 2026-08-27). Traded goods
   unchanged.
4. Stock Dashboard / Ledger / DPR already read the ledger — they light up automatically.

**Files:** `overrides/production.py` (largest change), `overrides/delivery_note.py`
(FG warehouse resolution), new `doctype/ib_production_cost_setting/*`,
`doctype/ib_work_order/*` (`custom_stock_entry`), warehouse masters, `hooks.py`.

**Risk:** High — touches the JIT production model + stock valuation + negative-stock
behaviour. Roll out per location (Gujarat factory first; Maharashtra/Chennai are
warehouse-only and skip manufacture entirely). Feature-flag via
`site_config` key `ib_production_posts_stock` (default off) so Phases 1–2 stay live while
Phase 3 is validated.
**Rollback:** flag off → completion reverts to annotation-only; existing Manufacture
entries are normal cancellable Stock Entries.
**Test:** full disposable lifecycle on a real Gujarat SO — RM in via Container Import,
WO through route, Manufacture entry posts (balanced GL + SLE + batch + serial ledger),
DN ships with serial selection, cancel unwinds cleanly. Verify Stock Dashboard / Ledger /
DPR reflect it. Negative-stock path: RM short → ERPNext blocks (correct).

---

### Phase 4 — DN serial capture + recall tooling

**Deliverables**
1. DN item rows: native serial selection (available once `has_serial_no=1`, Phase 2).
   `custom_make_delivery_note()` carries the WO's produced serials as the default
   selection for that item row.
2. DN `on_submit`: stamp `Serial No.custom_delivery_note` + `custom_customer`.
3. **`ib-trace` recall mode:** input a batch or serial → list every serial in that batch,
   its DN, its customer, ship date — one exportable table for a recall notice.
4. `ib-stock-scan` "Dispatch" mode: scan serials onto an open DN.

**Files:** `overrides/delivery_note.py`, `overrides/sales_order.py`,
`page/ib_trace/*`, `page/ib_stock_scan/*`.

**Risk:** Medium. Depends on Phase 2 (serials exist) and ideally Phase 3 (native DN serial
validation against the ledger). Without Phase 3, serial-on-DN is annotation.
**Test:** ship a disposable DN with serials → confirm stamp-back; recall table lists the
right customers; reverse trace from a shipped serial reaches the supplier lot.

---

## Rollout checklist per phase

| Change type | Command |
|---|---|
| Python (`overrides/*.py`, `hooks.py`) | `bench restart` (user runs — never kill the bench process) |
| Fixtures (`custom_field.json`, new doctypes) | `bench --site frontend migrate` |
| `hooks.py` | `bench --site frontend clear-cache` |
| JS / print formats | `bench build --app instabiz` |
| Group-flag backfill | one-off script via `bench --site frontend console`, `doc.save()` per item, not raw SQL for `has_batch_no`/`has_serial_no` (controller side-effects) |

All live testing on disposable docs, cleaned up by exact name (per standing rule).

---

## Deliberately deferred

- Per-carton serials for aerosols/sealants (batch is enough for now).
- Serial-wise valuation reporting (native once Phase 3 lands; no custom report planned).
- Customer-facing trace (public web page from the QR) — internal `/app/ib-trace` only for now.
- Barcode/serial on the RM batch label itself (Container Import label already covers the box).
- Integration with `IB Production Floor` warehouse routing beyond Phase 3's RM-warehouse split.

---

## Open items needing a real-data answer before Phase 3

- Confirmed list of **manufactured** vs **purely traded** item groups (drives the
  Container-Import-into-RM-warehouse switch). Assumption: PLASTIC/FOAM/CLOTH/PAPER/PVC/
  FOIL/REFLECTIVE are manufactured at Gujarat; AEROSOL/SEALANT/ADHESIVE are traded.
- Conversion cost model for FG valuation (flat 0 / % uplift / `IB Production Cost Setting`).
- Whether existing open WOs at rollout get retro-fitted with a `source_batch` or start clean.
