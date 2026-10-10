# REMIND evidence work package: implementation plan for priorities 1–3

Status: planned; implementation has not started. Prepared 2026-10-10 against
`feat/stock-sector-expansion`, baseline commit
`83cf844b169a9057131cf906941488701b58a50d`.

## Objective and bounded scope

Strengthen the eleven existing stock-vintage groups by (1) explaining differences
between observed and IAM stocks, (2) evaluating historical cohort reconstruction,
and (3) replacing equal-service assumptions where usable evidence supports a
better estimate. Keep REMIND SSP2-NPi2025 as the sole scenario and retain the
2022–2050 production horizon. Historical evaluation is a separate experiment.

Groups: passenger BEVs, heavy trucks, liquid-fuel passenger cars, PV, CCGT,
onshore wind, offshore wind, nuclear, gas turbines, geothermal and CSP.
The accepted UK-to-EUR and existing WECC-to-USA proxies remain permitted, with
explicit provenance. No additional REMIND-team data is required.

The principal deliverable is a reproducible, per-group evidence assessment with
qualified profile updates. Completion does not require every candidate method
to outperform the current model. A documented negative result or a justified
fallback is a valid outcome; an unmeasured improvement claim is not.

This package does not fit new retirement laws, optimize additional retirements,
create separate petrol/diesel scenario trajectories, add new asset sectors,
change capital-production coefficients, or implement component replacement.
Those belong to later work packages. Meaningful defects found in the existing
accounting can be corrected with dedicated regression tests and change records.

## Baseline and verified starting point

The existing campaign has 11 primary groups, 93 accepted cases, 2,697 annual
profiles, 61 passing tests and 176 signed-demand consumer checks. Its production
report is under `trails/build/reports/remind-npi2025-sector-expansion/`; preserve
it as the comparison baseline. These are numerical and integration checks, not
historical predictive validation.

Current code and consequences:

- `stock_observations.py` reads `3_1_Generator_Y2022.xlsx` explicitly. It returns
  operating rows but loses the identities and status transitions needed for a
  panel spanning several years. Generalize this reader before backtesting.
- `run_remind_sector_expansion.py` hard-codes technology selectors and assumes
  2022 initial shares. Put reviewed mappings and source boundaries in a small
  versioned registry shared by audits and configuration generation.
- `stock_vintages.py` already supports observed initial service factors and a
  declared factor for future entrants. It can consume the first power-service
  improvements without a change to the output namespace or consumer schema.
- Initial service factors remain associated with cohorts as they age. They are
  not automatically an age-dependent utilization curve.
- `stock_annualisation.py` rejects partial initial power-reporting windows. A
  2020 historical test must not pass a truncated 2018–2022 IAM window as a fully
  observed annual inflow. Use a separate historical driver and full annual data
  where available; retain the production window rules.

## Data already available

A pinned data inventory, fields and experimental rules are in
[the evidence protocol](remind-evidence-protocol.md).

| Input | Verified availability | Use in this package |
|---|---|---|
| REMIND SSP2-NPi2025 MIF and archived reporter code | Existing immutable pilot archive | Exact variable/unit/category definitions; 2020 native stock; 2022 interpolated stock; original production scenario |
| EIA-860 2020, 2021, 2022 | All three local ZIP files inspected; 2020/2021 currently in a temporary directory | US stock panels, stable generator identities, capacity and status changes, historical cohort evaluation |
| EIA-923 2022 | Archived ZIP; generator and plant/prime-mover generation sheets inspected | Relative power-service factors and coverage assessment |
| UK DfT VEH1111 | Archived ODS contains year-end observations for 2014–2025 | BEV, liquid-car and HGV cohort histories; unknown-date accounting |
| DfT VEH0520 | Archived detailed HGV file | Fleet-boundary and weight-class checks; not a mileage source |
| Existing PV/CCGT curation and service audit | Earlier premise pilot scripts | Reuse audited matching/block logic after generalization, with tests |

First promote the temporary 2020/2021 EIA files into a new immutable evidence
snapshot, verify their existing hashes and write a new manifest. Do not edit the
previous snapshot. Check legal units, table definitions, observation dates and
revision metadata before aggregating data.

A bounded public-data assessment for vehicle usage is included: official UK
vehicle-survey tables, commercial-vehicle utilization tables, and documented MOT
odometer extracts if accessible. Eligibility requires a usable joint age/body/
fuel classification, sampling weights and the right mileage denominator. No
suitable mileage-by-age dataset has yet been verified locally. Log inspected
candidates and rejection reasons; the package remains completable with explicit
vehicle sensitivities if none qualifies. No paid access, external contact or
REMIND-team request is needed.

## Workstream 1 — explain stock discrepancies

### Implementation

1. Build one exact mapping record per group: IAM stock/inflow/service selectors,
   units, source geography, source technology codes, status boundary, CHP/CCS
   boundary, capacity definition, commissioning/first-use semantics, provenance,
   and mapping status (`supported`, `proxy`, `unresolved`). Resolve labels through
   the archived reporter definitions where possible; record remaining uncertainty.
2. Parse EIA snapshots with unique generator keys and all relevant statuses. Keep
   both the complete raw candidate set and each disjoint selection/exclusion.
   Add national PV/CCGT comparison views without silently replacing their current
   WECC initial profiles. Review CCGT block versus component capacity explicitly.
3. Produce native-year 2020 comparisons, then observed 2021/2022 versus declared
   IAM interpolation. Distinguish nameplate versus seasonal capability, PV AC/DC,
   utility-scale versus distributed PV, CHP and non-operating capacity. Do not
   choose filters solely because they make totals agree.
4. For offshore wind, separate the 2020 anchor discrepancy from growth assigned
   to 2021/2022 by interpolation. Test a labelled timing sensitivity only if it
   preserves the complete source window and native stock anchors. Diagnose first;
   do not claim an 18-fold technology mismatch from the current ratio alone.
5. For gas turbines, check the exact gas/CCGT/CHP partition and excluded capacity.
   For CSP, check the electricity-capacity boundary and storage-equipped plants.
   For nuclear and geothermal, check operational status and date/capacity changes.
6. For vehicles, report UK and EUR totals separately. Their ratio is a proxy
   scaling factor, not a like-for-like validation error. Check conventional ICE,
   hybrid/PHEV and HGV category definitions; retain the combined Liquids boundary.
7. Write a discrepancy ledger with absolute values, ratios when denominators are
   positive, comparison year, selection masses, possible explanations, supporting
   evidence and unresolved remainder. Overlapping explanations must not be summed
   as though they were independent contributions.

### Deliverables and acceptance

- `stock-asset-mappings.yaml`, `stock-comparison.csv`, `stock-discrepancies.json`.
- Per-group 2020–2022 plots: observed totals, native anchors, interpolated values,
  and explicitly labelled alternative boundaries.
- All eleven groups have an evidence status and a documented comparison boundary.
  Every included/excluded source record is accounted for; duplicate or overlapping
  aggregation fails. Missing/zero denominators produce explicit status codes.
- Each large discrepancy has an evidenced explanation or an unresolved label.
  Numerical closeness alone cannot promote an unresolved mapping.

## Workstream 2 — historical cohort evaluation

### Implementation

1. Freeze the protocol, comparisons and parameter priors before evaluating held-out
   outcomes. These are retrospective tests using the acquired data revision, not
   recreations of the exact information available to a modeller in 2020.
2. Build a generator panel keyed by plant and generator identity. Record actual
   retirement evidence, returns to operation, status changes, capacity uprates/
   derates, cohort-date revisions, changes of asset category and records appearing
   or disappearing from coverage. Missing records are not assumed retired.
3. Use 2020 initialization and 2021 development evaluation, then a frozen 2022
   holdout for power. Keep 2022 cohort outcomes out of parameter selection. The
   current model priors are the starting candidates; preserve a prior-only run.
4. Run the three separate experiments specified in the protocol:
   - Opening-cohort survival diagnostics, with independently observable membership.
   - Known-inflow reconstruction where an independently supported commissioning
     series exists; label its use as conditioning information.
   - Composition reconstruction conditional on observed aggregate closing stock,
     while withholding the closing cohort shares.
5. For UK vehicles, retain apparent net cohort retention, including values above
   one caused by imports, re-licensing or revisions. Evaluate the current cohort
   model without treating that ratio as a pure retirement probability. An observed
   youngest closing cohort is not automatically a gross sales series.
6. Use 2014–2020 vehicle histories for development where compatible, keep 2021 as
   a development comparison and 2022 as a fixed initial holdout. The available
   2023–2025 snapshots provide an additional frozen test after a 2022 initialization.
   Run these against UK quantities, separately from EUR scenario projections.
7. Compare the current lifetime model with a simple documented ageing baseline
   and the stationary-age initialization sensitivity. Score exact annual cohorts,
   fixed age bins and old-age tails. Include unmatched mass and data revisions in
   the results instead of discarding them before computing errors.

### Deliverables and acceptance

- `generator-transitions.csv`, `vehicle-cohort-history.csv`,
  `backtest-predictions.csv`, `backtest-metrics.csv`, `backtest-decisions.json`.
- Cohort heatmaps, observed/predicted age-share plots, retention plots, cumulative
  age-distribution errors and residuals by coverage/status category.
- Scores report what was supplied to the model and what was withheld. A fitted
  closing total or a matched native IAM anchor earns no predictive accuracy credit.
- Historical data support is reported per group; sparse offshore coverage is a
  descriptive case, not population-level validation. Two years of power snapshots
  do not identify a complete lifetime distribution.
- Unit tests cover leakage guards, ambiguous identity changes, capacity versus
  count weighting, imports/returns, cohort revisions, missing records and a known
  analytical cohort example. A failed empirical fit is reported, not suppressed.

## Workstream 3 — service weighting with observed generation and usage evidence

### Implementation

1. Port and generalize the earlier `audit_power_service.py` matching logic into
   the preprocessor. Match EIA-923 generation to EIA-860 plant/generator IDs. Permit
   padded numeric aliases only after proving a unique one-to-one mapping. Validate
   fuel, prime mover, technology, year and CHP scope alongside the identity.
2. Use the evidence hierarchy: direct generator output; unambiguous single-cohort
   plant output; explicit allocation of multi-cohort plant output; equal-service
   fallback. Mark the third level as estimated allocation, not observed cohort use.
   Never sum page-4 output and page-1 totals for the same production twice.
3. Reconcile annual generation with the end-year-stock service convention. Keep
   retired-in-year generation, partial-year entrants and assets outside the closing
   operating stock in separate ledgers. Derive the first default factors from
   full-year comparable observations; use monthly data and commissioning dates
   where reliable. Report the service excluded from this calibration population.
4. Compute cohort-level output/capacity factors, normalize by the matching fleet
   average, and preserve equal-service comparators. Keep all stock in the model;
   unmatched output is not zero output and matched plants must not silently become
   the whole regional fleet. Record coverage by capacity, output and cohort.
5. Keep observed cross-sectional factors distinct from an ageing law. For initial
   cohorts, the first supported implementation uses `observed_factors`, with a
   documented factor for future entrants. Weather, site and dispatch differences
   observed in 2022 are not interpreted as causal age effects or projected trends.
6. For vehicles, assess usage sources separately for cars and trucks. A mileage
   factor only maps directly to vehicle-kilometres. Passenger-kilometres require
   occupancy and tonne-kilometres require payload/load-factor assumptions. If only
   age-decay sensitivities are defensible, specify them before inspecting results
   and retain the equal-service default. If a usable non-exponential age table is
   found, implement an opt-in, tested age lookup; a fixed cohort factor is not an
   adequate substitute for a curve that must evolve as the cohort ages.
7. Apply the service-coverage/default-selection rules in the protocol, then rerun
   the same REMIND pilot. Compare service shares, mean service-weighted age, birth-
   year quantiles and source/mass-balance diagnostics with the frozen baseline.
   Preserve stock-only outputs when only the service weights change.

### Deliverables and acceptance

- `power-generation-matches.csv`, `service-coverage.csv`,
  `service-factors.csv`, `vehicle-usage-source-assessment.md`,
  `service-weighting-decisions.json` and updated initial-factor CSVs.
- For each group: direct evidence coverage, allocated coverage, missing coverage,
  selected policy, fallback and its effect on the service-vintage distribution.
- No raw negative generation is clipped into a valid nonnegative service factor.
  Missing values, negative net generation and reporting conflicts have separate
  diagnostics. Physical output bounds remain enforced.
- A service-weight update cannot change total stock, native stock/inflow constraints
  or total capital-production coefficients. It may change the temporal shares and
  their resulting impacts. Consumer metadata records the chosen method.
- Quantitative validation of power service-factor prediction requires another
  generation year. The current 2022 archive supports reconciliation and sensitivity
  analysis only; historical stock tests do not substitute for that missing check.

## Planned code boundaries

Names below are proposed implementation targets, not existing public APIs.

| Location | Responsibility |
|---|---|
| `src/iam_preprocessor/stock_observations.py` | Year-aware source readers; lossless identities/statuses; raw audit records |
| `src/iam_preprocessor/data/remind_stock_assets.yaml` | Exact selectors, source boundaries and evidence labels |
| `src/iam_preprocessor/stock_history.py` | Snapshot reconciliation and historical event ledgers |
| `src/iam_preprocessor/stock_validation.py` | Historical experiments, metrics and leakage guards |
| `src/iam_preprocessor/stock_service.py` | Generation joins, coverage, factors and fallback policies |
| `stock_config.py`, `stock_vintages.py` | Only necessary opt-in service options; retain legacy configurations and namespace |
| `examples/run_remind_evidence_campaign.py` | Reproducible staged campaign with a source manifest and explicit configuration |
| `examples/plot_remind_evidence_campaign.py` | Standalone PDF, plots and their numeric tables |
| `tests/test_stock_history.py`, `tests/test_stock_service.py` | Scientific and data-contract regressions with small synthetic fixtures |

Reuse generic producer and consumer validation scripts. No initial premise or
TRAILS runtime changes are expected. Any required consumer change must receive
its own compatibility check and commit. Source files and generated scenarios
remain outside version control; commit schemas, mapping provenance, scripts,
documentation and small synthetic test fixtures.

## Sequence and reviewable increments

| Increment | Work | Dependency | Reviewable result |
|---|---|---|---|
| A | Freeze protocol, preserve baseline, promote sources, add year-aware readers | None | New source manifest; observation schema and parsing tests |
| B | Exact asset mappings and same-year stock audit | A | Eleven-group discrepancy report; unresolved mappings classified |
| C | Panels and historical evaluation | A and reviewed B boundaries | Frozen holdout metrics; failure analysis; no claimed totals prediction where totals were supplied |
| D | Generation matching and vehicle-usage assessment | A and reviewed B boundaries | Coverage and service-factor candidates; complete fallback ledger |
| E | Select qualified factors and run the current scenario | C and D | Before/after distributions; explicit promotion/retention decisions |
| F | Producer/consumer regression and report | E | Independently validated output, PDF, Markdown assessment and artifact manifest |

C and D can proceed independently once their boundaries are fixed. Changes are
kept on the isolated feature branch; use separate commits for each increment.
No external publication or communication is part of this package.

## Definition of done

- All eleven groups have a stock-comparison diagnosis, a historical evaluation
  result or explicit evidence limitation, and a service-weighting decision.
- Supported factors are exported; unsupported groups retain explicit proxies or
  equal-service assumptions with quantified sensitivities where possible.
- Every result can be reproduced from the new immutable evidence snapshot and
  a versioned campaign configuration. Held-out outcomes and promotion decisions
  are traceable; no failure disappears from the report.
- Baseline tests and appropriate new tests pass; all new profiles pass serialized
  source/stock/share checks and filtered/encrypted/cached runtime checks. Repeat
  the signed-demand consumer checks for affected primary groups.
- A report compares the baseline and candidate profiles and distinguishes numerical
  validity, source reconciliation, empirical accuracy and remaining assumptions.
- No acceptance criterion depends on obtaining more REMIND-team data or making
  every asset appear empirically supported.

## Evidence and implementation references

- [EIA-860 definitions and historical files](https://www.eia.gov/electricity/data/eia860/).
  The annual retired tab is not a complete historical retirement register.
- [EIA-923 reporting levels and files](https://www.eia.gov/electricity/data/eia923/).
  Generator-level output is available for a subset; plant/prime-mover totals are
  not automatically cohort-specific generation.
- [DfT vehicle licensing tables](https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-tables).
- [Existing sector mappings and limitations](remind-sector-expansion.md).
- [Current annualisation constraints](joint-stock-annualisation.md).
- [Existing serialized/runtime validation](stock-vintage-validation.md).
