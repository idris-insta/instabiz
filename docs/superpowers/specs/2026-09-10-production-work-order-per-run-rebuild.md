# Production Rebuild — Work Order = one run, moves through stages, ledger-true

**Date:** 2026-09-10
**Status:** Proposed — design locked with user, ready to build on a branch
**Related:** `2026-09-10-batch-serial-traceability-design.md` (IB Batch / IB FG Serial), Path B (DN→RM batch link) already shipped in `8383b54`.

---

## Why

Today `IB Work Order` = one (item × stage). A 5-stage item = 5 Work Orders. Confusing, no single "run" to point at, hard to trace, and every dashboard tab / DPR / machine view is bent around it. Production is still in testing (data wiped several times) — right time to rebuild.

## Target model

**One `IB Work Order` = one production run**, start to finish:

```
IB Work Order  (the run)
├─ sales_order, order_sheet, priority, created_by, created_at
├─ source_batch        Link → IB Batch   (the ONE raw-material / jumbo batch this run consumes)
├─ source_warehouse    Link → Warehouse  (where the RM sits — from the container/GRN)
├─ route []            child: IB WO Route Stage  — the plan (ordered stages this run passes through)
├─ current_stage       Data  (which route stage is active now; "Done" when finished)
├─ machine             Link → IB Machine (the machine at the current stage)
├─ status              Select: Draft / In Progress / On Hold / Completed / Cancelled  (Frappe workflow)
├─ outputs []          child: IB WO Output  — item_code, planned_qty, produced_qty, fg_batch, serial_count
├─ stage_log []        child: IB WO Stage Event — stage, machine, operator, started_at, completed_at, output_qty, wastage_qty, notes
├─ fg_batch            Link → IB Batch (kind=Finished Good) — created at final stage; parent_batches=[source_batch]
├─ stock_entry         Link → Stock Entry — the Repack posted at final stage
└─ total_wastage_qty   Float (read-only, summed from stage_log)
```

### Child doctypes (new)

| Doctype | Fields |
|---|---|
| `IB WO Route Stage` | `stage` (Select: Coating/Slitting/Rewinding/Cutting/Packing), `sequence` (Int), `applicable` (Check) |
| `IB WO Output` | `item_code` (Link Item), `item_name`, `planned_qty` (Float), `produced_qty` (Float), `uom`, `width_mm`, `length_mtr`, `gsm`, `fg_batch` (Link IB Batch, ro), `serial_count` (Int, ro) |
| `IB WO Stage Event` | `stage`, `machine` (Link IB Machine), `operator` (Link User), `started_at` (Datetime), `completed_at` (Datetime), `output_qty` (Float), `wastage_qty` (Float), `notes` (Small Text) |

### Multi-item = multi-OUTPUT, single input

The "a WO can have multiple items" case is **one jumbo → several output SKUs** produced together (e.g. slit one 1315 mm roll into 300/500/515 mm). That is 3 `outputs` rows on ONE Work Order — not 3 Work Orders. The normal single-SKU run is a WO with one `outputs` row.

---

## How it works

### 1. Create
- `IB Order Sheet` (from a Sales Order) still lists the ordered items.
- "Start Production" from an Order Sheet / SO opens **one dialog per run**:
  - pick the **source RM batch** (Link IB Batch, kind=Raw Material, filtered to the input item)
  - the **route** is pre-filled from the item group (editable — check/uncheck stages, reorder)
  - one or more **output** rows (default: the Order Sheet items being produced from this batch), each with planned qty + packing details (Brand/Core/CTN/Shrink Film/Packing Type — per output, since different SKUs differ)
  - pick the **starting stage** (default: first route stage)
- Creates ONE `IB Work Order`, `current_stage` = the starting stage, status → In Progress, machine auto-assigned for that stage.

### 2. Advance (one stage at a time — NO modal on continue)
- The WO row / side panel shows the current stage + a single **"Advance to <next>"** button.
- Click → prompt for **actual output qty** (wastage = planned − actual for that stage) → append an `IB WO Stage Event` row (stage, machine, operator, timestamps, output, wastage) → `current_stage` moves to the next route stage, machine freed + re-assigned for the new stage.
- Skipping a stage = move `current_stage` forward past it (a Stage Event row is still written with a "skipped" note).
- **Completing a stage never opens the stage picker.** The route is fixed on the WO; "next" is deterministic.

### 3. Final stage → serials + ledger
When `current_stage` reaches the last route stage and it's completed:
- Create **FG `IB Batch`** (kind=Finished Good, `parent_batches=[source_batch]`, `work_order`).
- Per `outputs` row: generate N `IB FG Serial` (N = the output's packing count) stamped with the full genealogy; write `produced_qty` / `serial_count` / `fg_batch` back on the row.
- Post **ONE Stock Entry** (`stock_entry_type = "Repack"`), linked as `IB Work Order.stock_entry`:
  - **Consume:** `source_batch` item, qty = planned input qty (or Σ output planned + total wastage), from `source_warehouse`.
  - **Produce:** each `outputs` row's `item_code` + `produced_qty` into the FG warehouse.
  - The difference (input − Σ produced) is the run's total wastage — ERPNext's Repack nets it out; valuation flows from RM cost across the outputs.
- `status` → Completed, `current_stage` → "Done".
- Non-blocking on serial-gen failure (log + warn); the Repack failing DOES block completion (ledger integrity — user's call: "everything in the ledger").

### 4. Cancel
- WO cancel → cancel the linked Repack Stock Entry (reverses RM/FG ledger), delete the run's IB FG Serials + FG IB Batch, clear `source_batch` links elsewhere.

### 5. Ship
- `Sales Order → Delivery Note` as today. If the SO line was produced (an IB FG Serial exists for it), the trace is via the serial. If not (direct B2B), `link_dn_source_batches` (already shipped) FIFO-links the DN line to the RM batch.
- Native FIFO batch auto-pick on the DN Stock Entry unchanged.

---

## Ledger — every in/out

| Event | Stock Entry | Effect |
|---|---|---|
| Container Import submit | Material Receipt | RM **in** *(today)* |
| Purchase Receipt submit | native GRN | RM **in** *(today)* |
| **WO final stage complete** | **Repack** — consume `source_batch` qty, produce `outputs` qty | RM **out** / FG **in**, wastage netted, valuation flows *(new)* |
| Delivery Note submit | Material Issue | FG **out** *(today)* |
| Any of the above cancelled | reversal | *(today, + the Repack reversal is new)* |

No more "annotation only" — `IB Batch` / `IB FG Serial` stay as the genealogy layer, but real stock now moves through production.

---

## Traceability (mostly already built)

One WO = one run = one trace unit. `ib-trace` resolves a Serial / IB Batch / **Work Order** / **Delivery Note** / Container:

```
supplier lot ← Container/GRN ← RM IB Batch ← IB Work Order (run)
                                              ├→ outputs → FG IB Batch → IB FG Serial → DN → Customer   (produced)
                                              └→ (direct sale) RM IB Batch → DN → Customer               (Path B, done)
```

`_trace_from_wo` is rewritten to read the new WO shape (route, current_stage, stage_log, outputs, serials). The rest of `traceability.py` already handles IB Batch / IB FG Serial / DN.

---

## Migration — fresh start

Production is in testing; wipe it. On the branch:
1. Delete all `IB Work Order` (old per-stage), `IB Order Sheet Item` production state, `IB FG Serial`, FG `IB Batch`, and any production-posted Stock Entries. Keep Sales Orders / Container Imports / RM `IB Batch`.
2. Deploy the new doctypes + code.
3. Re-run production on real open Sales Orders using the new flow.

No data-migration script — not worth writing one for a model being replaced.

---

## Phased build (own branch, `feature/wo-per-run`)

| Phase | Scope | Ship independently? |
|---|---|---|
| **1** | New `IB Work Order` + 3 child doctypes + Frappe workflow. `create_order_sheet` / "Start Production" build one WO per run. `start_run` / `advance_run` / `complete_run` in `production.py`. Order-wise tab + WO side panel rebuilt. Old production data wiped. | No — the core |
| **2** | Serials per output at final stage + `IB Serial Label` per output. | After P1 |
| **3** | Repack Stock Entry at final stage (ledger) + cancel reversal. Behind `site_config` flag `ib_production_posts_stock` until validated. | After P1 |
| **4** | ~~DN → RM batch link (direct-B2B trace)~~ **DONE — `8383b54`** | ✅ shipped |
| **5** | Rebuild Item-wise / Stage-wise / Machine-wise / DPR / Production Dashboard KPI cards / Analytics-Hub production tab on the new shape. | After P1 |
| **6** | `IB Job Order` / `IB Job Order Summary` print formats re-pointed at the run + its outputs. | After P1 |

**Estimated effort:** 1–2 focused weeks. Not a conversation-turn change.

---

## Open questions for the user before Phase 1

1. **Route master vs item-group map** — keep the hardcoded item-group → stage route (`_ITEM_GROUP_STAGE_ROUTES`), or make a `Routing` master (per item / per item group) that the run copies from? (Recommend: keep the item-group map, make the copied `route` child editable per run.)
2. **Repack qty basis** — is the input qty on the WO known up front (you load a specific jumbo of known length), or only "planned output + wastage"? Drives whether `source_qty` is a field or derived.
3. **One run per Order Sheet, or per source batch, or user-grouped?** — if an Order Sheet has 6 items all cut from one jumbo → 1 WO with 6 outputs. If from 3 different jumbos → 3 WOs. Who decides the grouping — auto (by source batch) or the operator at Start?
4. **Wastage valuation** — write the wastage value off to a scrap/COGS account, or just let it vanish into the Repack's per-unit FG valuation? (Recommend the latter for simplicity; a scrap account is a later refinement.)
