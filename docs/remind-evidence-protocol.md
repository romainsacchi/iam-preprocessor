# REMIND evidence protocol: inputs, historical tests and service decisions

Status: proposed protocol for the planned
[evidence work package](remind-evidence-work-package.md). Freeze a versioned copy
before computing new evaluation scores. The numerical coverage cutoffs below
are declared engineering selection rules, not statistical confidence levels.

## 1. Verified source inventory and preservation

Existing archive root:

```text
/Users/romain/Library/Application Support/trails/stock-vintage-evidence/2026-10-10-pilots
```

The original REMIND source is
`iam-inputs/remind 3.5.2/REMIND_generic_SSP2-NPi2025.mif`, SHA-256
`b19b71690d672b5e5cc2e908eeb5486fe723103f6ab6c852cdffc45486feb6dd`.

| Source | SHA-256 verified during planning | Current location |
|---|---|---|
| `eia8602020.zip` | `ce519fd0b02c74b8c4231dc023bf07f922ae5f2a018fcaf88914502f61aa89ea` | `/private/tmp/stock-data-campaign/` |
| `eia8602021.zip` | `ac35e582335ed5f82c1177361d6e8e82cff083ae85a5ec668815d21e0aef3ee5` | `/private/tmp/stock-data-campaign/` |
| `eia8602022.zip` | `a6f6b00f480ccfb7436804f5cb9984f27c3e0c20cfcbe9b4ed057285b5a68980` | Existing archive, `public-sources/` |
| `f923_2022.zip` | `2f030b7da3802b9310ecd93ef98014890d3519e6d1db55e5a49173121e5e82e4` | Existing archive, `public-sources/` |
| `veh1111.ods` | `bc3529975f7fa9e12181b64397cb1e619ae78926130146b64f5c35b9e268d1cc` | Existing archive, `public-sources/` |

Archive a new snapshot with its own manifest before implementation relies on
files in `/private/tmp`. Verify copies against these pins. Referencing an older
immutable snapshot by hash is acceptable; overwriting it is not. Pin any newly
acquired mileage or generation source independently, including its release,
retrieval date, units and any revisions. The source manifest must not contain
cryptographic keys or credentials.

Observed layouts:

- EIA-860 generator workbooks are `3_1_Generator_Y2020.xlsx`,
  `3_1_Generator_Y2021.xlsx` and `3_1_Generator_Y2022.xlsx`. Discover and validate
  the year-specific member; do not substitute the 2022 workbook for older years.
  Preserve operable, retired/cancelled and proposed statuses separately. A
  cancelled proposal is not a physical retirement.
- EIA-923's relevant workbook is
  `EIA923_Schedules_2_3_4_5_M_12_2022_Final_Revision.xlsx`. The inspected sheets
  include `Page 4 Generator Data`, `Page 1 Generation and Fuel Data` and the
  published file layout. Headers are on row 6 in this pinned edition. Match
  fields with a validated layout adapter, not a universal row-number assumption.
- VEH1111 contains UK year-end rows for cars and HGVs in 2014–2025. First-use
  year and manufacture year are distinct concepts. ODS numeric values are counts
  expressed in thousands; preserve low counts and unknown first-use dates.

## 2. Canonical observation and audit records

Retain generator records before aggregating to cohorts. The minimum fields are:

| Fields | Meaning |
|---|---|
| `source_sha256`, `source_member`, `sheet`, `source_row` | Trace a value to the pinned source |
| `observation_year`, `observation_date`, `revision` | Timing and data edition |
| `plant_id`, `generator_id`, `raw_generator_id`, `unit_id` | Source identity, preserving original labels |
| `source_technology`, `prime_mover`, `fuel`, `chp`, `status`, `geography` | Selection and mapping evidence |
| `capacity`, `capacity_unit`, `capacity_basis` | Nameplate/seasonal capability, AC/DC/unknown |
| `cohort_year`, `cohort_date_kind`, `operating_month` | Entry proxy and partial-year information |
| `asset_id`, `mapping_version`, `selection_reason` | Reviewed classification or exclusion |

Vehicle records use geography, body type, fuel, observation year and first-use
cohort, with known counts, unknown counts and independently published totals.
They have no fabricated vehicle-level IDs. Keep petrol, diesel and BEV rows
separate before constructing the disjoint combined Liquids proxy.

A transition ledger references both source records and distinguishes confirmed
retirement, commissioning, status transition, capacity change, date revision,
category change, newly covered record and unexplained disappearance. The sum of
its disjoint changes must reconcile observed opening and closing capacity. Do
not reinterpret an uprate or revised date as a wholly new asset by default.

The IAM comparison table records native/interpolated status, source anchor years,
stock selector/unit and the precise observational selection. Record a missing
value as missing, not zero; zero denominators do not produce infinite ratios.
Record UK-to-EUR scale factors separately from like-for-like US errors.

## 3. Historical experimental design

The protocol evaluates three different questions. Keep their results separate.

| Experiment | Inputs allowed | Outcomes withheld | Valid claim |
|---|---|---|---|
| A: opening-cohort survival | Initial dated stock, predeclared survival prior; documented independent capacity/status information in separately labelled variants | Later opening-cohort survivors and their age distribution | How well the prior describes the evolution of stock already present |
| B: reconstruction conditional on known additions | Initial stock, prior and independently supported dated commissioning/addition observations | Later closing stock and cohort composition | Reconstruction accuracy conditional on those realized additions |
| C: composition conditional on total stock | Initial stock, prior and observed aggregate closing totals | Closing vintage shares and cohort quantities | Ability to recover composition when the total is supplied |

Experiment B is available only where gross additions can be supported independently
of the target closing cohort table. If commissioning records are recovered from
later EIA files, label the exercise retrospective and conditioned on those records;
audit short-lived entrants and coverage changes. Do not infer additions by
subtracting held-out survivors or defining every youngest closing cohort as sales.
If such identification fails, report B as unsupported and complete A/C.

For A, show two evaluations: the full selected opening stock with unresolved
outcomes reported explicitly, and the subset with comparable confirmed identities.
State the latter's coverage and selection bias. Do not renormalize a disappearing
fraction away before reporting the error. Survival is evaluated at cohort/age-bin
level; a probabilistic lifetime prior does not predict which named plant retires.

Freeze the current lifetime and additional-exit assumptions for the principal
runs. Tests of alternative priors are predeclared sensitivities. Estimating new
retirement laws from the same short holdout is outside this work package.

### Time split and leakage controls

- Power: 2020 initialization; 2021 for development diagnostics; 2022 withheld from
  new tuning after the protocol is frozen. The 2022 snapshot was already used in
  the existing pilot, so this is a retrospective holdout, not previously unseen
  evidence for the entire project.
- Vehicles: compatible 2014–2020 histories and 2021 for development; 2022 for the
  first frozen comparison; 2023–2025 for a second frozen comparison initialized
  in 2022. Score UK observations against UK reconstruction. Any EUR scenario
  comparison is separately labelled and does not validate the regional proxy.
- Store per-run lists of input files/columns and held-out columns. A test must fail
  if held-out cohort values enter initialization, factors, smoothing selection
  or retirement-parameter fitting.
- In C, only an aggregate held-out total is allowed as a model input; this is
  explicitly conditioning, and no total-stock prediction score is awarded.
- Scenario native anchors, lifetime priors, data-year availability and fixed
  category metadata are not observations of later historical cohort outcomes.
  Production-scenario constraint checks remain a separate report.

### Vehicle-specific interpretation

Apparent retention `N(c,t+1)/N(c,t)` can exceed one because older vehicles may
enter the observed fleet, return to licensing or be reclassified. Keep the raw
ratio, flag undefined denominators and retain the corresponding count changes.
Do not cap the ratio or label all losses physical scrappage. Unknown first-use
mass is retained in raw metrics and its proportional-allocation assumption is
reported separately. Separate the historic-vehicle tail in plots; do not delete
it to improve the lifetime model's score.

## 4. Metrics and assessment rules

Use common cohort support with explicit zeros only for confirmed absent cohorts.
Unknown or uncovered mass has its own category and coverage metric. Age-only
metrics use explicitly identified dated/comparable support and publish its mass
coverage. Unknown ages cannot be assigned an arbitrary age for W1 or quantiles;
unexplained disappearing mass remains visible in the full-population ledger.

Report for each asset, year and experiment:

1. Absolute stock error and relative stock error where the total is independently
   predicted and the observed denominator is positive.
2. Total variation of cohort shares: `0.5 * sum(abs(p_c - q_c))`.
3. One-dimensional age-distribution distance in years: sum the absolute differences
   between cumulative annual age distributions (equivalent to discrete W1).
4. Signed mean-age bias and errors in the median and 90th-percentile age.
5. Fixed five-year age-bin errors, plus age >=20 for vehicles and >=40 for power.
   Publish the full unbinned data; tail cutoffs are reporting conventions.
6. Amount and share of unexplained transitions, unknown dates and unobserved
   outcomes, including revisions and capacity changes.

Compare with the current model and simple ageing baseline on identical eligible
support. Show both capacity/stock-weighted summaries and individual asset/year
results; a good large-sector score must not hide a failed small sector. Sparse
samples receive descriptive errors without unsupported confidence intervals.

There is no universal numerical accuracy threshold that makes all sectors valid.
Classify the result as improvement, mixed result, no improvement or insufficient
evidence using the predeclared metrics, and record the reason. Any promoted
method must pass data/accounting checks and have a defensible advantage for its
intended use. Do not tune cutoffs retrospectively to obtain a desired label.

## 5. Power-service matching and calibration

### Evidence hierarchy

| Level | Permitted use | Label |
|---|---|---|
| Generator ID, same year and technology, reported generation | Aggregate directly by dated cohort | `generator_observed` |
| Plant/prime-mover/fuel output maps completely to one eligible cohort | Assign that output once to the cohort | `single_cohort_observed` |
| Plant output covers multiple cohorts with compatible membership | Allocate by explicit capacity/exposure rule; retain alternative allocations | `plant_allocated` |
| Output missing, category ambiguous or population incomplete | Explicit equal-service or documented prior factor | `assumed` |

Direct generator output takes precedence. Plant totals are reconciliation checks,
not additional generation. If allocating an unmatched plant residual, subtract
only comparable direct output once, verify complete membership and fail on an
unexplained negative residual. Do not allocate production from another technology,
fuel, CHP boundary or excluded generator to the selected cohort.

Ambiguous IDs are not matched by fuzzy names. Numeric padding may be normalized
only when the raw and normalized candidate sets establish a one-to-one mapping;
record every alias. Preserve valid reported zero generation. Preserve raw negative
net generation in a separate diagnostic because it cannot form a nonnegative
production-service weight. Missing, zero and negative values are distinct states.

### Temporal and capacity consistency

Generation is annual whereas the producer's default service composition describes
end-year serving stock. A unit retired during the year can generate electricity
without appearing in that closing stock. Keep this difference in the denominator
and reconciliation ledger; do not assign its output to surviving generators.

For commissioning-year units, use monthly generation and credible operating
months to assess exposure where possible. Full-year comparable units provide
the first calibration population. Uncertain partial-year observations receive
an explicit fallback; low first-year generation must not become a permanent
low-utilization factor for that cohort. Also check uprates, missing months,
status changes, net versus gross output and PV capacity basis.

Use actual calendar hours for raw historical-year physical checks (2020 is a
leap year). Preserve and state the producer's existing 365-day bound convention
for scenario service until a separate change is justified. Passing the physical
bound does not establish a correct age-utilization relation.

### Construction of factors

For an eligible cohort, form relative output per unit stock from comparable
capacity and generation. Normalize to the matched population's capacity-weighted
mean, with cohort-level coverage retained. Impute unmatched capacity only through
an explicit rule, such as the matched group mean, and preserve the full stock
composition when normalizing the completed factors.

At service year `t`, the producer applies:

```text
service_share(c,t) = stock(c,t) * relative_use(c,t)
                    / sum_c(stock(c,t) * relative_use(c,t))
```

Reported aggregate IAM service controls the total, not the relative-use evidence.
A 2022 output/capacity difference may reflect location, design, dispatch or weather
as well as age. Initial observed factors are cohort-specific cross-sectional
proxies. Future entrants require their own documented factor; data from one year
do not justify a fitted future utilization trend.

### Coverage rules for selecting a default

Proposed rules to freeze before inspecting the new match scores:

- Account for 100% of selected capacity as directly observed, single-cohort
  observed, allocated or assumed; report output reconciliation separately.
- For an evidence-weighted default, aim for at least 90% of selected capacity in
  the first two evidence levels, and at least 80% within each five-year cohort
  bin containing at least 5% of selected capacity. Count partial-year or incompatible
  calibration records as unsupported unless an explicit exposure treatment qualifies.
- If those thresholds fail, retain the current default and export the weighted
  result as a labelled sensitivity, with the missing coverage and reason.
- A fully matched but geographically or technologically narrow population remains
  a proxy. In particular, offshore's two generator records do not support broad
  empirical claims even if their matching coverage is 100%.
- Existing PV/CCGT observed factors undergo the same audit. Preserve their baseline
  for comparison; retain, replace or downgrade their evidence status explicitly.
- Every candidate must conserve shares and aggregate service, retain stock outputs,
  and respect the per-cohort physical bound after scenario scaling. Failing cases
  are recorded and excluded from default export; weights are not silently clipped.

These thresholds select defaults; they do not make missing data a blocker for
finishing the package. Single-year service factors can pass reconciliation and
coverage checks but cannot be described as validated predictions of future use.

## 6. Vehicle-usage assessment and fallbacks

Record source year, population, age definition, fuel/body categories, sample
weights, service measure, exposure denominator, suppression, imports and
missingness for every candidate usage source. MOT odometer differences require
compatible tests on the same vehicle, elapsed time, unit/reset checks and an
assessment of vehicles absent from the test population. Availability of licensing
counts alone does not supply any of these utilization quantities.

Priority is an official usable age/body/fuel mileage table. For passenger-km,
make occupancy assumptions explicit; for tonne-km, make payload and empty-running
assumptions explicit. Do not reuse car mileage as a heavy-truck service profile.
Do not describe a vignette based on vehicle-km as observed passenger- or tonne-km.

If no qualifying table is obtained, retain equal service as the default and run
predeclared utilization sensitivities using existing capabilities. At minimum,
compare no age decline with the already documented 3% exponential annual decline,
applying the initial-age factor as well as subsequent ageing. These are assumed
curves, not confidence bounds. Treat BEVs, liquid cars and HGVs separately.

If an actual non-exponential age schedule qualifies, specify annual-age lookup,
interpolation, youngest/oldest-age rules, new-entrant exposure and missing-age
policy before adding an opt-in configuration kind. Test movement along the age
curve as cohorts age. Keep existing configuration behavior and consumer output
contracts compatible.

## 7. Reproducibility, invariants and package outputs

Each candidate export records the evidence snapshot, protocol version, mapping
version, implementation hashes, chosen service method, coverage, imputation and
fallback. The historical report lists data supplied versus withheld for each
experiment. Preserve failed cases and old defaults as explicit comparisons.

Accounting checks include nonnegative finite stocks/shares, normalized shares
for positive-service cases, chronological validity, stock balance, unchanged
native IAM values, explicit source-inflow residuals, exact eligible generation
reconciliation and conserved inventory coefficients. Use scaled floating-point
tolerances consistent with existing tests; integer vehicle counts reconcile
exactly before modelling allocations.

Keep the current `Stock Vintage|v1|` contract. Run existing tests plus focused
new parser, matching, historical-evaluation and service-weight tests. For affected
exports repeat independent serialized checks, filtered/encrypted/cached profile
comparisons and signed-demand premise-to-TRAILS integration. Integration fixtures
remain synthetic inventories and cannot validate real production coefficients.

The new campaign writes a separate output directory with a Markdown assessment,
PDF and PNG figures, numeric plot tables, transitions and coverage ledgers, rejected
cases, validation JSON and artifact hashes. Preserve the earlier sector-expansion
artifacts. No source data, test encryption keys or private scenarios are committed.

## Primary-source definitions

- [EIA-860](https://www.eia.gov/electricity/data/eia860/): generator stock/status
  fields and the limits of the annual retired-generator list.
- [EIA-923](https://www.eia.gov/electricity/data/eia923/): generator versus plant/
  prime-mover generation reporting and historical files.
- [DfT vehicle licensing tables](https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-tables):
  VEH1111/VEH0520 catalogue. Exact years and layouts above were checked in the
  pinned local files, rather than inferred from the current download listing.
