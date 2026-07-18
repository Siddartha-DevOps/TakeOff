# Trade assemblies (`estimating/assemblies.py`)

Togal-style **conditions/assemblies**: one *measured* quantity expands into the
many material/labor line items a trade needs. Complements `boq.py` (India
DSR/SOR) as the generic estimating layer, and complements `models.Condition`
(which is a single priced line) with the *bundle*.

## Model
- **`Assembly`** — `key`, `name`, `trade`, `driver_unit` (`sf|lf|ea`), `components`.
- **`AssemblyComponent`** — `item`, `unit`, `factor` (output qty per 1 driver
  unit), `waste_pct`, optional per-component `trade`.

Component quantity = `measured_qty × factor × (1 + waste_pct/100)`. Unit costs are
injected via a **cost book** (`{item: cost}` or `{"assembly:item": cost}`), so
factors stay separate from prices.

## Seed library
`interior_partition` (LF), `paint_finish` (SF), `resilient_flooring` (SF),
`interior_door` (EA), `acoustic_ceiling` (SF), `slab_on_grade_4in` (SF). Factors
are editable US-customary defaults — tune per project/region.

## API
- `GET /api/estimating/assemblies` — list the library.
- `POST /api/estimating/assemblies/expand` — body
  `{measured: [{assembly, quantity}], cost_book: {item: cost}}` →
  `{line_items, by_trade, total, skipped}`.

## Example
```python
from estimating.assemblies import expand_takeoff
expand_takeoff(
    [{"assembly": "interior_partition", "quantity": 240},   # 240 LF wall
     {"assembly": "resilient_flooring", "quantity": 1800},  # 1800 SF floor
     {"assembly": "interior_door", "quantity": 14}],
    cost_book={"Gypsum board 5/8\"": 0.55, "Flooring material": 3.50, "Door slab": 180},
)
# -> priced line items rolled up by trade + grand total
```

## Next
Wire measured takeoff quantities → assembly keys automatically (rooms→flooring,
walls→partition, door count→interior_door), and add a cost-book editor + a
frontend assemblies panel.
