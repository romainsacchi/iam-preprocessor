# Reconstructing stock vintages with flodym

This opt-in feature reconstructs annual cohort quantities from existing IAM
exports. It adds variables that premise can read at runtime without importing
flodym. The first application is **REMIND SSP2-NPi2025**, using the existing local
3.5.2-labelled MIF and already-curated 2022 observations. These are conditional
reconstructions, not recovery of REMIND's native vintages or a new calibration
of its exact run. No additional REMIND-team data is required for this route.

The production default is strict `stock_flow` mode. It preserves both the
linearly annualized stock path and additions, infers only explicitly authorized
additional retirements, never retires a same-year addition, and fails rather
than inventing a balancing flow. `error` is the default policy;
`proportional`, `oldest_first`, and `hazard_weighted` are explicit alternatives.

The optional [joint annualisation mode](joint-stock-annualisation.md) fits smooth
annual additions while retaining original stock anchors and reconciling sampled
sales or complete addition-reporting windows. It is the default in the reviewed
pilot script; the legacy modes described below remain available unchanged.

## Architecture and scope

```text
existing scenario + cohort observations + explicit YAML assumptions
  -> exact variable/unit checks and annualisation
  -> configured survival matrices + initialized cohort balance
  -> annual stock and service shares + diagnostics + hashed report
  -> enriched scenario CSV [optional filtering and encryption]
  -> premise IAMDataCollection runtime accessor
  -> explicit StockVintageExport inventory bindings -> TRAILS
```

`flodym==1.1.0` is pinned in the optional `stocks` extra and the development
environment as an independent comparison for the analytical fixed and Weibull
implementations. The exact REMIND energy-conversion survival law is implemented
directly because its
reported lifetime is a maximum, not a Weibull mean. The small accounting adapter
conditions observed initial survivors and handles explicitly selected additional
exits. It does not claim that these operations are native flodym initial-stock or
forced-retirement APIs. Analytical tests and comparisons with flodym's own
`InflowDrivenDSM` and `StockDrivenDSM` verify the equivalent fixed/Weibull cases.

The inspected flodym stock-driven solver can return negative inflows when a
stock decline is incompatible with the supplied survival law. Here this either
fails or is represented as proportional additional exits, never as silently
clipped negative inflow. No imports, exports, reactivation or physical disposal
are invented to close the balance.

The existing water-infrastructure pilot remains an external-data,
constant-stock case. The selected REMIND exports do not supply its forecast.
The interface is reusable for other assets, but their mappings, population
boundaries and lifetime assumptions need a separate review.

## Accounting and timing

Let `C[t,c]` be end-year stock in entry cohort `c`, and `S[t,c]` the configured
survival fraction. For surviving initial observations `C[t0,c]`, advance using
conditional survival:

```text
survivors[t,c] = C[t-1,c] * S[t,c] / S[t-1,c]
natural_exits[t] = sum(C[t-1,:]) - sum(survivors[t,:])
```

Initial observations are not multiplied by unconditional survival again. An
observed positive cohort with zero survival at initialization is rejected.
Changing lifetime inputs affect new cohorts; earlier cohorts retain the explicit
`initial_mean` or `initial_maximum` prior. Scenario time-dependent lifetimes are
indexed by entry year, not retroactively applied to every extant asset.

In stock mode, gross entries fill a positive gap to the target stock. A negative
gap either raises an error or removes the same fraction of surviving cohorts.
In inflow mode, supplied annual entries determine the stock and no additional
exits are inferred. In both cases:

```text
closing_stock = opening_stock + entries - natural_exits - additional_exits
```

The reference stock is an initial condition. Reference-year flow diagnostics
are undefined, not zero. Comparison series expose stock and inflow residuals.
`opening_IAM_stock + reported_inflow - closing_IAM_stock` is also reported;
negative values indicate infeasibility of those annualized closed-stock totals.
Feasible totals do not establish the survival law or allocation of exits to
cohorts. These two legacy modes do not jointly fit inconsistent stock and flow
targets. `mode: joint` supplies that separate constrained reconstruction, with
an explicit strict or penalized inflow policy and a constraint-by-constraint report.

The annual convention is end-year stock and end-year entry for survival. Service
weights use the serving end-year stock as an annual-service proxy:

```text
service_index[t,c] = C[t,c] * cohort_factor[c]
                     * exp(-annual_age_decay * elapsed_years)
                     * new_cohort_exposure_if_new
service_share[t,c] = service_index[t,c] / sum(service_index[t,:])
```

Observed cohort factors already describe reference-year use; their extra decay
starts at the reference year. Future entrants use `future_factor` (or one under
equal weighting). `new_cohort_exposure` defaults to one; an explicit half-year
sensitivity is supplied. This is not an exact integration of within-year births,
retirements or dispatch. Such histories remain unavailable. A declared upper
bound can reject physically impossible service per unit stock.

Multiplying all cohort indices by one factor to match total IAM service does
not change normalized shares. Exported cohort service quantities reconcile
that total but add no evidence about relative utilization. Zero-stock or
zero-service years have zero shares and cannot become runtime routing profiles.

Common amortisation is retained: multiply the original inventory coefficient
by normalized service shares to distribute its dates. Do not divide again by
lifetime, multiply again by replacements, infer manufacture from every regional
entry, or equate stock exits with physical disposal. First-use/commissioning
dates may be manufacturing-date proxies; those semantics belong in provenance.
Lifecycle/component bindings need their own existing reviewed rules.

## Input conventions

- One model and scenario per file; exact selected regions, variables and units.
- Stock and service levels: linear interpolation between existing anchors.
- REMIND `New Cap` and `Sales`: annual values at the reported years, with linear
  interpolation to missing annual years.
- Period-average additions: explicit inclusive annual windows for each reported
  anchor. The flat expansion preserves the declared window integral. Overlaps,
  gaps and absent anchors fail. No five-year rule is extended automatically into
  later ten-year or irregular reporting periods. This generic option is not used
  for REMIND `New Cap` under the variable definition adopted here.
- No extrapolation. Missing/nonfinite selected source values fail. Original
  anchor values are preserved; newly needed annual columns for original rows
  are filled linearly between adjacent source columns, preventing holes when
  premise reads the enriched annual grid. Existing missing values are not filled.
- Initial observation amounts become shares and are scaled to the selected IAM
  region's reference stock. This transfers composition; it does not establish
  that a UK or WECC observation represents the whole IAM region.
- An equilibrium fallback assumes stationary past inflow and a declared finite
  age support. It is a sensitivity/prior, not recovered historical composition.
- Schema-v2 equilibrium priors require `acknowledge_prior: true`. When the
  reference year follows the first IAM year, `warm_start` initializes the legacy
  prior at that first year and advances it with known IAM additions and stocks.
  Outputs separately label prior-dependent and IAM-addition cohorts.
- External evidence can be pinned through `evidence_manifest`. Each source entry
  records its URL, version, observation year, download date, SHA-256, licence,
  adapter version, and immutable local path. A mismatched checksum is fatal.

## Configuration example

The numbers below illustrate a prior, not recommended universal vehicle lives.
All unrecognized configuration fields are rejected.

```yaml
schema_version: 1
model: REMIND
scenario: SSP2-NPi2025
reference_year: 2022
end_year: 2050
assets:
  - id: passenger-bev
    region: EUR
    mode: stock
    exit_policy: proportional
    stock:
      variable: Stock|Transport|Pass|Road|LDV|Four Wheelers|BEV
      unit: million veh
    inflow:
      variable: Sales|Transport|Pass|Road|LDV|Four Wheelers|BEV
      unit: million veh
    service:
      variable: ES|Transport|Pass|Road|LDV|Four Wheelers|BEV
      unit: billion pkm/yr
    inflow_timing:
      kind: sampled_annual
      provenance: Sampled annual sales; linear interpolation assumed.
    lifetime:
      distribution: weibull
      mean: 16
      initial_mean: 16
      shape: 3
      interpretation: Explicit mean-service-life prior, not native EDGE survival.
      provenance: Illustrative prior with shorter/longer-life sensitivities.
    initial:
      kind: observed_shares
      file: passenger-bev-initial.csv
      provenance: Curated UK first-use composition used as an EUR proxy.
    service_weighting:
      kind: equal
      annual_age_decay: 0
      new_cohort_exposure: 1
      provenance: Equal service per vehicle; end-year-stock service proxy.
```

The observation CSV has `cohort,amount` and, when using `observed_factors`, a
`service_factor` column. Cohorts must be unique integer years no later than the
reference year; amounts and factors must be finite and nonnegative. File paths
are resolved relative to the YAML file. Public example code creates these local
CSVs from the existing private evidence archive; observations are not bundled.

For a Weibull IAM mean, replace `mean` with
`source: {variable: ..., unit: years}`; `initial_mean` remains explicit. A
Weibull mean is converted to scale using `mean / Gamma(1 + 1/shape)`. Use
`distribution: fixed` without `shape` for a fixed retirement age.

REMIND energy-conversion `Tech|...|Lifetime` variables instead report maximum
lifetime `tau`. Configure them with `distribution: remind`, an explicit
`initial_maximum`, and the IAM `source`; do not supply `mean` or `shape`. Their
survival is `max(0, 1 - (age/tau)^4)`, their mean lifetime is `4*tau/5`, and
capacity is zero at and after `tau`. This depreciation represents dismantlement,
not declining conversion efficiency. These semantics come from *Technical note:
Lifetimes in REMIND* (2026-03-23) and are not automatically applied to transport
`serviceLife` parameters.

For REMIND power additions and vehicle sales, use
`inflow_timing.kind: sampled_annual`. Values between source years are linearly
interpolated. `reported_periods` remains available only for other inputs whose
metadata explicitly defines period-average rates.

Generate a starting configuration for separate REMIND regions with:

```console
iam-preprocessor remind-stock-config scenario.mif -o stocks.yaml \
  --region DEU --region FRA --region UKI
```

Without `--region`, the builder emits every nonaggregate region found in the
scenario. It maps exact leaf power technologies and the available transport
classes, skipping asset families absent from the export. The opening composition
is an explicitly labelled equilibrium prior because the scenario does not report
the initial vintage distribution.

For transport, the builder uses the disclosed `serviceLife` values as fixed
retirement ages: 20 years for four-wheel LDVs, 15 for two-wheel LDVs, buses,
light trucks and heavy trucks, and 8 for three-wheel LDVs. This is a transparent
fallback, not a claim that REMIND disclosed a vehicle survival distribution.
The supplied 0.10/0.05 interest rates are financial inputs and are not used as
physical retirement parameters. Two- and three-wheel mappings are skipped for
the inspected EU21 MIF because it contains no matching `Stock`/`Sales` rows.

For schema-v2 equilibrium initialization use `kind: equilibrium`, `maximum_age`
(1–150), `acknowledge_prior: true` and provenance, without `file`. For observed service factors use
`kind: observed_factors`, `future_factor`, `annual_age_decay` and provenance.
An optional `maximum_service_per_stock` uses the configured service-unit per
stock-unit ratio; `0.031536` EJ/yr per GW represents 8760 full-load hours.

## Variable contract, version 1

Every new variable starts `Stock Vintage|v1|<asset-id>|`. Regions use the original
IAM dimension; annual columns denote service/stock years, while cohort years
remain in variable labels and can predate premise's 2005 scenario-year floor.

| Suffix | Unit / meaning |
| --- | --- |
| `Coverage` | `1`; exactly one within the declared annual coverage |
| `Stock` | Original stock unit; end-year total |
| `Stock|Vintage|YYYY` | Original stock unit; surviving cohort quantity |
| `Stock Share|Vintage|YYYY` | `1`; cohort quantity divided by total stock |
| `Service Share|Vintage|YYYY` | `1`; assumed share of annual service |
| `Service`, `Service|Vintage|YYYY` | Optional original service unit; total and allocated service |
| `Inflow`, `Natural Exit`, `Additional Exit` | Stock unit per year; undefined in reference year |
| `Stock Residual` | Reconstructed minus IAM-interpolated stock |
| `Inflow Residual` | Reconstructed minus reported/annualized inflow |
| `Implied Exit From IAM Totals` | Diagnostic closed-stock exit implied by both input series |
| `Balance Residual` | Opening plus entries minus exits minus closing stock |

Future and zero-weight cohorts are written explicitly as zero within coverage.
Outside coverage values are missing, not zero or extrapolated. Exported shares
are validated; the consumer never normalizes malformed shares. No overlapping
parent/technology aggregates are inferred. Asset IDs and regions must be unique.

## Canonical sidecar contract, version 2

The canonical output is `<scenario>_stock_vintages_v2/`, containing:

```text
datapackage.json
vintages.parquet
vintages.csv.gz
validation.json
```

The sparse long table uses `model, scenario, region, asset, year, cohort_year,
metric, value, unit, evidence_basis`. Its unique key is the first seven fields.
Metrics are limited to `stock`, `stock_share`, `service_share`, `service`,
`addition`, `retirement_natural`, `retirement_additional`, and
`legacy_unallocated`. Only the last may have a null cohort. Additions use their
entry year and no retirement may target that cohort in the same year.

`validation.json` reports numerical residuals, source precision, structural
consistency, evidence coverage, and prior dependence separately with
machine-readable pass/warning/fail statuses. Aggregate totals remain in that
summary rather than being mixed with cohort rows. Parquet is canonical; the
compressed CSV is an inspection copy. Package creation is finalized atomically
and every resource has a SHA-256 in `datapackage.json`.

## CLI, reports and runtime consumption

```console
python -m pip install -e '.[stocks]'
iam-preprocessor stock-vintages scenario.mif --config stocks.yaml -o output/stocks \
  --filter-output --encrypt-to output/encrypted --key-file local-test.key
```

Leave out the final three options to preserve every original row and write
plaintext only. CSV/MIF and Excel are accepted. Run any existing model-specific
transformations **before enrichment**, preserving the stock/capacity rows with
their `--no-filter` option. The generic filtering/encryption commands run after
enrichment do not update its report; use the enrichment command's integrated
options to keep hashes bound to the delivered file.

The JSON report records input/output hashes, observation/configuration hashes,
implementation-file hashes, library versions, complete assumptions and residuals.
It can be renamed along with the scenario; it is bound to bytes, not filenames.
Scenario files should be placed under a filename accepted by premise, for
example `remind_SSP2-NPi2025.csv`. Renaming does not change the recorded hash.
Keep all generated IAM-derived outputs and reports local under source rights.

The paired premise branch provides:

```python
record = iam_data.stock_vintage_weights("passenger-bev", "EUR", 2030)
profile = iam_data.stock_vintage_profile(
    asset_id="passenger-bev", region="EUR", years=range(2022, 2051),
    report_path="stock-report.json", asset_unit="kilogram", service_unit="kilometer",
)
```

`record` contains calendar `event_years` and normalized `weights`; request
`basis="stock"` explicitly for stock shares. The profile factory verifies the
report hash against the actual source file and checks scenario context. It
produces a profile for the existing `StockVintageExport` contract. Callers must
still provide reviewed exact caller/supplier bindings and inventory context.
No supplier-name matching, geographic fallback, coefficient changes or default
promotion occurs. TRAILS still requires its explicit `stock_vintage=True` flag.

## Sources

- [flodym repository and relationship to ODYM](https://github.com/pik-piam/flodym)
- [flodym stock/lifetime API](https://flodym.readthedocs.io/en/latest/api.stocks.html)
- [flodym annual and irregular timestep conventions](https://flodym.readthedocs.io/en/latest/howto6.html)

The exact installed 1.1.0 code and the local pinned REMIND/reporting-code evidence
were inspected. Current online documentation may describe a later release.
Exact REMIND run/reporter identity remains unresolved; the directory label alone
does not prove it. See the validation document for supported and deferred claims.

## Historical evidence and annual-age service profiles

The implemented campaign, empirical limitations and opt-in `age_profile` CSV
contract are documented in [remind-evidence-results.md](remind-evidence-results.md).
Only offshore wind qualifies for a new default in the current pilot. Other
usage candidates remain sensitivities; all stock distributions and production
coefficient totals are unchanged.
