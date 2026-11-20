# Validation strategy: one REMIND scenario

## Objective and boundaries

Implement the flodym-backed producer and its premise/TRAILS consumer route for
**SSP2-NPi2025 only**. Work on separate branches; retain existing pilot work and
the unrelated PyPSA experiment. Use the current local IAM files and already
curated observations. Do not contact providers or claim exact native vintages.

The scenario MIF is pinned by SHA-256 in the existing private evidence archive.
The campaign imports only each pilot's reference-year observed cohort state;
its old future projections are not inputs to the new reconstruction.

## Asset decisions and unresolved evidence

| Group | Existing inputs used | Explicit reconstruction choice | Remaining uncertainty |
| --- | --- | --- | --- |
| Passenger BEVs, EUR | REMIND Four Wheelers BEV stock/sales/service; UK 2022 first-use cohorts | REMIND serviceLife 20 years used as Weibull mean, with shape 3 an explicit non-REMIND assumption; equal service initially; stock- and inflow-driven cases | UK-to-EUR composition transfer; first use versus manufacture; unknown/old cohorts retained only as curated; true survival and mileage by age |
| Heavy trucks, EUR | REMIND liquid-fuel 40-tonne stock/sales/service; UK articulated diesel 32–40 t cohorts | REMIND serviceLife 15 years used as Weibull mean, with shape 3 an explicit non-REMIND assumption; equal service initially | Matching by weight and fuel, distance driven, weight carried, and trips without cargo, older/unknown registration dates, territorial exits versus disposal |
| PV, USA | REMIND PV capacity/new capacity/generation/lifetime; selected US-WECC crystalline plant cohorts and output | Native REMIND maximum-lifetime survival `max(0, 1-(age/tau)^4)`; initial observed output/capacity factors | Regional/system/AC–DC boundary; future degradation and curtailment allocation |
| CCGT, USA | REMIND unabated combined-cycle capacity/additions/generation/lifetime; selected non-CHP WECC blocks | Native REMIND maximum-lifetime survival; explicit proportional additional exits in stock mode | Dispatch, idle versus retired capacity, refurbished/old units and selective retirement; no gas-wide idle variable assigned to CCGT |
| Water infrastructure | Existing Quebec pipe/storage observations and reviewed pilot | Keep separate external-data constant-stock scenario | No reviewed matching REMIND stock/additions series; no IAM-derived water forecast |

The 20/15-year transport values come from REMIND `serviceLife`; treating them as
Weibull means with shape 3 remains a modelling assumption in this historical pilot.
Power uses the documented REMIND maximum-lifetime law: the IAM value is `tau`,
and its associated mean is `4*tau/5`. Existing initial composition can make these
useful conditional projections without establishing empirical validity of the
transport priors or the proxy initial cohorts.

The initial implementation provided eight cases per IAM group: primary stock-driven,
reported-inflow-driven, 25% shorter lifetime, 25% longer lifetime, equal service,
3% annual age decay of service, stationary initial age composition, and half-year
exposure of new cohorts. Equal service duplicates the vehicle primary by design;
it isolates the difference between observed-output and capacity weighting for
power. This is a sensitivity set, not a probability distribution or confidence
interval. Shape and selective-retirement uncertainty remain future extensions.

The [joint annualisation revision](joint-stock-annualisation.md) makes the primary
case a constrained annual fit, retains the linear-stock reconstruction as an
additional comparator, and adds inflow-penalty sensitivities of 1 and 100 around
the primary value 10. Of 44 proposed cases, 43 pass; CCGT age-decay is explicitly
rejected for exceeding the physical service limit. It is absent from exported
profiles and documented in `rejected-sensitivities.json`.

## Three release requirements

### 1. Correct boundaries and conserved coefficients

New variables change dates and shares, not exchange amounts or their original
common-amortisation denominators. Consumers require exact inventory identities
and units. They reject missing annual coverage rather than reusing a neighboring
year. Verify signed demands +1 and -2, repeated/reversed years, physical dates
before the inventory horizon, and zero-weight future cohorts.

Keep existing reviewed component, replacement and disposal rules separate.
This feature does not supply a new physical retirement/disposal model or apply
parent weights automatically to every component. The complete earlier licensed
pilots remain unchanged; their lifecycle regression tests still apply.

### 2. Defensible reconstruction and uncertainty

Test replacing assets with a fixed lifetime against a result calculated by hand.
Compare equivalent cases with FLODyM. Check survival of the starting stock,
lifetimes that vary by build year, declines, recovery from zero stock, totals for
reporting periods, units, and cases that cannot be matched. The tool should stop
on missing or invalid selected values, duplicate rows, or incomplete reporting periods.

For the scenario file, check that each original value is preserved to the
precision used to write it. Check that each group's stock is nonnegative and
appears only in or after its build year. Check that stock and use sum correctly,
recalculate the stock balance, and show differences from whichever input series
was used only as a check. Power generation must fit within 8760 hours of
full-load operation per year. Plot how the age breakdown changes when you vary
lifetimes, use during the year, and the ages of the starting stock.

Negative implied exits for BEV/PV diagnose disagreement in the independently
annualized input constraints. They do not prove REMIND itself is inconsistent.
Truck/CCGT totals can be feasible while still disagreeing with a chosen survival
or additional-exit model. Joint mode now preserves native stock anchors, checks
inflow-constraint feasibility and smooths annual additions. Incompatible inflows
are rejected or receive an explicitly configured penalty; all residuals remain
visible. Independent checks of the saved results compare its constraints with source
values and complete reporting windows, including internal years beyond export
coverage. Analytical tests cover five/ten-year windows and legacy compatibility.

### 3. Tests that run from preprocessing through TRAILS

Use the actual enriched SSP2-NPi2025 file through premise's real IAM reader,
including source/report verification and cached reads. Test filtering and
Fernet encryption through the public preprocessing CLI. Feed the four primary
profiles to the actual premise matrix/datapackage exporter, then load in TRAILS
with annual interpolation and explicit stock-vintage opt-in.

The test uses build-year shares from the IAM and a made-up inventory with the
same units as the earlier pilot. It checks the dates and amounts in the
life-cycle inventory for positive and negative demands against a calculation
done separately. It runs with both constant and changing background data. This
checks that the dates and amounts pass between the tools. The regional LCA
results using licensed data remain in the earlier pilot.

## Reproduction

Use the preprocessor's `stocks`/`dev` extras. The archive is the already acquired
private pilot evidence, containing `cohorts/` and `iam-inputs/`.

```console
python examples/run_remind_stock_pilot.py \
  --archive /path/to/existing-stock-vintage-evidence \
  --output-dir /path/to/new-local-evidence --end-year 2050
```

The script writes local initial-cohort CSVs, an explicit YAML config, one enriched
scenario, its JSON report, a source file list, mean-age tables and two PDF/PNG
figures. Output must be a new/empty directory. No scenario or observation data
is shipped in Git. The standard CLI can also be used with a hand-reviewed config.

For runtime export, give the scenario an accepted premise filename, preserving
its bytes, and use the paired premise branch's
`dev/stock_vintage/export_iam_enrichment_fixture.py`. Then run the paired TRAILS
branch's `dev/stock_vintage/check_iam_enrichment.py` on the integration output.
These scripts identify their inventory as synthetic. Use separate local
Brightway directories via `BRIGHTWAY2_DIR` when running tests using those example datasets.

Required checks:

```console
ruff check src tests examples
ruff format --check src tests examples
pytest
sphinx-build -W -b html docs docs/_build/html
```

Premise has dedicated `test_iam_stock_vintage.py` tests plus the existing
stock-vintage export suite. TRAILS retains its stock-vintage/lifecycle regression
suites and supplies the independent integration checker. Store executed results,
exact revisions, hashes and remaining limitations with the local artifacts.

## Supported horizon and priorities after this release

The reviewed example covers **2022–2050**. The engine supports explicitly declared
annual periods through 2100, but that is an interface limit, not proof that the
later REMIND reporting transformations are reconstructed correctly. The generic
irregular-window test checks arithmetic only. Before extending the actual power
example, review the five-to-ten-year transition and the reporter's window
mapping; a centred reported rate can mix native investment blocks.

Joint annualization at published stock anchors is implemented, conditional on
the selected survival and fixed exit fractions. Remaining priorities are
comparing selective exit assumptions; historical
backtesting with already available public observations; age-specific vehicle
use and plant dispatch/degradation; within-year exposure/retirement integration;
and a broader table matching regions and technologies. Original run fidelity, empirical
calibration and service allocation cannot be established by changing libraries.
