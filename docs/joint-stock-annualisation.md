# Fitting annual additions to reported stock

Use `mode: joint` to estimate annual additions when the IAM reports stock and
additions at intervals. This can avoid sudden jumps in the estimated build-year
mix when reported stock grows at different rates between reporting years. The
calculation uses the same starting ages, lifetime curves, and assumptions about
use as the other modes. It keeps the observed starting groups as supplied.

## How reported values are used

- The fitted stock matches the values in the input file for every reported year.
  Stock between those years comes from the starting assets that survive and the
  new assets added each year.
- An annual addition rate reported for a particular year applies to that year.
  Values filled in between reported years only guide the fit. The REMIND pilot
  uses this interpretation for `New Cap` and `Sales`.
- A reported average applies to its stated period. An average of 10 GW per year
  over five years means 50 GW in total. Each period uses its actual start and end year.
- Each asset keeps the lifetime assigned in its build year. The starting amounts
  represent assets already in use at the beginning of the run.
- `exit_policy: error` allows retirement from ageing alone. With `proportional`,
  the tool first uses a straight-line stock estimate to work out the share of
  surviving assets that retires early each year. The fit keeps those shares
  fixed, so the quantities retired may change as the estimated stock changes.

The resulting stock is linear in annual additions:

```text
K[t] = surviving_initial_stock[t] + sum_c(response[t,c] * additions[c])
```

`response[t,c]` is the share of additions made in year `c` that survive until
year `t`, including any fixed share retired early. Additions and stocks must
be nonnegative. The older CSV format fills gaps in the original rows along a
straight line and writes the fitted values in the `Stock Vintage|v1|` rows.
Changing assumptions can change estimated stock between reporting years.

## Smoothing and incompatible observations

The HiGHS solver in SciPy checks whether the stock and addition figures can both
be matched given the starting ages, lifetimes, and retirement assumptions. When
they can, the fit keeps both sets of reported figures exactly and estimates a
smooth series between them. This check applies to the assumptions used in the run.

If the figures cannot both be matched, `strict` stops the run. `penalized`
keeps reported stock values and balances a smooth series of annual additions
against differences from the reported addition rates. The report shows each
difference, including totals for reported periods and differences from zero rates.

The solver puts all quantities on the same scale, then minimises this sum.

```text
sum(second_difference(annual_additions)^2)
  + reference_weight * sum((annual_additions - reference_trajectory)^2)
  + inflow_weight * sum((reconstructed_reported_rates - source_rates)^2)
```

The final term applies when the data conflict and `penalized` is selected. Each
reported rate counts once, whether it gives one year or an average across
several years. A reported average is compared with the average of all estimated
values for that period.

The example sets `reference_weight: 0.01` and `inflow_weight: 10`. It also tests
addition weights of 1 and 100. These choices control the trade-off in the fit.
The report gives the smallest possible difference from the addition rates as
well, so readers can see how much extra difference the smooth fit accepts.
Fitting only that difference can produce short spikes in additions.

The code uses a fixed OSQP version to solve the fit. It rescales equations when
reported figures differ greatly in size and checks the results against the
original equations. For `penalized` only, SciPy SLSQP can take over if OSQP fails
its checks. That alternative must pass the same checks on values and equations,
plus a check that the result satisfies the mathematical conditions for a best
fit (the KKT conditions). The run stops if the required checks fail. The report
records the solver, outcome, scaling, remaining differences, and iteration count.
Matching observed sales can make the result less smooth than the stock-only fit.

## Configuration

Add this to an otherwise valid asset configuration:

```yaml
mode: joint
exit_policy: proportional
annualisation:
  inflow_constraints: penalized  # strict rejects any incompatible inflow constraints
  reference_weight: 0.01
  inflow_weight: 10
  provenance: >-
    Match stock in reported years and estimate smooth annual additions.
    Use fixed retirement shares from the straight-line stock estimate.
```

Supply all fields and use positive numbers for both weights. Use the
`annualisation` section only with `mode: joint`.

## Which years are used

The fit runs to the next reported stock year on or after the requested end year.
It also completes each addition period that overlaps the requested range. The
report includes the annual additions for every year used in the fit. In the
REMIND pilot, `New Cap` and `Sales` are treated as annual rates at the stated years.

If an addition period starts before the starting stock date, choose an earlier
starting stock date or start at a reporting boundary. Reporting periods must
cover the requested years without overlaps or gaps, and stay within the input
range. The tests include five-year, ten-year, and uneven periods. The REMIND
pilot covers years through 2050.

## Checking and repeating the example

For each asset, the report shows whether both input series could be matched,
the values and periods used, differences from reported values, the shares
retired early, the fit weights, and the solver checks. `Stock Residual` compares
the fit with the straight-line estimate. The difference from the reported stock
is recorded separately in `annualisation.stock_anchor_max_absolute_residual`.

```console
python examples/run_remind_stock_pilot.py --archive /path/to/archive \
  --output-dir /path/to/new-output --end-year 2050 --annualisation joint
python examples/validate_stock_output.py /path/to/new-output/*_report.json
python examples/plot_joint_annualisation.py /path/to/new-output/*_report.json
```

The pilot runs 44 main or alternative cases. It stops on errors in the main
cases. It records alternative cases with impossible levels of use in
`rejected-sensitivities.json` and leaves them out of the results. In 2047, one
gas power case exceeds 8760 hours of full-load operation, leaving 43 valid cases.

`annualisation-comparison.pdf` shows the calculated annual stock, additions,
and build-year shares. It draws each observation as a value for one year or an
average over its reported period. Inputs and outputs for `premise` and TRAILS
are checked using the existing test runs.

Uncertainty remains about starting ages, lifetimes, how much assets are used,
early retirement, what happens within a year, and how much weight to give
addition data when the reported figures disagree.
