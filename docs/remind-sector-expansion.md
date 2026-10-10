# REMIND sector expansion: stock-vintage reconstruction

This implementation extends the single `REMIND / SSP2-NPi2025` example to eleven
asset groups over 2022–2050. It uses the existing scenario and archived public
observations. It does not require additional REMIND team data. The existing BEV,
heavy-truck, PV and CCGT profiles remain available; seven groups are added below.
The catalogue is in `examples/run_remind_sector_expansion.py`.

## Added groups and data

| Asset ID | Region | Native stock / additions suffix after `Electricity` | Initial composition | Mean lifetime prior |
|---|---|---|---|---|
| `passenger-liquids` | EUR | `Stock` / `Sales` of `Transport\|Pass\|Road\|LDV\|Four Wheelers\|Liquids` | UK DfT VEH1111, petrol + diesel cars, 2022 Q4, first-use year | 16 years |
| `wind-onshore` | USA | `Wind\|+\|Onshore` | US EIA-860 operating onshore generator MW by operating year | 25 years |
| `wind-offshore` | USA | `Wind\|+\|Offshore` | US EIA-860 operating offshore generator MW by operating year | 25 years |
| `nuclear` | USA | `+\|Nuclear` | US EIA-860 operating nuclear generator MW by operating year | 50 years |
| `gas-turbine` | USA | `Gas\|GT` | US EIA-860 operating natural-gas combustion turbines, excluding CHP | 30 years |
| `geothermal` | USA | `+\|Geothermal` | US EIA-860 operating geothermal generator MW by operating year | 30 years |
| `csp` | USA | `Solar\|+\|CSP` | US EIA-860 solar thermal generator MW, with and without storage | 30 years |

Power stock uses `Cap|Electricity|...` (GW), additions use
`New Cap|Electricity|...` (GW/yr), service uses `SE|Electricity|...` (EJ/yr).
Gas-turbine service has the different suffix `Gas|++|Gas Turbine`; lifetime uses
`Tech|Electricity|Gas|Gas Turbine|Lifetime`. All selectors and units are checked
exactly. Vehicle service is `ES|Transport|Pass|Road|LDV|Four Wheelers|Liquids`
(billion pkm/yr); stock and sampled annual sales use the native `million veh` unit.
Power lifetime series are reinterpreted as Weibull mean priors, with shape 3;
this is not an assertion that REMIND uses that retirement law. The vehicle prior
is an explicit modelling assumption. No aggregate and its children are summed.

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
Each excluded category has a record-count and capacity ledger; dates and positive
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
Native stock anchors are hard constraints. Annual vehicle sales are sampled
rates; power additions are five-year reporting-window means. Solve full windows,
including the internal 2051–2052 years, before exporting through 2050. A penalized
policy reconciles incompatible inflow observations and reports every residual;
no claim is made that all stock and inflow observations can be met simultaneously.
Additional-exit fractions are fixed from the linear-stock baseline, proportional
across naturally surviving cohorts. They are assumptions, not observed scrappage.
Smoothing does not remove real commissioning-year concentrations in the initial
observations, and no smoothing is applied to the final plotted distributions.

Rare observed old vehicles can have a mathematically positive Weibull survival
probability below floating-point precision. Conditional survival now uses
`exp(-(H(age) - H(reference_age)))`, rather than dividing two absolute survival
probabilities. Observed 1900-era cars are retained, including in the 12-year
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
primary-case failure, selector error or numerical solver failure aborts the run.
SLSQP convergence may be refined once if an independent convex optimality check
fails; stock conservation and KKT tolerances are never relaxed.

Each new group includes primary, linear-stock, inflow-only, ±25% mean lifetime,
and low/high inflow-penalty cases. Existing groups retain their original broader
sensitivity set. Scenario stock/service changes and lifetime assumptions do not
by themselves change the inventory's total capital-production coefficient:
this feature distributes an existing burden over cohort dates under common
amortisation. Technology-specific production coefficients and different
lifetime-allocation rules require separate justification.

## Reproduction and acceptance

Install the stock extra and plotting dependencies, then run from the repository:

```sh
PYTHONPATH=src python examples/run_remind_sector_expansion.py \
  --archive /absolute/path/to/2026-10-10-pilots \
  --output-dir /absolute/path/to/empty-output
PYTHONPATH=src python examples/plot_remind_sector_expansion.py \
  /absolute/path/to/empty-output
```

The archive manifest, original curated cohorts, raw DfT/EIA files and IAM input
are SHA-256 pinned. The curation audit keeps selection, missing dates, initial CSV
hashes and source selectors. The ordinary enrichment report records configuration,
implementation, observation and output hashes. Preserve both reports. Generated
scenario data and raw observations are local and must not be committed.

Acceptance includes exact source-anchor preservation; finite, nonnegative,
normalized shares; stock balance; chronological validity; full-window source
residual accounting; and independent analytic conditional survival checks from
the serialized CSV. The PDF and CSV tables compare primary distributions, annual
inflows and sensitivities for all eleven groups. Runtime checks must compare
unfiltered, filtered, encrypted and cached profiles. A premise-to-TRAILS fixture
uses the actual profiles with explicit synthetic inventories and both constant
and varying backgrounds; it is not a complete regional ecoinvent LCA.

The runtime loader expects the filename `remind_SSP2-NPi2025.csv`; create a link
to the generated CSV in each of the unfiltered, filtered and encrypted test
directories. The ordinary `stock-vintages` command can generate the latter two
with `--filter-output` and `--encrypt-to`. Use an ephemeral test key and remove
it after testing. `examples/export_sector_runtime_fixture.py` accepts
`--premise-checkout` and `--directory` (the campaign output), uses the paired
consumer branch's fixture exporter and covers all eleven primary groups.
Run premise's `dev/stock_vintage/check_iam_enrichment_runtime.py` for all cases
and TRAILS' `dev/stock_vintage/check_iam_enrichment.py` on the resulting
`integration` directory. The additional synthetic inventory coefficients are
test constants; they do not constitute reviewed production-burden bindings.

## Deferred groups and next priorities

| Group | Blocking issue for a defensible default | Work possible with current files |
|---|---|---|
| Separate petrol/diesel trajectories | Native fleet is combined | Keep combined profile and initial-composition sensitivities; require declared split before separate binding |
| Hybrids/PHEVs | Native Hybrid electric versus UK HEV/PHEV/range-extender mapping | Inspect archived reporter technology definitions; avoid merging categories by name |
| Gas/FCEV vehicles | Gas/LPG/bi-fuel boundary and sparse initial cohorts | Audit native categories and DfT selections; use explicit sensitivity if initial support is weak |
| Hydro | Conventional versus pumped-storage boundary | Compare EIA conventional/pumped classes with native aggregate capacity; do not sum blindly |
| Coal/biomass | CHP, CCS and technology aggregates | Build exact disjoint leaf crosswalks and audit plant technology/fuel/CHP fields |
| Battery storage | GW versus GWh assets; duration and cycle ageing | Separate converter and energy stocks, define service and initialize each independently |
| Heat/hydrogen/industry | Equipment boundary, service unit and initial cohorts | Audit native capacity/additions/lifetime availability before choosing a prior |
| Buildings/roads/water | No reviewed native stock crosswalk in this pilot | Continue the separate observation-based infrastructure strategy |

The accepted regional proxies are not treated as a blocker. The most useful
improvements within current data are: native technology crosswalks, age-specific
service from EIA generation data, status/nameplate-boundary sensitivities, and
component/repowering treatment. Expanding to other scenarios, regions, zero-initial
stock technologies or post-2050 ten-year windows needs explicit new validation.
The absence of a detailed vintage variable in an IAM does not block reconstruction,
but it limits what can be presented as observed or uniquely determined.
