# Stock-vintage reconstruction

This workflow estimates when the assets still in use in each scenario year were
built. A group of assets built in the same year is called a vintage or cohort.
The estimates are preliminary and depend on the available data and assumptions.
They help put construction impacts in the right years in a dynamic life-cycle
assessment.

## What the workflow needs

Each asset and region needs:

1. How much stock or capacity is installed.
2. How much is added or sold.
3. How long assets stay in use.
4. When the assets already in use were built, based on observations or a stated assumption.

An optional series gives total use, such as electricity generated. To split that
use by build year, specify how much older and newer assets are used.

Use the exact variable names and units in the scenario file. Each selected row
must be unique and have a nonnegative value for every reported year. Choose
years within the range covered by the file.

## How the code runs

```text
IAM table + YAML configuration
    |
    +-- vintage_inputs.py
    |     read the selected rows and fill in years between reported values
    |
    +-- vintage_reconstruction.py
    |     set the starting stock and calculate how it changes each year
    |
    +-- stock_model.py / flodym_stock.py / stock_annualisation.py
    |     calculate survival and estimate how many assets are added each year
    |
    +-- stock_vintages.py
    |     collect the results for each asset
    |
    +-- stock_package.py
          check and write the results
```

The corresponding public Python entry points are `read_iam_series`,
`annual_additions`, `reconstruct_asset`, `enrich_stock_vintages`, and
`prepare_stock_vintages`.

## How the stock changes each year

Let `stock[t,c]` be the amount of cohort `c` still present at the end of year
`t`. Let `survival[t,c]` be its survival fraction.

For an existing cohort:

```text
survivors[t,c] = stock[t-1,c] * survival[t,c] / survival[t-1,c]
```

Natural retirement counts the assets that reach the end of their useful life
under the chosen curve.

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

Assets seen at the start have already survived to that date. Their chances of
remaining in use are calculated from that date onward.

## Lifetime choices

The YAML sets the lifetime curve for each asset:

- `fixed` gives every unit the same retirement age.
- `weibull` uses a mean lifetime and a shape parameter.
- `quartic` uses a maximum lifetime. Survival reaches zero at that age.

A lifetime read from the IAM is attached to the cohort built in that year.
Any of these curves can be selected for any IAM, provided the parameter matches
the meaning of the input lifetime.

## How the workflow uses FLODyM

`flodym_stock.py` uses FLODyM to calculate how many assets survive at each age.
It passes the observed or assumed starting stock to `set_initial_stock`.

FLODyM's `InflowDrivenDSM` calculates what remains and what retires when annual
additions are given. Its `StockDrivenDSM` works out additions when installed
stock is given. If more assets need to retire early, `proportional` removes the
same share from each build-year group, and `oldest_first` starts with the oldest.
`remove_by_hazard` increases the retirement risks set by the lifetime curve
until the stock target is met. With this option, a group with zero natural
retirement risk can prevent a stock decline from being matched. Use `error` to
stop whenever the stock target requires early retirement.

In `stock_flow`, the code keeps both reported stock and additions. The
`remove_by_hazard` rule applies only to assets already in use before that year's
additions. In `joint`, SciPy and OSQP estimate annual additions and FLODyM uses
those estimates to track the build-year groups.

The `stocks` extra requires Git and installs the exact revision from
[FLODyM PR #261](https://github.com/pik-piam/flodym/pull/261). The processing
report records the installed version and, for a Git install, the commit.
The [FLODyM paper](https://doi.org/10.21105/joss.10105) describes the underlying
stock models.

## Annual input series

Between reported years, stock levels and annual addition rates follow a straight
line. The input file sets the earliest and latest year the tool can use.

Some models give an annual average for a period of several years. Choose
`reported_periods` and give the start and end year for each period. The periods
cannot overlap or leave gaps in the years you want to calculate.

Use the reporting convention documented by the modelling team. The difference
between two capacity points measures net change after retirements.

## Ways to use the stock and addition data

| Mode | What it keeps | What it estimates or checks |
| --- | --- | --- |
| `stock` | Installed stock path | Compare inferred additions with reported additions. |
| `inflow` | Addition path | Compare projected stock with reported stock. |
| `stock_flow` | Both annual series | Checks whether the figures can agree under the retirement rule. |
| `joint` | Stock values for the reported years | Fits annual additions to the available stock and addition data. |

In `joint` mode, `strict` stops if the stock and addition data cannot both be
matched. `penalized` matches the reported stock and shows where the fitted
additions differ from the reported additions.

If stock falls faster than natural retirement, choose a rule for early
retirement. `joint` mode supports `error` and `proportional`.

## Opening stock

You can supply the starting stock by build year in a CSV file.

```text
cohort,amount
2018,120
2019,180
2020,240
```

Optional columns are `service_factor` for how much the assets are used and
`evidence_basis` for the source of each group's estimate. Use whole years, one
row per year, and nonnegative amounts.

The YAML field `evidence_kind` records how well the data match the asset being
modelled. Use `composition_proxy` when borrowing the age breakdown from a
different place or technology. The output marks those rows as `observed_proxy`.

Without observations, use `equilibrium` or `warm_start` and give the oldest age
to include. With `schema_version: 2`, set `acknowledge_prior: true` to record
that the starting ages are assumed. The results show whether each build-year
group comes from an assumption, an observation, or a reported addition.

## Minimal configuration

Start with the [stock mapping template](../examples/stock-mapping.yaml). It
uses example names and assumptions. Enter the exact variable names and units
for your scenario. If lifetimes vary by build year and the scenario reports
them, give the variable name and unit `years` in `lifetime.source`.

Use the fields shown in the template. File paths are relative to the YAML file. A template
may omit the model, scenario and years. `stock-config` fills in the model and
scenario from the file and uses the available year range within 2005–2100. Set
the years in the template or on the command line to use a shorter horizon.

## Commands

List the input rows, fill in the model and scenario names in the YAML, and
check that the chosen rows are present.

```console
iam-preprocessor stock-inventory scenario.csv -o stock-inventory.csv
iam-preprocessor stock-config scenario.csv --mapping stock-mapping.yaml -o stocks.yaml
iam-preprocessor stock-inventory scenario.csv --config stocks.yaml -o mapped-inputs.csv
```

Calculate the build-year shares.

```console
iam-preprocessor stock-vintages scenario.csv --config stocks.yaml \
  -o output/stocks --package-only
```

Omit `--package-only` to also write the older CSV format with one column per
year. Use `--overwrite` to replace existing files.

## REMIND lifetime test case

REMIND energy-conversion assets are a test case for the quartic curve. For age
`a` and maximum lifetime `tau`, survival is `max(0, 1 - (a / tau)^4)` and the
mean lifetime is `4 * tau / 5`. Use `distribution: quartic` with
`initial_maximum` and either `maximum` or a `source` variable. Old configurations
with `distribution: remind` still select the same curve.

## Output

The output folder contains three files.

```text
datapackage.json
vintages.parquet
validation.json
```

Without `--package-only`, the tool also writes `vintages.csv.gz` and a CSV with
one column per year.

Each table row gives the model, scenario, region, asset, year in use, year built,
type of result, value, unit, and where the estimate came from. Results include
stock, shares of stock or use, additions, and retirements.

The run report records the assumptions, software versions, warnings, and
differences from the input figures. It also records file fingerprints so the
same inputs, settings, and code can be identified later. Keep it with the output
folder.

## Service shares and later use

Stock share is the fraction of installed stock built in a given year. Service
share is the fraction of annual use supplied by that group. Use can be assumed
equal, based on observations, or described by a curve that varies with age.

`premise` can use the shares to assign construction demand to build years.
TRAILS can then follow that demand through the supply chain and calculate the
impacts using the background data for those years.

## Main limitations

- When only a few years are reported, the estimated values between them depend on
  how those years are filled in.
- Starting ages often rely on an assumption or observations borrowed from another region.
- A single lifetime tells us little about when different assets retire unless
  we know how the model defines it.
- Installed stock and additions may reflect different accounting conventions.
- Without retirement dates, the choice of which assets retire early follows the
  selected rule.
- Total use gives little information about how use is shared between age groups.
- The end-year convention approximates within-year construction and operation.
- Results depend on the selected technology and regional boundaries.

`validation.json` and the run report show whether the numbers balance and where
the results depend on limited observations.

## Further detail

- [Joint annualisation](joint-stock-annualisation.md)
- [Validation strategy](stock-vintage-validation.md)
- [REMIND evidence results](remind-evidence-results.md)
- [Documentation map](README.md)
