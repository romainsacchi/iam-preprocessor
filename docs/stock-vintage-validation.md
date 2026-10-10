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
| Passenger BEVs, EUR | REMIND Four Wheelers BEV stock/sales/service; UK 2022 first-use cohorts | Weibull mean 16 years, shape 3 as an explicit prior; equal service initially; stock- and inflow-driven cases | UK-to-EUR composition transfer; first use versus manufacture; unknown/old cohorts retained only as curated; true survival and mileage by age |
| Heavy trucks, EUR | REMIND liquid-fuel 40-tonne stock/sales/service; UK articulated diesel 32–40 t cohorts | Weibull mean 12 years, shape 3 as a prior; equal service initially | Weight/fuel crosswalk, mileage/payload/empty running, older/unknown registration dates, territorial exits versus disposal |
| PV, USA | REMIND PV capacity/new capacity/generation/lifetime; selected US-WECC crystalline plant cohorts and output | Technical-life variable used as a declared Weibull-mean prior; shape 3; initial observed output/capacity factors | Technical life is not empirical mean survival; regional/system/AC–DC boundary; future degradation and curtailment allocation |
| CCGT, USA | REMIND unabated combined-cycle capacity/additions/generation/lifetime; selected non-CHP WECC blocks | Technical-life variable used as a declared Weibull-mean prior; shape 3; explicit proportional additional exits in stock mode | Dispatch, idle versus retired capacity, refurbished/old units and selective retirement; no gas-wide idle variable assigned to CCGT |
| Water infrastructure | Existing Quebec pipe/storage observations and reviewed pilot | Keep separate external-data constant-stock scenario | No reviewed matching REMIND stock/additions series; no IAM-derived water forecast |

The 16/12-year transport means are modelling priors, not the old 20/15-year
support parameters renamed as means. Power's technical-life reinterpretation
is similarly an assumption. Existing initial composition can make these useful
conditional projections without establishing empirical validity of the priors.

Each of the four IAM groups has eight cases: primary stock-driven,
reported-inflow-driven, 25% shorter lifetime, 25% longer lifetime, equal service,
3% annual age decay of service, stationary initial age composition, and half-year
exposure of new cohorts. Equal service duplicates the vehicle primary by design;
it isolates the difference between observed-output and capacity weighting for
power. This is a sensitivity set, not a probability distribution or confidence
interval. Shape and selective-retirement uncertainty remain future extensions.

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

Test fixed-life replacement against an analytical solution; compare compatible
cases against flodym's own stock/inflow-driven solvers. Verify conditional
initial survival, cohort-specific new lives, declines, zero-stock restart,
reporting-period integrals, units and infeasible conditions. Selected missing
or nonfinite data, duplicate rows and incomplete reporting windows fail.

For the real file, preserve every original anchor to floating-point serialization
precision, verify every cohort's nonnegativity and chronology, reconcile cohort
quantities/shares/service totals, independently recompute stock balances, and
report residuals relative to the unused stock or inflow constraint. Power cases
enforce a declared 8760-hour service/capacity bound. Plot age distributions and
lifetime, service-exposure, utilization and initial-state sensitivities.

Negative implied exits for BEV/PV diagnose disagreement in the independently
annualized input constraints. They do not prove REMIND itself is inconsistent.
Truck/CCGT totals can be feasible while still disagreeing with a chosen survival
or additional-exit model. A constrained joint fit remains distinct future work;
this version exposes both endpoint reconstructions and their residuals.

### 3. Actual producer–consumer evidence

Use the actual enriched SSP2-NPi2025 file through premise's real IAM reader,
including source/report verification and cached reads. Test filtering and
Fernet encryption through the public preprocessing CLI. Feed the four primary
profiles to the actual premise matrix/datapackage exporter, then load in TRAILS
with annual interpolation and explicit stock-vintage opt-in.

The new integration fixture uses **actual IAM-derived profiles and a synthetic
inventory** with coefficients matching the earlier pilot units. It checks exact
pulses and signed LCI against an independent analytical result for both constant
and changing background intensities. It proves the new interface and calendar
semantics. It is not a new full ecoinvent regional LCA or independent empirical
validation. The earlier complete licensed-pilot evidence is retained separately;
there is no automatic release of global default stock distributions.

## Reproduction

Use the preprocessor's `stocks`/`dev` extras. The archive is the already acquired
private pilot evidence, containing `cohorts/` and `iam-inputs/`.

```console
python examples/run_remind_stock_pilot.py \
  --archive /path/to/existing-stock-vintage-evidence \
  --output-dir /path/to/new-local-evidence --end-year 2050
```

The script writes local initial-cohort CSVs, an explicit YAML config, one enriched
scenario, its JSON report, a source manifest, mean-age tables and two PDF/PNG
figures. Output must be a new/empty directory. No scenario or observation data
is shipped in Git. The standard CLI can also be used with a hand-reviewed config.

For runtime export, give the scenario an accepted premise filename, preserving
its bytes, and use the paired premise branch's
`dev/stock_vintage/export_iam_enrichment_fixture.py`. Then run the paired TRAILS
branch's `dev/stock_vintage/check_iam_enrichment.py` on the integration output.
These scripts identify their inventory as synthetic. Use separate local
Brightway directories via `BRIGHTWAY2_DIR` when running fixture tests.

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

Highest priorities with no new team data are: joint constrained annualization at
published stock anchors; comparing selective exit assumptions; historical
backtesting with already available public observations; age-specific vehicle
use and plant dispatch/degradation; within-year exposure/retirement integration;
and a broader geography/technology crosswalk. Exact-run fidelity, empirical
calibration and service allocation cannot be established by changing libraries.
