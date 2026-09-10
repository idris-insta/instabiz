# Production Module — Clean Rebuild: Implementation Plan

**Date:** 2026-09-10
**Status:** Plan for review. Companion to `2026-09-10-production-work-order-per-run-rebuild.md` (the model) — this doc is the *how*.
**Branch:** `feature/wo-per-run` (do not touch `develop` production code until Phase 1 is merged)
**Scope (user decision 2026-09-10):** rebuild the **running logic + the `IB Work Order` doctype**. **Keep the Production Dashboard UI** — same page, same tabs, same look; the JS is adapted to the new data shape, not rewritten, plus a handful of targeted UX fixes (see PART F). No layout or visual redesign.

---

## PART A — What is wrong with the module today

Every point below is a real, observed defect (CLAUDE.md items 84 / 96 / 117 / 119 / 120 / 123–135 / 147, and this session). They are symptoms of **one** root cause.

### A1. The data model is the bug
The atomic unit is **(item × stage)** — one `IB Work Order` per item per stage. A 5-stage item = 5 Work Orders. Consequences:
- **No "run" object.** "Show me production run #123" is impossible — a run is scattered across 5 rows joined by fragile `item_code` / `order_sheet_item` string matches.
- **Cross-contamination.** `get_production_plan` / Order-wise matched WOs to items by `item_code` alone → when one Sales Order carries the same item on 2+ lines, all lines showed the same merged Work Orders. Fixed **three separate times** (119, 134, this session) and the class of bug keeps coming back because the join is inherently ambiguous.
- **Future-stage WOs look actionable.** `auto_create_all_stage_wos` (old model) pre-created a `Pending` WO for every route stage. Stage-wise and Job Bundles then listed an item at *every* stage it hadn't reached yet, not just its current one (129, 130). The JIT switch (2026-08-13) helped but the mental model is still "a WO per stage."

### A2. Qty and wastage are unmeasurable
- `IB Production Entry` (the doctype meant to record per-stage real output) has **zero rows, ever**. ~180 lines of DPR / stage-breakdown / wastage code sit dead below `if not entries:` returns (120, 124, 134).
- `IB Work Order.completed_qty` is set to the item's **full `target_qty`** the moment *any single stage* completes — so progress reads **100% after stage 1 of N**. Bug fixed in 119, 123, 134; the field is structurally wrong.
- `IB Work Order.wastage_qty` / `wastage_pct` are hardcoded `0.0` at creation and never written by any real completion path. "0% wastage" is not measured — it's a default. (124's own code comment admits this.)
- Result: DPR, machine yield, Analytics-Hub production tab all report numbers that are either fabricated or blank.

### A3. The workflow fights the code
- `apply_workflow(doc, action)` internally calls `doc.load_from_db()` before its own save — **silently discarding** any `completed_at` / `completed_qty` / `wastage_qty` set on the in-memory doc. Every transition function has to re-`db.set_value` the fields *after* `apply_workflow`. Confirmed to have left real completed WOs with `completed_qty=0` / `completed_at=NULL` for weeks after the 2026-07-30 workflow migration (119, 120, 123, 148).
- Historically, status was changed with `frappe.db.set_value` which **bypasses Document events entirely** — RTD bell notifications and n8n webhooks never fired from any real completion path for the life of the feature (item 84).
- "Completed" is a terminal workflow state with no transition back. Reworking a finished stage (quality reject → back to Packing) left the earlier stage's pre-created WO stuck `Completed` forever, and the all-done check then wrongly flipped the whole Order Sheet to Completed (120).

### A4. Nothing posts to the stock ledger
- Container Import posts RM **in**. Delivery Note posts FG **out**. **Production consumes and produces nothing.** Stock quantity and valuation are wrong at every point between receipt and dispatch. There is no record that 300 KG of RM became 280 KG of FG with 20 KG lost.
- `source_batch` (which RM batch a run consumed) was **never set in the normal flow** — there was no picker in the Start Production dialog, only a dormant manual action on the WO side panel. Genealogy was broken in practice.

### A5. The UI teaches the wrong model
- The Start Production dialog's stage checkboxes read as "start all of these now" — bulk-start created a WO for every checked stage simultaneously (this session's complaint). The stage list is a **route** (the plan), not a launch checklist.
- Completing a stage re-opens the full stage-picker modal to continue — a modal for what should be a one-click "advance."
- `next_stage_suggestion` keeps offering a *skipped earlier* stage after the final stage is done, so "Start Production" shows on a finished order (this session).
- Order Sheet and Work Order both render as ID-looking things; users couldn't tell which was which (117).

### A6. Accreted dead weight
Seat Map / Live Floor backend (96, 114), `get_dpr`'s Production-Entry path (124), `batch_assign_machine` (139), `get_cutting_slot_map` and friends — all dead, all still in `production.py`.

### Root cause, one sentence
**The module models stages instead of runs, records nothing real about quantity, and never touches the ledger — so every feature on top of it has to reconstruct reality from fragile joins and defaulted zeros.**

---

## PART B — The target

### B1. One `IB Work Order` = one production run

```
IB Work Order  ── the run, cradle to grave
──────────────────────────────────────────
identity     : sales_order (Link), order_sheet (Link), priority, location (fetch),
               posting_date, owner, workflow_state
input        : source_batch (Link → IB Batch, kind=Raw Material)   ← the ONE RM batch
               source_item  (fetch from source_batch.item)
               source_qty   (Float)   ← RM consumed by this run (see decision D2)
               source_warehouse (Link → Warehouse, fetch from the container/GRN)
route        : route []  (child IB WO Route Stage)  ← the plan: ordered stages
               current_stage (Data)   ← active stage, or "Done"
               machine (Link → IB Machine)  ← machine at current_stage
outputs      : outputs []  (child IB WO Output)  ← 1+ finished SKUs from this run
history      : stage_log []  (child IB WO Stage Event)  ← one row per stage transition
result       : fg_batch (Link → IB Batch, kind=Finished Good, ro)
               stock_entry (Link → Stock Entry, ro)   ← the Repack
               total_output_qty  (Float, ro, Σ outputs.produced_qty)
               total_wastage_qty (Float, ro, Σ stage_log.wastage_qty)
               started_at, completed_at (Datetime, ro)
status       : Draft → In Progress → (On Hold ⇄ In Progress) → Completed / Cancelled
```

### B2. Child doctypes (all new)

**`IB WO Route Stage`** (istable) — the plan
| field | type | notes |
|---|---|---|
| `stage` | Select | Coating / Slitting / Rewinding / Cutting / Packing |
| `sequence` | Int | 1..N, defines order |
| `machine_type` | Data (ro) | for machine filtering at that stage |
| `done` | Check (ro) | set when that stage's Stage Event is written |

**`IB WO Output`** (istable) — the finished SKUs
| field | type | notes |
|---|---|---|
| `item_code` | Link → Item | the finished SKU |
| `item_name` | Data (fetch) | |
| `planned_qty` | Float | expected output |
| `produced_qty` | Float (ro) | actual, set at final stage |
| `uom` | Link → UOM | |
| `width_mm` / `length_mtr` / `gsm` | Float | dimensions, for the serial label |
| `brand` / `core` / `ctn` / `shrink_film` / `packing_type` | Link/Data | packing details — **per output** (different SKUs differ) |
| `pack_count` | Int | boxes/rolls → serial count |
| `fg_batch` | Link → IB Batch (ro) | |
| `serial_count` | Int (ro) | |

**`IB WO Stage Event`** (istable) — the run's real history
| field | type | notes |
|---|---|---|
| `stage` | Select | |
| `machine` | Link → IB Machine | |
| `operator` | Link → User | |
| `started_at` / `completed_at` | Datetime | |
| `input_qty` | Float | what went in |
| `output_qty` | Float | what came out (operator enters this — the ONE real number) |
| `wastage_qty` | Float (ro) | `input_qty − output_qty` |
| `wastage_pct` | Percent (ro) | |
| `skipped` | Check | true = stage bypassed, no work done |
| `notes` | Small Text | |

This table is the **only** place quantity/wastage is recorded, and it is real, per stage, entered by the person at the machine.

### B3. Multi-item is multi-OUTPUT

"A Work Order can contain multiple items" = **one RM batch → several finished SKUs, produced together**. Example: one 1315 mm jumbo → slit into 300 + 500 + 515 mm → 3 `outputs` rows on **one** Work Order. The everyday single-SKU run is a WO with one `outputs` row. There is never more than one *input* batch per WO (if a run needs two jumbos, that's two runs).

### B4. Route = template, not checklist

- Route is copied onto the WO at creation from the item group (`_ITEM_GROUP_STAGE_ROUTES`) — **editable per run** (add/remove/reorder stages, mark inapplicable).
- The WO advances through its own `route` one stage at a time.
- Warehouse-only locations (Maharashtra, Chennai) get a `["Packing"]` route (as today).

---

## PART C — Complete stock ledger map

Every movement. Nothing "annotation only."

| # | Trigger | Document posted | Stock effect | GL effect |
|---|---|---|---|---|
| 1 | Container Import submit | Stock Entry — **Material Receipt** | RM item **+qty** → import warehouse (`First Floor - GUJARAT - IB` etc) | Stock In Hand DR (value = row rate or 0) |
| 2 | Purchase Receipt submit | native GRN | RM item **+qty** → warehouse | Stock In Hand DR / Stock Received But Not Billed CR |
| 3 | Purchase Invoice submit | native PI | — | Creditors CR / SRBNB DR / Input GST DR |
| 4 | **WO final stage completed** | Stock Entry — **Repack**, linked as `IB Work Order.stock_entry` | RM item **−source_qty** from `source_warehouse`; each output SKU **+produced_qty** into the FG warehouse (same location warehouse for v1). `source_qty − Σ produced_qty` = run wastage (leaves stock, value absorbed). | RM valuation total (source_qty × valuation_rate) distributed across output rows → FG unit cost carries the wastage. Optional (D4): write wastage value to a Scrap/COGS account instead of absorbing. |
| 5 | Delivery Note submit | Stock Entry — **Delivery** (native) | FG item **−qty** from FG warehouse. Native FIFO batch pick unchanged. | Stock In Hand CR / COGS DR |
| 6 | Sales Invoice submit | native SI | — | Debtors DR / Sales CR / Output GST CR |
| 7 | Payment Entry | native PE | — | Bank/Cash DR / Debtors CR |
| 8 | **Any of the above cancelled** | ERPNext reversal SE + reverse GL | exact inverse | exact inverse |

**Direct B2B (imported → customer, no production):** rows 1 → 5 → 6 → 7 only. No WO, no Repack. The DN line is stamped with the RM `IB Batch` via `link_dn_source_batches` (**already shipped, `8383b54`**) for traceability.

**Repack mechanics (ERPNext):**
- `stock_entry_type = "Repack"`.
- Consume row: `s_warehouse` = RM warehouse, `item_code` = source item, `qty` = `source_qty`, `basic_rate` from item valuation (or `allow_zero_valuation_rate`).
- Produce rows: `t_warehouse` = FG warehouse, `item_code` = each output SKU, `qty` = `produced_qty`. Leave `basic_rate` blank → ERPNext auto-distributes the consumed value across produced rows proportionally by qty. Same item code for RM and one output is allowed.
- If `Σ produced_qty > source_qty` (impossible-yield) → block completion with a clear message (real data guard).

---

## PART D — Decisions the plan is built on (confirm or override)

| # | Decision | Recommended | Impact if changed |
|---|---|---|---|
| D1 | Route source | Keep `_ITEM_GROUP_STAGE_ROUTES` map, copy to editable `route` child at WO creation. A `Routing` master is a later refinement. | If Routing master: +1 doctype, route dialog gets a "load routing" step. |
| D2 | Is `source_qty` known up front? | **Yes** — the operator loads a specific jumbo of known length/weight, so `source_qty` is entered at Start. If unknown, derive `source_qty = Σ planned_qty` and true it up from stage_log at completion. | Changes the Start dialog and the Repack consume qty. |
| D3 | Run grouping | **Operator picks at Start.** Default: one WO per (Order Sheet, source batch) — pre-fills every Order Sheet item that shares that RM item as `outputs`. Operator can split/merge. | Auto-by-batch only = simpler, less flexible. |
| D4 | Wastage value | **Absorb into FG unit cost** (Repack auto-distribute). A Scrap/COGS write-off account is a Phase-3 refinement. | +1 account, +1 Repack row, per-run wastage visible in P&L. |
| D5 | WIP warehouse | **No.** RM and FG stay in the same location warehouse; Repack is in-place. Add per-location WIP warehouses later if shop-floor stock visibility is wanted. | +movement #4 (Material Transfer store→floor), +cancel handling. |
| D6 | Migration | **Fresh start.** Wipe all `IB Work Order` / `IB Order Sheet` production state / `IB FG Serial` / FG `IB Batch` / production Stock Entries. Keep SO / Container Import / RM `IB Batch`. | A migration script to fold old per-stage WOs into runs is possible but not worth it for a model being deleted. |

---

## PART E — Backend (`instabiz/overrides/production.py`, rewritten)

### E1. Route + creation

```
_get_route(item_code, location) -> list[dict]        # from _ITEM_GROUP_STAGE_ROUTES, seq-numbered
create_run(order_sheet, source_batch, source_qty, outputs, route, start_stage) -> wo_name
    # outputs: [{item_code, planned_qty, uom, dims, packing...}]
    # - validates source_batch exists, kind=Raw Material, has qty
    # - validates every output item's group route is compatible with `route`
    # - inserts one IB Work Order: route child, outputs child, current_stage=start_stage,
    #   status via apply_workflow(doc, "Start"), machine = _assign_machine(start_stage, location)
    # - writes started_at
    # - locks: GET_LOCK('IB-RUN-{order_sheet}-{source_batch}') to serialize concurrent Starts
```

`create_order_sheet(sales_order)` stays — builds the Order Sheet (unchanged shape: header + items). "Start Production" from the Order Sheet UI calls `create_run` with operator-picked grouping.

### E2. Advance / hold / complete

```
advance_run(work_order, output_qty, machine=None, operator=None, notes=None) -> {ok, next_stage}
    # the ONLY progress action. For current_stage:
    #   - append IB WO Stage Event: stage, machine, operator, started_at (from WO or now),
    #     completed_at=now, input_qty (= prev stage output_qty or source_qty), output_qty, wastage
    #   - mark route child.done
    #   - current_stage := next route stage; machine := _assign_machine(next, location)
    #   - if next is None -> _finish_run(doc)
    #   - one apply_workflow only if status needs to change; NEVER db.set_value for status
    # lock GET_LOCK('IB-WO-{name}')

skip_stage(work_order, reason) -> {ok, next_stage}
    # append Stage Event with skipped=1, output_qty = prev output_qty (pass-through), advance

hold_run(work_order, reason) / resume_run(work_order)     # apply_workflow Hold/Resume

_finish_run(doc):
    # 1. create FG IB Batch (kind=Finished Good, parent_batches=[source_batch], work_order)
    # 2. per outputs row: produced_qty := last Stage Event output_qty split by planned ratio
    #    (or operator-entered per-output at the final advance — see E3);
    #    generate pack_count IB FG Serial each, stamped with full genealogy;
    #    write produced_qty / serial_count / fg_batch back
    # 3. _post_repack(doc)   <-- the ledger movement, MUST succeed or completion is blocked
    # 4. apply_workflow(doc, "Complete"); current_stage := "Done"; completed_at := now
    # serial-gen failure: log + warn, do not block. Repack failure: block (ledger integrity).

_post_repack(doc):
    # Stock Entry, stock_entry_type="Repack"
    #   consume: source item, source_qty, s_warehouse=source_warehouse
    #   produce: each output item_code + produced_qty, t_warehouse=fg warehouse
    # link as doc.stock_entry ; if Σproduced > source_qty -> frappe.throw

reverse_run_stock(doc, method=None):   # IB Work Order on_cancel doc_event
    # cancel doc.stock_entry (reverses Repack), delete this run's IB FG Serial + FG IB Batch
```

### E3. Final-stage output per output row
At the last `advance_run`, if the run has >1 output, the dialog collects `output_qty` **per output row** (not one number). `_finish_run` uses those directly. Single-output runs: one number, goes straight through.

### E4. Read APIs (all rewritten to the run grain — no more item_code joins)

```
get_run_list(location, status, priority, search)         # Order-wise tab = list of runs
get_run_detail(work_order)                               # header + route + outputs + stage_log + serials
get_stage_board(location)                                # Stage-wise: runs grouped by current_stage (ONE per run)
get_machine_board(location)                              # Machine-wise: runs grouped by current machine, real yield from stage_log
get_dpr(date) / get_weekly_dpr()                         # from IB WO Stage Event (real per-stage output/wastage/hours)
get_production_kpis(location)                            # Dashboard cards: runs in progress / by stage / completed today / machines active
```

Every one of these reads the WO + its children directly. No reconstruction, no ambiguity.

### E5. Traceability (`traceability.py` — small changes)
`_trace_from_wo(name)` rewritten for the new shape: source_batch → source doc; route + current_stage + stage_log; outputs → fg_batch → serials → DNs → customers. The IB Batch / IB FG Serial / DN trace paths (already built) are unchanged.

### E6. Delete on sight
`auto_create_all_stage_wos`, `auto_create_first_stage_wos`, `start_item_stage`, `bulk_start_item_stages`, `move_work_order_stage`, `advance_to_next_stage`, `complete_work_order`, `get_order_sheet_detail`'s `order_wise_view`/`product_wise_view`, `get_stage_pipeline`, `get_job_bundles`, `get_cutting_slot_map` + friends, `get_live_floor_status` + friends, all `IB Production Entry` code, `_generate_fg_serials`'s old form.

---

## PART F — Frontend: KEEP THE UI, re-wire it + targeted UX fixes

**Scope decision (user, 2026-09-10): the running logic and the doctype get rebuilt; the Production Dashboard UI stays.** Same page, same tabs (Dashboard / Order-wise / Item-wise / Stage-wise / Machine-wise), same look, same `ib-production-dashboard` route. `ib_production_dashboard.js` is **adapted, not rebuilt** — only what's needed to read the new WO shape, plus the specific UX fixes the user already flagged. No mass rewrite, no design change.

### F1. What each tab keeps vs. changes

| Tab | Keep | Change (data-shape only) |
|---|---|---|
| **Dashboard** | KPI cards, Active Production Plan list, comment popover, filters (location/priority/search), infinite scroll | Cards + list read from the run grain (`get_run_list` / `get_production_kpis`). One row = one run (not one item×stage). Deep-links land at the **same grain** they count (fixes the WO-count → Order-Sheet-filter mismatch, item 119). Wastage % card now shows real numbers from `stage_log`. |
| **Order-wise** | Order-sheet list + drill-in detail, stage-chip row, progress bar, Print button, "Start All Items" | Detail rows read the run + its `outputs` / `route` / `stage_log`. Item↔WO match is by the run's own child rows — **no `item_code` join** (kills the recurring cross-contamination bug, items 119/134). WO side panel → **Run side panel** (see F3). |
| **Item-wise** | Per-item stage matrix (done/current/pending), jumbo-roll chain | Reads the run's `route` child (`.done` flags) + `stage_log`. A future route stage correctly shows "pending", not "actionable". |
| **Stage-wise** | Stage picker pills with live count badges, flat table, row → panel | Lists runs **currently at** that stage only (`current_stage` field — one row per run, never a future/past stage; fixes items 129/130). |
| **Machine-wise** | Machine cards, WO list per machine, OEE fields | Shows the run currently on each machine + today's real output/wastage/yield from `stage_log` (not the dead `IB Production Entry` path, items 120/124). |

### F2. Run side panel (the current WO side panel, re-pointed)
Same slide-in drawer, same visual language. Contents change to the run:
- Header: run id, SO/customer, **source batch**, route as chips (done = green, current = accent, pending = grey), `outputs` list with qty.
- **One** primary button — `Advance to <next stage>` → the existing actual-output prompt (`_prompt_actual_output`, per output row if multi-output) → posts. **No stage picker. No modal to continue.** (UX fix.)
- Dropdown (existing `⋯`): Hold / Resume, Skip Stage (reason), Print Job Order, Adjust output plan, Reassign machine.
- Final advance: inline "Run complete — FG batch X, N serials" + Print Serial Labels + Create Delivery Note.

### F3. Start Production dialog (rework the existing dialog — ONE dialog, first start only)
The current `_show_start_stage_dialog` / `_show_packing_details_dialog` / bulk dialog collapse into one:
1. **Source RM batch** (Link → IB Batch, kind=Raw Material, filtered to the input item) + **source qty** (D2).
2. **Route** — pre-filled from item group, shown as `Coating → Slitting → … → Packing`, editable (check/uncheck + reorder). **This is the plan, not a launch checklist** — checking stages does NOT start them (UX fix — the exact bug the user hit this session).
3. **Outputs** — grid pre-filled with the Order Sheet items sharing that RM (D3): item_code, planned qty, pack count, per-row "＋ packing" expander (Brand/Core/CTN/Shrink Film/Packing Type).
4. **Start at stage** — Select, default = first route stage.
→ `create_run(...)`. Shown **once per run**. Continuing = the one-click Advance, no dialog. (UX fix — item this session: "completing a stage prompts the stage selector modal".)

### F4. UX improvements to add (small, on the kept screens)
- Route chips on the Order-wise row + Run panel (see the plan at a glance).
- "Start Production" and "Start All Items" buttons **hide** once the run's last route stage is Completed → "Create Delivery Note" shows instead (this session's fix, re-applied on the run grain).
- Order-wise row click opens the Run panel (this session's ask).
- One-line "Coating done — Slitting is next" toast after each advance, no interruption.
- Real wastage / yield surfaced on the Machine-wise and DPR tabs (they show zeros today).

### F5. DPR page, Analytics-Hub production tab, Job Order / Job Order Summary print formats
Same pages/formats, re-pointed at the run + its `outputs` / `stage_log`. Phase 5/6.

---

## PART G — Migration (fresh start)

On the branch, one script (`instabiz/patches/wo_per_run_reset.py`, run once at go-live):
1. `frappe.db.sql` delete (in FK order): `IB FG Serial`, all `IB Batch` where `kind='Finished Good'`, `IB Work Order` + its old children, `IB Order Sheet` + `IB Order Sheet Item`.
2. Cancel + delete every submitted Stock Entry whose `remarks LIKE '%IB Work Order%'` or that is linked from a deleted WO (the old model never posted these, so likely a no-op — safety).
3. Keep: `Sales Order`, `IB Container Import`, `IB Batch` where `kind='Raw Material'`, `IB Machine`, `IB Production Floor`.
4. `bench migrate` the new doctypes.
5. Re-create Order Sheets + runs from real open Sales Orders using the new flow (manual, by the team — this is also the acceptance test).

No fold-old-WOs-into-runs script. The old model is deleted, not migrated.

---

## PART H — Test plan (each must pass live on disposable data, cleaned by exact name)

| # | Scenario | Assert |
|---|---|---|
| T1 | Create run: 1 RM batch → 1 output, full 5-stage route | 1 WO, route child = 5 rows, current_stage = Coating, status In Progress, machine assigned, started_at set |
| T2 | Advance through all 5 stages, output_qty 300→295→290→285→280 | 5 Stage Event rows with correct input/output/wastage each; current_stage moves 1 at a time; **no modal** between stages |
| T3 | Final advance | FG IB Batch created (parent = source batch); N IB FG Serial with full genealogy; **Repack Stock Entry** posted (RM −300 from source wh, FG +280 to FG wh); `stock_entry` linked; status Completed; current_stage "Done" |
| T4 | Stock ledger after T3 | SLE: RM item −300, FG item +280 at the right warehouses; GL balanced; item valuation_rate on FG reflects RM cost + absorbed wastage |
| T5 | Multi-output run: 1 jumbo → 3 widths | 1 WO, 3 outputs rows; final advance collects 3 output_qty; Repack has 1 consume + 3 produce rows; 3 FG batches, serials per output |
| T6 | Skip a stage | Stage Event with skipped=1, pass-through qty; route child.done set; advance continues |
| T7 | Hold → Resume | status transitions, machine freed on hold / re-assigned on resume; no data loss |
| T8 | Cancel a Completed run | Repack SE cancelled (ledger reversed), IB FG Serial + FG IB Batch deleted, source_batch links cleared |
| T9 | Warehouse-only location (Maharashtra) | route = [Packing] only; one advance completes the run |
| T10 | Same SKU on 2 SO lines, 2 runs | each run's outputs are its own; no cross-contamination in any view |
| T11 | DN from a produced SO line | trace via serial; DN line NOT re-stamped by link_dn_source_batches (production path) |
| T12 | DN direct (imported, no run) | link_dn_source_batches stamps RM batch (already passing — regression check) |
| T13 | Trace a run id / a serial / an FG batch / a DN | full chain both directions, one screen |
| T14 | DPR for a day with real runs | per-stage output/wastage/hours from Stage Events, not zeros |
| T15 | Impossible yield: output_qty > source_qty on final | completion blocked with a clear message; no Repack, no serials |

---

## PART I — Phased rollout

Branch `feature/wo-per-run`. Merge to `develop` only after Phase 1 + its tests pass.

| Phase | Deliverable | Gate to ship |
|---|---|---|
| **1** | New `IB Work Order` + 3 child doctypes + Frappe workflow (`IB Work Order Workflow` rebuilt). `create_run` / `advance_run` / `skip_stage` / `hold_run` / `_finish_run` (serials + FG batch, **no Repack yet**). `get_run_list` / `get_run_detail`. **Adapt** (not rebuild) the Dashboard + Order-wise tabs, the side panel → Run panel, and the Start dialog — same UI, new data shape, + the F4 UX fixes. Migration script. T1–T3 (minus ledger), T6–T10, T13. | T1–T3/T6–T10/T13 pass; team runs 3 real orders end to end on the branch site |
| **2** | Serial labels per output (`IB Serial Label` re-pointed). Scan a serial / run on `ib-stock-scan`. | T5 serial parts, label PDF renders |
| **3** | `_post_repack` + `reverse_run_stock` behind `site_config` flag `ib_production_posts_stock` (default off). Flip on after validation. T3 ledger parts, T4, T8, T15. | T4 GL balanced + valuation correct; T8 reverses cleanly; run on real Gujarat data for a week with the flag on |
| **4** | ~~DN → RM batch link (direct-B2B trace)~~ | ✅ **shipped `8383b54`** |
| **5** | **Adapt** Item-wise / Stage-wise / Machine-wise / DPR / Dashboard KPI cards / Analytics-Hub production tab to the run grain (same screens, real numbers). T14. | all tabs show real numbers, deep-links land at the right grain |
| **6** | `IB Job Order` / `IB Job Order Summary` print formats re-pointed at run + outputs. | prints one run, its outputs, its stage×machine grid |

**Effort (UI kept, not rebuilt):** Phase 1 ≈ 3–4 focused days. Phases 2–6 ≈ 4–5 days. Total ~1.5 weeks, one person, no interruptions.

**Not in scope:** any redesign of the Production Dashboard's layout, tabs, or visual language. `ib-ui-*` components may be used for the *new* small pieces (route chips, the Run panel's stage row) but the existing screens are left as they look today.

---

## PART J — Risks & mitigations

| Risk | Mitigation |
|---|---|
| Repack valuation surprises (same item RM=FG, zero-value RM) | `allow_zero_valuation_rate` fallback (already the pattern); T4 checks valuation explicitly; Phase 3 behind a flag, validated a week before default-on |
| Team confusion during the model switch | Fresh start + a 1-page "how production works now" (KB article), delivered with Phase 1. The new model is *simpler* (one WO = one run) so this is a net reduction in confusion |
| `apply_workflow` field-discard trap resurfaces | New code sets result fields with **one explicit `db.set_value` immediately after** each `apply_workflow`, and a helper `_wf(doc, action, then={})` that does both — single choke point |
| Concurrent Starts on the same Order Sheet + batch | `GET_LOCK('IB-RUN-{os}-{batch}')` in `create_run`; `GET_LOCK('IB-WO-{name}')` in every mutating function (existing pattern) |
| Existing `develop` production code keeps getting patched while the branch is open | Freeze: no production-code changes on `develop` except emergency fixes, which get cherry-picked to the branch |
| Migration deletes something real | Script keeps SO / Container / RM Batch / Machine / Floor; deletes only the model being replaced; dry-run count printed before any delete; run only at go-live with sign-off |

---

## PART K — What's already done (this session, on `develop`, safe)

- `IB Batch` (RM genealogy, from Container Import + Purchase Receipt) — `1c9272f` / `5e2fb85`
- `IB FG Serial` (annotation serials) — same
- `ib-trace` page + `traceability.py` (Serial / Batch / WO / **DN** / Container) — same + `8383b54`
- Barcode backfill + Item barcode field/image
- **Direct-B2B trace** (DN line → RM batch, FIFO) — `8383b54` ✅ (Phase 4 of this plan)
- Qty-adjustment note fix (UOM-agnostic) — `27a2d1d`
- `ib-ui-*` design system — `5e2fb85`
- "All Territories" hidden from pickers — `d136431`

The rebuild reuses all of it. `IB Batch` / `IB FG Serial` / `ib-trace` are the genealogy layer the new `IB Work Order` plugs into.
