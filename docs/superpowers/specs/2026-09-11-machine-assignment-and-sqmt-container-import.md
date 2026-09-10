# Machine Assignment for Dimension-Driven Orders + SQMT Container Import

**Date:** 2026-09-11
**Status:** Engineering plan for review. Companion to `2026-09-10-production-rebuild-implementation-plan.md`
(the run model) and `2026-09-10-production-work-order-per-run-rebuild.md`.
**Branch:** all work on `feature/wo-per-run`, pushed to prod later. **Do not touch `develop`.**
**Fills two gaps the run-rebuild plan left open:** (a) how machines actually get chosen when an order
has many line items at different finished dimensions, and (b) container-import intake for SQMT-UOM items
(L / W / area entry — the PCS path already works).

---

## PART 0 — Current state (verified from code + dev DB, 2026-09-11)

### Machines (dev DB — 8 real, all Gujarat, no floor set)
| code | type | capacity | notes |
|---|---|---|---|
| CM-01 | Coating | 1111 rolls/hr | **only coater** — no choice at Coating |
| SM-01 | Slitting | 3800 rolls/hr | **only slitter** — no choice at Slitting |
| RW-01 | Rewinding | 6300 rolls/hr | **only rewinder** |
| CT-01 | Cutting | 3000 rolls/hr | one of **two** cutters — real choice |
| CT-02 | Cutting | 7100 rolls/hr | |
| PK-01 | Packing | 80000 ctn/shift | one of **two** packers |
| PK-02 | Packing | 4000 ctn/shift | |
| DS-01 | Despatch | 500 ctn/shift | not a production machine (Despatch type, unused by routing) |

So **today the only stages with a genuine assignment decision are Cutting and Packing.**
The design must still scale to N machines per stage (a second slitter/coater is plausible).

### `_assign_machine_load_balanced(stage, location)` today (`production.py:102`)
Picks the least-loaded active machine of `_STAGE_MACHINE_TYPE[stage]` at the location, floor-filtered,
capacity-skipped. **Zero awareness of the job's dimensions** — width, GSM, knife count, roll diameter,
cut length are never consulted. A job that physically cannot run on a machine can still be assigned to it
(this is how DS-01 ended up with mis-typed jobs, CLAUDE.md item 123).

### `IB Machine` fields today
`machine_code, machine_name, machine_type, location, floor, capacity, capacity_uom, wastage_norm_pct,
status, notes, linked_asset`. **No physical-capability fields.** (The `machine_width_mm` / `knife_positions`
from the 2026-07-15 seat-map experiment were reverted — not on `develop`.)

### `IB WO Output` (already on `feature/wo-per-run`)
Already carries `item_code, planned_qty, produced_qty, uom, width_mm, length_mtr, gsm, pack_count,
brand, core, ctn, shrink_film, packing_type, sales_order_item`. **The finished dimensions are already
in the run model** — the assignment layer just has to read them.

### `IB Order Sheet Item`
`item_code, qty, uom, completed_qty, status, sales_order_item`. **No dimension fields** — finished
W/L must be read through `sales_order_item` → `Sales Order Item` (custom `width_mm` / `length_mtr`),
or the `Item` master as fallback.

### `IB Container Import Item`
`item_code, item_name, stock_uom, no_of_boxes, qty_per_box, total_qty, rate, barcode, batch_no`.
`validate()`: `total_qty = no_of_boxes × qty_per_box` — **one formula, every UOM.**
Dev item mix: **423 SQMT**, 88 PCS, 19 KG, 5 Nos, 1 ROLL. SQMT is the norm; 430/536 items have `width_mm` set, 0 have `gsm`.

---

## PART 1 — Machine assignment for dimension-driven orders

### 1.1 What physically decides the machine, per stage

| stage | hard constraints | the "setup" that costs a changeover |
|---|---|---|
| **Coating** | jumbo width ≤ coat width; GSM in machine range; adhesive type | jumbo width + GSM + adhesive |
| **Slitting** | jumbo width ≤ max input width; every output width ≥ min slit width; `Σ output widths ≤ jumbo width − trim`; output count ≤ knife positions; output Ø ≤ max diameter | the sorted set of output widths + core Ø |
| **Rewinding** | roll width ≤ max width; Ø ≤ max diameter; core Ø | width + core |
| **Cutting** | roll width ≤ max cut width; finished length in [min, max]; lane count ≤ blade positions | roll width + finished length + core |
| **Packing** | — (box size rarely a blocker) | box type (minor) |

**The dimension-critical stages are Slitting and Cutting.** Coating is width+GSM-gated but there is one
coater. Everything downstream inherits the widths that Slitting produced.

### 1.2 The two order shapes you described

**Shape A — one `item_code`, N lines, different finished dims.**
(Real: `IB-SGM-SO-00480`, one PVC tape item on 5 lines at different W×L, CLAUDE.md item 147.)
These are **N distinct finished outputs**. The question is *how they map onto slitting passes*:
- If the source jumbo is wide enough and the slitter has enough knives, several of the N widths are
  **co-slit in one pass** → **one run, several `outputs` rows, one slitter setup**.
- Widths that don't co-fit (`Σ + trim > jumbo`) or blow the knife count → **another pass / another run**.
- After slitting, each output roll goes to **Cutting independently** (different finished lengths) and
  fans out across CT-01 / CT-02 by feasibility + load.

**Shape B — different `item_code`, same finished dims.**
(Red 300 mm + blue 300 mm, both 50 m.) Different adhesive/colour ⇒ probably different coating runs,
but at **Slitting and Cutting their setup signature is identical** (300 mm, same knife layout, same
length). They should be **assigned to the same machine and sequenced back-to-back** so the knives are
set once for both.

### 1.3 The unifying model — feasibility → changeover → load (lexicographic)

Define a **setup signature** per (stage, job):

```
_sig(stage, spec):
  Coating   -> (round(spec.input_width), round(spec.gsm), spec.adhesive_type)
  Slitting  -> (tuple(sorted(round(w) for w in spec.output_widths)), spec.core_id)
  Rewinding -> (round(max(spec.output_widths)), spec.core_id)
  Cutting   -> (round(max(spec.output_widths)), round(spec.output_length), spec.core_id)
  Packing   -> (spec.box_type,)
```

Machine assignment picks the machine that is, in order:

1. **feasible** — every hard constraint in 1.1 satisfied (unset machine field = no constraint), else
   **hard error** ("no machine can run width 1600 mm — widest is SM-01 at 1500 mm"). No silent
   load-balanced fallback — an infeasible assignment is a data/planning error the operator must see.
2. **lowest changeover** — `0` if the machine's `current_setup_sig` already equals `_sig(stage, spec)`,
   else a flat `CHANGEOVER_PENALTY` (minutes; used only to rank).
3. **lowest load** — queued minutes = `Σ (planned_qty / speed_m_per_min)` over the machine's
   In-Progress + queued runs (falls back to WO count if `speed` unset — today's behaviour).

This one rule covers **both** shapes: Shape A's co-fitting widths collapse into one run whose signature
routes to whatever machine already runs it; Shape B's identical signatures land on the same machine and
batch. Ties break on `machine_code` (stable).

### 1.4 New `IB Machine` fields — "Physical Capability" section

| field | type | used by |
|---|---|---|
| `max_input_width_mm` | Float | Coating, Slitting, Rewinding |
| `max_output_width_mm` | Float | Cutting, Rewinding |
| `min_slit_width_mm` | Float | Slitting, Cutting |
| `knife_positions` | Int | Slitting, Cutting (lanes) |
| `max_roll_diameter_mm` | Float | Slitting, Rewinding, Cutting |
| `min_length_m` / `max_length_m` | Float | Cutting |
| `gsm_min` / `gsm_max` | Float | Coating |
| `speed_m_per_min` | Float | all — time-based load |
| `current_setup_sig` | Data (read-only) | all — last Stage Event's `_sig`, for changeover ranking; written on each `advance_run` |

**Every field blank ⇒ behaves exactly like today** (load-balanced only). Backward compatible by
construction — nothing breaks before the shop-floor numbers are entered.

### 1.5 `_machine_feasible(machine, stage, spec) -> bool`

```
spec = { input_width_mm, output_widths_mm: [...], output_diameter_mm,
         output_length_m, gsm, core_id, adhesive_type, box_type }

Coating:   input_width ≤ max_input_width           (if set)
           gsm_min ≤ gsm ≤ gsm_max                 (if set and gsm known)
Slitting:  input_width ≤ max_input_width
           len(output_widths) ≤ knife_positions
           min(output_widths) ≥ min_slit_width
           sum(output_widths) ≤ input_width − TRIM_MM
           output_diameter ≤ max_roll_diameter
Rewinding: max(output_widths) ≤ max_input_width  AND  output_diameter ≤ max_roll_diameter
Cutting:   max(output_widths) ≤ max_output_width
           min_length ≤ output_length ≤ max_length
           len(output_widths) ≤ knife_positions
Packing:   True
Any unset machine constraint ⇒ that check passes.
```

### 1.6 `_assign_machine(stage, location, spec) -> machine_name`

```
1. candidates = active IB Machine of _STAGE_MACHINE_TYPE[stage] at `location`
                (fall back to any location), floor-filtered  ← existing rule kept
2. feasible = [m for m in candidates if _machine_feasible(m, stage, spec)]
   if not feasible: frappe.throw(clear message naming the binding constraint)
3. want = _sig(stage, spec)
   score(m) = (0 if m.current_setup_sig == want else CHANGEOVER_PENALTY,
               queued_minutes(m))
4. return min(feasible, key=score)   # tie -> machine_code
```

Replaces `_assign_machine_load_balanced` at every call site (`create_run`, `advance_run`,
`reassign machine` action). Old name kept as a thin alias that calls the new fn with `spec=None`
(→ feasibility all-pass → pure load balance) so any missed caller still works.

### 1.7 Building `spec` — it falls out of the run's `outputs`

`IB WO Output` already has `width_mm / length_mtr / gsm / core`. So:

```
_spec_from_outputs(wo_doc, stage):
    outs = wo_doc.outputs
    return {
      "input_width_mm":   flt(wo_doc.source_batch_width) or max(o.width_mm for o in outs),
      "output_widths_mm": [flt(o.width_mm) for o in outs if o.width_mm],
      "output_length_m":  max(flt(o.length_mtr) for o in outs) or None,
      "output_diameter_mm": flt(wo_doc.get("roll_diameter_mm")) or None,
      "gsm":  flt(outs[0].gsm) or None,
      "core_id": outs[0].core,
      "adhesive_type": frappe.db.get_value("Item", wo_doc.source_item, "custom_adhesive_type"),
      "box_type": outs[0].packing_type,
    }
```

`source_batch_width` = the RM `IB Batch`'s real width (see Part 2.5 — container import writes it).
**Nothing new is asked of the operator for assignment** — the Start dialog already collects the outputs.

**One gap to close (step S6):** populate `IB WO Output.width_mm / length_mtr / gsm` at run creation
from `Sales Order Item` (via `sales_order_item`), Item master as fallback. Order Sheet Item has no dims.

### 1.8 Run grouping for Shape A — `_propose_runs` (bin-packing)

In the Start Production dialog, after the operator picks the source jumbo batch(es):

```
_propose_runs(order_sheet, picked_batches) -> [proposal, ...]
  for each picked jumbo batch b:
    lines = OrderSheet lines whose finished item's RM == b.item, not yet in a run
    lines.sort(key=width desc)
    passes = []
    for ln in lines:
        placed = False
        for p in passes:
            if (sum(p.widths) + ln.width ≤ b.width − TRIM_MM
                and len(p.lines) + 1 ≤ slitter.knife_positions):
                p.add(ln); placed = True; break
        if not placed: passes.append(new pass with ln)
    for p in passes: yield proposal(run with p.lines as outputs, source_batch=b)
  # operator can merge / split / assign a different jumbo before confirming
```

Example — SO-00480, jumbo A = 1680 mm usable, SM-01 = 6 knives:
`{600, 450, 300, 300}` (Σ 1650 ≤ 1680, 4 ≤ 6) = run 1; `{1000}` from jumbo B = run 2.
Two runs, each co-slit in one pass; then Cutting fans them across CT-01/CT-02 by length + load.

Even with one slitter this matters — it decides how many **passes** SM-01 makes and seeds the
Cutting-stage batching.

### 1.9 Batching for Shape B — `get_setup_batches` (the reborn Job Bundles)

```
get_setup_batches(stage, location):
  runs = runs whose current_stage == stage, at `location`
  groups = group runs by _sig(stage, _spec_from_outputs(run, stage))
  return [ {sig, machine: pick feasible machine already at sig else least-loaded,
            runs: [...], est_total_minutes}
           for g in groups if len(g) ≥ 2 ]
```

Surfaced on the **Machine-wise tab** as a "set the knives once — run these N" card, with a
"assign all + sequence" button (uses the existing per-run reassign path, no new write model).

### 1.10 What this is NOT

- Not a scheduler/optimiser. No Gantt, no due-date solving. It's a **deterministic picker**
  (feasible → least changeover → least load) run at each stage transition, plus a batch *suggestion*.
- Not automatic re-grouping mid-run. `_propose_runs` runs once, at Start; the operator owns the result.
- No WIP-warehouse / shop-floor stock moves (that's the run-rebuild plan's deferred D5).

---

## PART 2 — SQMT container import

### 2.1 The SQMT logic (identical shape to Sales Order Item)

CLAUDE.md dimension rule: `SQMT qty = (width_mm / 1000) × length_mtr × qty_pkg × total_pkg`.

Container-import equivalent — a container holds **N units (rolls)**, each **W mm × L m**:

```
area_per_unit = (roll_width_mm / 1000) × roll_length_m         # m² per roll
total_qty     = no_of_boxes × area_per_unit                    # m² into stock, UOM = SQMT
```

PCS / KG / Nos path unchanged: `total_qty = no_of_boxes × qty_per_box`.

### 2.2 New fields on `IB Container Import Item`

| field | type | notes |
|---|---|---|
| `roll_width_mm` | Float | `depends_on: eval:doc.stock_uom=="SQMT"`; default from `Item.width_mm` |
| `roll_length_m` | Float | `depends_on: eval:doc.stock_uom=="SQMT"` |
| `roll_gsm` | Float | optional; feeds the RM batch + downstream Coating feasibility |
| `area_per_unit` | Float, read-only | label "m² per roll"; `= roll_width_mm/1000 × roll_length_m` |
| `no_of_boxes` | Int | UI label switches to **"No. of Rolls"** when SQMT; still the unit count |
| `qty_per_box` | Float | hidden when SQMT |
| `total_qty` | Float, read-only | branched in `validate()` |

### 2.3 `validate()` / `before_submit()` change

```python
def validate(self):
    for row in self.items:
        if (row.stock_uom or "").upper() == "SQMT":
            row.area_per_unit = flt(row.roll_width_mm) / 1000 * flt(row.roll_length_m)
            row.total_qty = flt(row.no_of_boxes) * flt(row.area_per_unit)
        else:
            row.total_qty = flt(row.no_of_boxes) * flt(row.qty_per_box)
        row.barcode = _resolve_barcode(row.item_code)

def before_submit(self):
    for row in self.items:
        if cint(row.no_of_boxes) <= 0:
            frappe.throw(_("Row #{0}: No. of Rolls/Boxes must be > 0").format(row.idx))
        if (row.stock_uom or "").upper() == "SQMT":
            if flt(row.roll_width_mm) <= 0 or flt(row.roll_length_m) <= 0:
                frappe.throw(_("Row #{0}: Roll Width and Roll Length required for SQMT items").format(row.idx))
        elif flt(row.qty_per_box) <= 0:
            frappe.throw(_("Row #{0}: Qty per Box must be > 0").format(row.idx))
        if not row.barcode:
            frappe.throw(_("Row #{0}: barcode could not be resolved").format(row.idx))
```

### 2.4 Stock Entry — already correct once `total_qty` is right
`_make_stock_entry` posts `row.total_qty` in `row.stock_uom`. No change needed.

### 2.5 `IB Batch` — carry the real roll dims (feeds Part 1 feasibility)
`_make_batch` currently copies `Item.width_mm / gsm`. Change: for SQMT rows write the **row's**
`roll_width_mm / roll_length_m / roll_gsm` onto the batch (the actual imported jumbo can differ from
the Item master). Add `length_mtr` to `IB Batch` if absent. `_spec_from_outputs` reads
`source_batch.width_mm` as `input_width_mm`.

### 2.6 UI (`ib_container_import.js`)
- On `stock_uom` set/change per row: toggle field visibility (SQMT → show width / length / area,
  hide `qty_per_box`; relabel `no_of_boxes` → "No. of Rolls").
- Live-recompute `area_per_unit` and `total_qty` on `roll_width_mm` / `roll_length_m` / `no_of_boxes`
  change — mirror the debounced recalc in `recalc.js`.
- The pre-submit confirmation dialog (item 149) already lists per-UOM totals; extend its line to
  `"<item>: N rolls × Wmm × Lm = X.XX m²"`.

---

## PART 3 — Build order (branch `feature/wo-per-run`)

| step | deliverable | depends on | ship alone? |
|---|---|---|---|
| **S1** | SQMT container import (Part 2) — fields, `validate` branch, `_make_batch` dims, JS toggle | nothing | **yes — do first** |
| **S2** | `IB Machine` capability fields + `IB Batch.length_mtr` + form "Physical Capability" section | nothing | yes |
| **S3** | `_machine_feasible` + `_assign_machine(stage, location, spec)` + `_spec_from_outputs`; swap call sites; old name → alias | S2, WO-per-run Phase 1 (`IB WO Output`) | with P1 |
| **S4** | `_propose_runs` bin-packing wired into the Start Production dialog (Shape A) | S3 | with P1 |
| **S5** | `get_setup_batches` + Machine-wise "set up once, run N" card (Shape B) | S3 | after P1 |
| **S6** | populate `IB WO Output.width_mm/length_mtr/gsm` from Sales Order Item at run creation | WO-per-run Phase 1 | with P1 |
| **S7** | shop-floor data entry: capability numbers on CM-01 … PK-02 | S2 + real numbers | — |

**S1 and S2 are independent and safe to build now.** S3–S6 sit on top of the WO-per-run Phase 1
already in flight. Nothing here touches `develop`; everything lands on the branch and goes to prod
with the rest of the rebuild.

---

## PART 4 — Needed FROM YOU (real shop-floor numbers)

1. **Per machine** (CM-01, SM-01, RW-01, CT-01, CT-02, PK-01, PK-02): max input width, max output
   width, min slit/cut width, knife/blade positions, max roll diameter, cut-length min/max, line
   speed (m/min). DS-01 = despatch, skip.
2. **Slitter edge-trim allowance** (`TRIM_MM`) — mm lost per jumbo edge.
3. **Changeover penalty** — rough minutes to re-set knives for a new width layout (ranking only,
   not exact).
4. Confirm one `item_code` really does appear on multiple SO lines with different `width_mm` /
   `length_mtr` (item 147 says yes — confirming it's not always encoded in the code).
5. SQMT container imports: always "**N rolls, each W × L**", or do some arrive as "**N boxes ×
   M rolls each × W × L**" (three-level)? Changes the formula depth.
6. Adhesive type: is there an `Item.custom_adhesive_type` (or similar) to key Coating changeover on?
   If not, Coating changeover keys on width + GSM only.
