# Joint annual additions and stock reconstruction

This optional `mode: joint` addresses steps in reconstructed vintage composition
caused by piecewise-linear interpolation of IAM stock. It uses the same observed
initial cohorts, flodym survival matrices and service-weighting contract as the
existing `stock` and `inflow` modes. Regional composition proxies remain explicit
accepted pilot assumptions. It does not smooth observed historical cohorts or
post-process the final histograms.

## Source semantics and constraints

- **Stocks/capacities:** original IAM anchor years are exact constraints.
  Intermediate stocks emerge from surviving initial cohorts and annual additions.
- **Sampled annual sales:** the reported years constrain annual entries at those
  years. Interpolated sales supply a weak reference trajectory, not extra data.
- **Reported period-average additions:** annual entries are constrained by the
  average over each explicit window. A 10 GW/year five-year observation therefore
  constrains 50 GW of additions, not 10 GW of additions in the reporting year.
  Ten-year windows constrain ten annual entries, with no assumed fixed step width.
- **Lifetimes:** unchanged flodym conditional survival; historical initial stocks
  are survivors, not historic sales. Future lifetimes retain their cohort indexing.
- **Additional exits:** `exit_policy: error` allows none. With `proportional`, the
  annual extra-exit fractions from the existing linear-stock reconstruction are
  fixed before fitting. They apply proportionally to naturally surviving cohorts.
  Their absolute quantities may change with the fitted stock. This deliberately
  conditions on the existing exit schedule; it does not jointly estimate retirement
  timing or silently add retirements to fit reported construction.

The resulting stock is linear in annual additions:

```text
K[t] = surviving_initial_stock[t] + sum_c(response[t,c] * additions[c])
```

`response` includes natural survival and any fixed proportional extra-exit
fractions. All additions and cohort stocks are nonnegative. Native source rows
and values remain unchanged. Newly introduced annual columns in original IAM
rows still follow the general linear interpolation convention; reconstructed
annual stocks and additions are explicitly in `Stock Vintage|v1|`. Consumers
requiring these reconstructed quantities must use that namespace. Different
sensitivity cases can have different intermediate annual stocks.

## Smoothing and incompatible observations

SciPy HiGHS first checks whether stock anchors and all source inflow constraints
are simultaneously feasible under the selected initialization, lifetime and exit
assumptions. If they are, all remain exact while the annual path is smoothed.
This feasibility statement is conditional on those assumptions, not a finding
that REMIND itself is internally inconsistent.

If the constraints conflict, `strict` raises an error. An explicitly selected
`penalized` policy retains exact stock anchors and balances additions' curvature
against discrepancies in source inflow rates. Every sampled-year or period-mean
discrepancy is reported, including period totals. No period is silently shortened
or relabelled, and zero source rates are not hidden behind relative percentages.

With all quantities divided by one common stock scale, the quadratic objective is:

```text
sum(second_difference(annual_additions)^2)
  + reference_weight * sum((annual_additions - reference_trajectory)^2)
  + inflow_weight * sum((reconstructed_reported_rates - source_rates)^2)
```

The final term is used only when inflow constraints are infeasible and `penalized`
is selected. Exact-feasible fits keep those constraints hard. Each reported rate
has one residual; a period mean uses the average of all entries in its actual
window. The objective does not give a ten-year window twice a five-year window's
weight simply because it contains more years.

The example sets `reference_weight: 0.01`, `inflow_weight: 10` and compares inflow
weights 1 and 100. These are documented regularization choices, not calibrated
statistical uncertainties. A separate minimum absolute rate discrepancy is
reported to distinguish unavoidable mismatch from the extra mismatch accepted
for smoothness. Minimizing only that absolute discrepancy can concentrate new
capacity into narrow spikes; it is a diagnostic, not the selected smooth fit.

SLSQP solves the convex quadratic fit. The code checks stock/inflow residuals,
nonnegativity and independent first-order stationarity/complementarity conditions.
It aborts on solver failure; a visually smooth plot does not count as validation.
Curvature need not improve relative to the old stock-only baseline when newly
enforcing observed sales samples introduces additional constraints.

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
    Exact stock anchors; smooth annual additions with explicit inflow reconciliation.
    Fixed proportional exit fractions from the linear-stock baseline.
```

All fields are required; unknown fields, nonpositive weights and booleans fail
validation. The `annualisation` block is rejected outside joint mode. Legacy
`stock` and `inflow` configurations continue to work unchanged.

## Horizon and interval boundaries

The internal solve includes the next stock anchor at/after the requested end
year and completes all intersecting addition-reporting windows. For the reviewed
2022–2050 power example, the final centered window runs through 2052. Its complete
total is fitted before exporting only the requested 2022–2050 profiles; the full
internal inflows are retained in the report for verification.

A reporting window crossing the initial stock date is rejected because its
historical additions are not supplied. Choose an earlier initial state or an
aligned reference year instead of assuming its missing part. Overlapping,
duplicate, uncovered and extrapolating windows are rejected. The generic tests
cover five-to-ten-year and irregular windows. The actual REMIND pilot still
stops at 2050; later native reporting mappings require a separate review.

## Diagnostics, reproduction and runtime

Each asset report includes exact-feasibility status, source stock constraints,
source inflow samples/windows and residuals, internal solve years/inflows,
fixed extra-exit fractions, objective weights, optimizer/KKT checks and original
versus fitted additions' curvature. `Stock Residual` in joint mode is the deviation
from the old linear interpolation; actual source-anchor errors are separately
labelled in `annualisation.stock_anchor_max_absolute_residual`.

```console
python examples/run_remind_stock_pilot.py --archive /path/to/archive \
  --output-dir /path/to/new-output --end-year 2050 --annualisation joint
python examples/validate_stock_output.py /path/to/new-output/*_report.json
python examples/plot_joint_annualisation.py /path/to/new-output/*_report.json
```

The pilot prepares 44 primary/sensitivity cases. Its preflight records optional
service-bound failures in `rejected-sensitivities.json` and excludes those invalid
profiles. Primary-case failures, solver failures and other data errors abort.
For the reviewed scenario the CCGT age-decay sensitivity fails the 8760-hour
per-capacity service limit in 2047, leaving 43 valid cases. The declared utilization
assumption is not clipped to conceal the failure.

`annualisation-comparison.pdf` contains actual annual stock/addition paths and
recomputed vintage distributions, with no cosmetic smoothing. Period observations
are drawn as horizontal windows, not mistaken for point samples. Runtime variables,
units, common-amortisation inventory coefficients and premise/TRAILS interfaces
are unchanged. Producer hashes and the paired consumer checks remain required.

Remaining modelling uncertainties include proxy initialization, lifetime and
utilization priors, historical cohort dates, the inherited early-exit schedule,
within-year service exposure and the weighting of incompatible inflow data.
