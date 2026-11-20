# Stock-vintage reconstruction

This workflow estimates which construction-year cohorts make up an IAM stock in
each year. It is intended for dynamic life-cycle assessment, where the timing of
asset construction matters.

The method is preliminary. It reconstructs a plausible cohort history from the
available IAM variables and declared assumptions. It does not recover hidden
vintages from the IAM.

## What the workflow needs

Each asset and region needs:

1. installed stock or capacity;
2. additions or sales;
3. a lifetime or survival assumption; and
4. an opening stock composition or an acknowledged prior.

An optional service series can be used to express service by cohort. The total
service series does not reveal how use is divided between old and new assets, so
relative service weights remain a separate assumption.

Variable names and units are matched exactly. Missing values, duplicate matches,
negative quantities, and extrapolation beyond the IAM horizon are rejected.

## From IAM rows to vintage shares

The production path is deliberately divided into small tasks:

```text
IAM table + YAML configuration
    |
    +-- vintage_inputs.py
    |     select exact rows and produce annual input series
    |
    +-- vintage_reconstruction.py
    |     build the opening stock, apply survival, reconcile annual flows
    |
    +-- stock_model.py / flodym_stock.py / stock_annualisation.py
    |     calculate survival, fit annual additions, and project cohorts
    |
    +-- stock_vintages.py
    |     process every asset and assemble output
    |
    +-- stock_package.py
          validate and write the data package
```

The corresponding public Python entry points are `read_iam_series`,
`annual_additions`, `reconstruct_asset`, `enrich_stock_vintages`, and
`prepare_stock_vintages`.

## Cohort accounting

Let `stock[t,c]` be the amount of cohort `c` still present at the end of year
`t`. Let `survival[t,c]` be its survival fraction.

For an existing cohort:

```text
survivors[t,c] = stock[t-1,c] * survival[t,c] / survival[t-1,c]
```

Natural retirement is the loss caused by survival:

```text
natural retirement[t]
    = sum(stock[t-1,:]) - sum(survivors[t,:])
```

The annual stock balance is:

```text
closing stock
    = opening stock + additions - natural retirement - additional retirement
```

New additions form a new cohort in their entry year. They are placed at the end
of that year and cannot retire in the same year.

Observed opening cohorts are quantities known to have survived to the opening
year. They are advanced using conditional survival and are not subjected to past
survival a second time.

## Lifetime choices

The configuration supports three survival descriptions:

- `fixed`: all units retire at the declared age;
- `weibull`: a distribution defined by mean lifetime and shape;
- `remind`: the REMIND capacity law based on a reported maximum lifetime.

For the REMIND law, survival at age `a` with maximum lifetime `tau` is:

```text
survival(a) = max(0, 1 - (a / tau)^4)
```

Its mean lifetime is `4 * tau / 5`. A lifetime read from the IAM is attached to the
cohort built in that year. It is not applied retroactively to older cohorts.

## How the workflow uses FLODyM

`flodym_stock.py` uses FLODyM's `FixedLifetime` and `WeibullLifetime` for
survival and adds `RemindLifetime` for REMIND's maximum-lifetime curve. The
workflow passes the observed or assumed opening cohorts through `set_initial_stock`.

`InflowDrivenDSM` projects stock and retirements by cohort from annual additions,
including additions fitted in `joint` mode. With `StockDrivenDSM`, `proportional`
uses FLODyM's `remove_flat` rule and `oldest_first` uses `remove_oldest`. The
`error` policy rejects declines that require early retirement. With
`remove_by_hazard`, FLODyM raises the underlying retirement hazards until the
stock target is met. A zero natural hazard can make a stock target infeasible
under this rule, for example with a fixed lifetime.

In `stock_flow`, the IAM code reconciles both stock and additions. For
`remove_by_hazard`, it sets aside the current year's reported additions and lets
FLODyM retire the older cohorts. In `joint`,
the existing IAM stock calculation supplies the reference retirement fractions.
SciPy and OSQP fit annual additions, and FLODyM projects the fitted additions
using those fractions.

The `stocks` extra requires Git and installs the exact revision from
[FLODyM PR #261](https://github.com/pik-piam/flodym/pull/261). The processing
report records the installed version and, for a Git install, the commit.
The [FLODyM paper](https://doi.org/10.21105/joss.10105) describes the underlying
stock models.

## Annual input series

Stock levels and sampled annual additions are linearly interpolated between IAM
years. No extrapolation is allowed.

Some models may report an average annual addition for a complete multi-year
window. Such data use `reported_periods`, with explicit start and end years.
Windows must be complete, non-overlapping, and cover every requested year.

For IMAGE or MESSAGE, use the timing interpretation documented by the modelling
team. A difference between two capacity points is a net change, not gross
additions, because retirements are mixed into the difference.

## Reconstruction modes

| Mode | Main evidence preserved | Typical use |
| --- | --- | --- |
| `stock` | Installed stock path | Compare inferred additions with reported additions. |
| `inflow` | Addition path | Compare projected stock with reported stock. |
| `stock_flow` | Both annual paths exactly | Inputs are already mutually consistent. |
| `joint` | Original stock anchors; additions fitted under declared constraints | Sparse or mildly conflicting IAM series. |

`joint` mode fits annual additions over complete reporting windows. The report
records every discrepancy from a source addition constraint. A strict policy
stops on a conflict; a penalized policy retains stock anchors and reports the
adjustment.

When stock falls faster than natural retirement, an explicit additional-retirement
policy is needed. Available policies include proportional, oldest-first, and
FLODyM's `remove_by_hazard`. Joint mode supports `error` and `proportional`.
These policies describe assumptions about when assets leave the stock.

## Opening stock

An opening composition can come from a CSV with:

```text
cohort,amount
2018,120
2019,180
2020,240
```

The optional `service_factor` column weights service by cohort. Cohorts must be
unique integer years and amounts must be finite and non-negative.

When observations are unavailable, `equilibrium` or `warm_start` constructs an
opening prior over a declared maximum age. Schema-v2 configurations require
`acknowledge_prior: true`. Output and validation keep prior-based cohorts
separate from observed and IAM-addition cohorts.

## Minimal configuration

The values below show the format and are not recommended universal assumptions.

```yaml
schema_version: 1
model: REMIND
scenario: example
reference_year: 2022
end_year: 2050

assets:
  - id: passenger-bev
    region: EUR
    mode: joint
    exit_policy: proportional

    stock:
      variable: Stock|Transport|Pass|Road|LDV|Four Wheelers|BEV
      unit: million veh
    inflow:
      variable: Sales|Transport|Pass|Road|LDV|Four Wheelers|BEV
      unit: million veh

    inflow_timing:
      kind: sampled_annual
      provenance: Annual sales sampled at IAM output years.

    lifetime:
      distribution: weibull
      mean: 16
      initial_mean: 16
      shape: 3
      interpretation: Mean service-life assumption.
      provenance: Replace with reviewed evidence.

    initial:
      kind: equilibrium
      maximum_age: 30
      acknowledge_prior: true
      provenance: Opening composition is unavailable.

    service_weighting:
      kind: equal
      annual_age_decay: 0
      new_cohort_exposure: 1
      provenance: Equal annual service per surviving vehicle.
```

All unknown fields are rejected. Paths in the YAML file are resolved relative to
that file.

## Commands

For REMIND, inspect coverage before building a configuration:

```console
iam-preprocessor remind-stock-inventory scenario.mif -o stock-inventory.csv \
  --region DEU --region FRA --region UKI

iam-preprocessor remind-stock-config scenario.mif -o stocks.yaml \
  --region DEU --region FRA --region UKI --reconciliation joint
```

Run the reconstruction:

```console
iam-preprocessor stock-vintages scenario.mif --config stocks.yaml \
  -o output/stocks --package-only
```

Remove `--package-only` when the wide schema-v1 compatibility table is also
needed. Existing files are protected unless `--overwrite` is supplied.

## Output

The canonical sidecar directory contains:

```text
datapackage.json
vintages.parquet
validation.json
```

A non-package-only run also writes `vintages.csv.gz` and an IAM-style wide CSV.

The long table contains model, scenario, region, asset, service year, cohort year,
metric, value, unit, and evidence basis. Metrics include stock, stock share,
service share, additions, and natural or additional retirement.

The processing report records source and configuration hashes, implementation
hashes, library versions, assumptions, residuals, and warnings. Keep it with the
data package.

## Service shares and later use

Stock share is the fraction of installed stock in a cohort. Service share is the
assumed fraction of annual use delivered by that cohort. Equal use, observed
factors, age decay, and annual age profiles are supported.

`premise` reads these shares and associates construction demand with calendar
years. TRAILS propagates that time-distributed demand through the life-cycle
system. Inventory coefficients and total construction demand remain unchanged;
the workflow changes their timing.

## Main limitations

- IAM output years may be sparse, so annual values depend on interpolation or a
  fitted path.
- Opening stock composition is often a prior or a geographic proxy.
- A lifetime parameter does not identify a full retirement distribution unless
  its meaning is documented.
- Installed stock and additions may reflect different accounting conventions.
- Additional retirement allocation is assumed when source data do not identify it.
- Total service does not determine relative utilization by cohort.
- The end-year convention approximates within-year construction and operation.
- Results depend on the selected technology and regional boundaries.

Use `validation.json` and the processing report to distinguish numerical
consistency from empirical evidence quality.

## Further detail

- [Joint annualisation](joint-stock-annualisation.md)
- [Validation strategy](stock-vintage-validation.md)
- [REMIND evidence results](remind-evidence-results.md)
- [Documentation map](README.md)
