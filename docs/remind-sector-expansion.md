# REMIND sector expansion: stock-vintage reconstruction

This implementation extends the single `REMIND / SSP2-NPi2025` example to eleven
asset groups over 2022–2050. It uses the existing scenario and archived public
observations. It does not require additional REMIND team data. The existing BEV,
heavy-truck, PV and CCGT profiles remain available; seven groups are added below.
The catalogue is in `examples/run_remind_sector_expansion.py`.

The numerical results quoted below describe the archived campaign produced before
the documented REMIND maximum-lifetime law, annual-sample interpretation of
`New Cap`, and disclosed vehicle `serviceLife` values were implemented. Regenerate
the campaign before treating those figures as results of the current code.

## Added groups and data

| Asset ID | Region | Native stock / additions suffix after `Electricity` | Initial composition | Lifetime input |
|---|---|---|---|---|
| `passenger-liquids` | EUR | `Stock` / `Sales` of `Transport\|Pass\|Road\|LDV\|Four Wheelers\|Liquids` | UK DfT VEH1111, petrol + diesel cars, 2022 Q4, first-use year | REMIND serviceLife 20 years; assumed Weibull shape 3 |
| `wind-onshore` | USA | `Wind\|+\|Onshore` | US EIA-860 operating onshore generator MW by operating year | 25 years |
| `wind-offshore` | USA | `Wind\|+\|Offshore` | US EIA-860 operating offshore generator MW by operating year | 25 years |
| `nuclear` | USA | `+\|Nuclear` | US EIA-860 operating nuclear generator MW by operating year | 50 years |
| `gas-turbine` | USA | `Gas\|GT` | US EIA-860 operating natural-gas combustion turbines, excluding CHP | 30 years |
| `geothermal` | USA | `+\|Geothermal` | US EIA-860 operating geothermal generator MW by operating year | 30 years |
| `csp` | USA | `Solar\|+\|CSP` | US EIA-860 solar thermal generator MW, with and without storage | 30 years |

Power stock uses `Cap|Electricity|...` (GW), additions use
`New Cap|Electricity|...` (GW/yr), service uses `SE|Electricity|...` (EJ/yr).
Gas-turbine service has the different suffix `Gas|++|Gas Turbine`; lifetime uses
`Tech|Electricity|Gas|Gas Turbine|Lifetime`. All variable names and units are checked
exactly. Vehicle service is `ES|Transport|Pass|Road|LDV|Four Wheelers|Liquids`
(billion pkm/yr); stock and sampled annual sales use the native `million veh` unit.
Power lifetime series are maximum lifetimes under REMIND's documented survival
`max(0, 1-(age/tau)^4)`; the associated mean is `4*tau/5`. Depreciation represents
dismantlement rather than efficiency loss. The vehicle prior remains a separate
explicit modelling assumption. No aggregate and its children are summed.

The UK data source is [DfT VEH1111](https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-tables).
Use the archived ODS numeric values rather than rounded display strings. Known
first-use-year counts plus unknown counts must equal the published fuel total.
The combined observed stock is 30,846,413 cars; 442,363 have unknown first-use year.
Unknown dates are assigned in proportion to known dates for the model input;
the unaltered quantities and missing-date fraction remain in the audit.
No survival weighting is applied to the observed initial composition.

REMIND provides a **combined Liquids fleet**, not separate petrol and diesel
stock trajectories. The default is therefore a conventional petrol + diesel
initial-composition proxy. The correspondence to native hybrid/fuel categories
is not fully resolved. Two sensitivities apply petrol-only and diesel-only
initial compositions to that same combined trajectory. They must not be added
together, interpreted as fuel forecasts, or silently bound to separate petrol
and diesel inventories as if such forecasts had been supplied by the IAM.
An explicit inventory mapping and allocation decision is still needed there.

Power observations come from [EIA-860](https://www.eia.gov/electricity/data/eia860/),
2022 generator workbook, `Operable` sheet. The survey covers generators at plants
with at least 1 MW combined nameplate capacity. The sheet also contains standby
and out-of-service records: the example selects `Status == OP`, the 50 states
plus DC, and explicit non-CHP records. Generator IDs must be unique within plants.
For each excluded category, we recorded the number of entries and total capacity. Dates and positive
capacity are checked before aggregation. Observed totals are not substituted for
IAM totals: only cohort shares are scaled. The audit reports the IAM-to-observed
stock ratio so large boundary or calibration mismatches remain visible.

Offshore wind starts from only **two generator records**, representing 42 MW;
these are not turbine counts. US coverage improves the geographical match over
the existing WECC PV/CCGT proxy, but size thresholds, availability, nameplate
conventions, aggregation and scenario calibration can still differ. Operating
year is an entry-date proxy, not an observed manufacture or refurbishment date.
For CSP, the profile represents electricity-generation capacity; it does not
supply a separate storage-equipment lifetime. Repowering, nuclear life extensions
and component replacement are not inferred from the generator operating year.

In this run, the interpolated IAM 2022 stock is about 18.0 times the observed
offshore capacity, 0.335 times the selected gas-turbine capacity and 1.609 times
the CSP capacity. These are substantial calibration/boundary differences, not
evidence that all regional stocks have been empirically validated. Offshore's
sparse observed age shape is especially uncertain. The liquid-car factor of
7.95 also reflects that UK shares initialize a much larger EUR fleet.

## Annualisation, survival and service

The [joint annualisation method](joint-stock-annualisation.md) is retained.
Native stock anchors are hard constraints. Annual vehicle sales and power
`New Cap` values are sampled annual rates and missing years are linearly
interpolated. A penalized
policy reconciles incompatible inflow observations and reports every residual;
no claim is made that all stock and inflow observations can be met simultaneously.
Additional-exit fractions are fixed from the linear-stock baseline, proportional
across naturally surviving cohorts. They are assumptions, not observed scrappage.
Smoothing does not remove real commissioning-year concentrations in the initial
observations, and no smoothing is applied to the final plotted distributions.

Rare observed old vehicles can have a mathematically positive Weibull survival
probability below floating-point precision. Conditional survival now uses
`exp(-(H(age) - H(reference_age)))`, rather than dividing two absolute survival
probabilities. Observed 1900-era cars are retained, including in the short-life
short-life sensitivity. Historical entries are not reconstructed from those
survivors. This numerical treatment does not establish that the same lifetime
law adequately describes collector vehicles. Impossible fixed-lifetime cohorts
still fail. The stationary-inflow initialization continues to use unconditioned
survival; future cohorts still use flodym's survival matrix.

New groups assume equal service per vehicle or per GW. Consequently their stock
shares and service shares are equal under the default assumption; reported total
service does not identify cohort-specific mileage or capacity factors. Power
cases must respect 0.031536 EJ/yr per GW (8,760 hours). Optional cases violating
this bound are recorded in `rejected-sensitivities.json` and not exported. A
failure in the main case, an incorrect variable name or unit, or a failed calculation stops the run.
Pinned OSQP performs the convex quadratic solve after an independent HiGHS
feasibility check; stock conservation and solver-certificate tolerances are
never relaxed.

Each new group includes primary, linear-stock, inflow-only, ±25% maximum lifetime,
and low/high inflow-penalty cases. Existing groups retain their original broader
sensitivity set. Scenario stock/service changes and lifetime assumptions do not
by themselves change the inventory's total capital-production coefficient:
this feature distributes an existing burden over cohort dates under common
amortisation. Technology-specific production coefficients and different
lifetime-allocation rules require separate justification.

## Reproduction and acceptance

Install the stock extra, then run from the repository:

```sh
PYTHONPATH=src python examples/run_remind_sector_expansion.py \
  --archive /absolute/path/to/2026-10-10-pilots \
  --output-dir /absolute/path/to/empty-output
```

The plotting script for the historical report is available in Git history at
`83cf844:examples/plot_remind_sector_expansion.py`.

The archive list, starting stock, original DfT and EIA files, and IAM input are
checked against recorded SHA-256 file fingerprints. The first report records
which entries were used, missing dates, starting-stock files, and input variable
names. The run report records the settings, code, observations, and outputs.
Keep both reports. Keep private scenarios and observations outside Git.

Check that the saved CSV preserves reported stock values, that shares are
nonnegative and sum to one when stock is present, and that future cohorts have
no stock. Check the stock balance, differences across each full reporting
period, and survival of the starting stock independently. The PDF and CSV tables
compare the main results and alternatives for all eleven groups. Compare
unfiltered, filtered, encrypted, and cached results. The test from `premise` to
TRAILS uses the calculated shares with made-up inventories and with background
data that are either constant or change over time.

The runtime loader expects the filename `remind_SSP2-NPi2025.csv`; create a link
to the generated CSV in each of the unfiltered, filtered and encrypted test
directories. The ordinary `stock-vintages` command can generate the latter two
with `--filter-output` and `--encrypt-to`. Use an ephemeral test key and remove
it after testing. `examples/export_sector_runtime_fixture.py` accepts
`--premise-checkout` and `--directory` (the campaign output). It uses the test
export script in the corresponding `premise` branch and covers all eleven main groups.
Run premise's `dev/stock_vintage/check_iam_enrichment_runtime.py` for all cases
and TRAILS' `dev/stock_vintage/check_iam_enrichment.py` on the resulting
`integration` directory. The inventory amounts used here are examples for
testing. Production processes would need separately reviewed links.

## Deferred groups and next priorities

The next implementation package is specified in the
[priorities 1–3 plan](remind-evidence-work-package.md), with a separate
[data and validation protocol](remind-evidence-protocol.md). It covers stock
comparability, historical cohort evaluation and service weighting for the
existing eleven groups.


| Group | Blocking issue for a defensible default | Work possible with current files |
|---|---|---|
| Separate petrol/diesel trajectories | Native fleet is combined | Keep combined profile and tests with different starting ages; require declared split before linking the fuels to separate inventory exchanges |
| Hybrids/PHEVs | Native Hybrid electric versus UK HEV/PHEV/range-extender mapping | Inspect archived reporter technology definitions; avoid merging categories by name |
| Gas/FCEV vehicles | Gas/LPG/bi-fuel boundary and sparse initial cohorts | Audit native categories and DfT selections; use explicit sensitivity if initial support is weak |
| Hydro | Conventional versus pumped-storage boundary | Compare EIA conventional/pumped classes with native aggregate capacity; do not sum blindly |
| Coal/biomass | CHP, CCS and technology aggregates | Build tables matching the most detailed technology categories without overlap and audit plant technology/fuel/CHP fields |
| Battery storage | GW versus GWh assets; duration and cycle ageing | Separate converter and energy stocks, define service and initialize each independently |
| Heat/hydrogen/industry | Equipment boundary, service unit and initial cohorts | Audit native capacity/additions/lifetime availability before choosing a prior |
| Buildings/roads/water | No reviewed mapping to the reported stock variables in this pilot | Continue the separate observation-based infrastructure strategy |

The accepted regional proxies are not treated as a blocker. The most useful
improvements within current data are: tables matching the IAM's technology categories, age-specific
service from EIA generation data, status/nameplate-boundary sensitivities, and
component/repowering treatment. Expanding to other scenarios, regions, zero-initial
stock technologies or post-2050 ten-year windows needs explicit new validation.
The absence of a detailed vintage variable in an IAM does not block reconstruction,
but it limits what can be presented as observed or uniquely determined.
