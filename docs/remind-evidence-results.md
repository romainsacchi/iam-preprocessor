# REMIND evidence work package: implementation and findings

Implemented on `feat/stock-evidence-validation`, from the frozen plan at
`4eda2aa`. This completes priorities 1–3 for the eleven existing asset groups
in SSP2-NPi2025. The earlier sector-expansion output remains the comparison
baseline; no lifetime parameters were fitted to the holdouts.

The implementation separates numerical validity, observation comparability and
empirical prediction. Passing the stock and service accounting checks does not
make the retirement priors or future utilization empirically validated.

## Results and decisions

| Group | 2020→2022 age W1: prior / no retirement (years) | Observed generation capacity coverage | Default decision |
|---|---:|---:|---|
| Passenger BEV | 0.044 / 0.043 | No eligible age-specific service evidence | Equal service; assumed age sensitivity |
| Heavy trucks | 1.418 / 1.306 | Mileage only; payload not identified | Equal service; NAEI and assumed age sensitivities |
| Passenger Liquids | 0.543 / 1.134 | Mileage only; occupancy not identified | Equal service; petrol/diesel usage sensitivities on the combined fleet |
| PV | 0.029 / 0.014 | 77.0% | Retain WECC default; national generation-factor sensitivity |
| CCGT | 0.884 / 0.051 | 80.5% | Retain WECC default; national generation-factor sensitivity |
| Onshore wind | 0.254 / 0.043 | 85.7% | Equal service; generation sensitivity |
| Offshore wind | 0.028 / 0.000 | 100.0% | Promote generation weighting; preserve previous default as a comparison |
| Nuclear | 1.590 / 0.115 | 30.0% | Equal service; generation sensitivity |
| Gas turbine | 1.823 / 0.403 | 55.1% | Equal service; generation sensitivity |
| Geothermal | 4.970 / 0.366 | 47.3% | Equal service; reject generation candidate on physical grounds |
| CSP | 1.024 / 1.326 | 45.9% | Equal service; generation sensitivity |

W1 measures the distance between annual-age distributions. These are experiment C
results: observed aggregate stocks were supplied, while later cohort composition
was withheld. Total-stock prediction errors are deliberately absent. The power
holdout is retrospective: 2022 observations already supported the earlier pilot,
but did not tune this work package. The separate 2022-initialized vehicle test
scores 2023–2025 observations without retuning the priors.

For that separate 2025 vehicle endpoint, W1 is 0.040 versus 0.057 years for BEV,
1.226 versus 2.859 for trucks, and 0.893 versus 1.643 for Liquids (prior versus
no retirement). The short power panel generally favors no retirement. That is
an empirical limitation of the current lifetime priors, not evidence that assets
should never retire. Existing lifetime sensitivities remain necessary.

## Priority 1: stock comparability

`stock_history.py` reads EIA-860 2020–2022 with plant/generator identities,
operating and retirement dates, technology/fuel/CHP/status, capacity ratings,
source row/sheet and hashes. It preserves missing quantities and does not treat
cancelled projects with missing capacities as measured zero-capacity assets.
The UK reader retains 2014–2025 first-use cohorts and unknown ages separately.

The versioned `data/remind_stock_assets.yaml` registry declares all eleven
crosswalks, units and limitations. Source ledgers test status, CHP, geographic
and nameplate/seasonal-rating alternatives. National power observations and UK
vehicles are kept in their original populations for historical evaluation.

Key diagnoses:

- Offshore wind: IAM/observed capacity is 1.077 at the native 2020 anchor but
  18.005 in interpolated 2022. Timing explains much of the apparent discrepancy;
  this does not establish the correctness of the future scenario trajectory.
  The initial source still has only two operating generator records.
- Gas turbines: the ratio remains about 0.35 at the 2020 anchor and 0.34 in
  2022. The native technology/CHP crosswalk is unresolved.
- PV: distributed-generation coverage and AC/DC rating boundaries are unresolved.
  The national audit does not replace the earlier selected WECC stock cohorts.
- CCGT: component operating dates need not represent whole-block construction;
  CHP/technology boundaries remain unresolved. No components are counted twice.
- CSP: 1.088 at the native anchor versus 1.609 in interpolated 2022.
- Nuclear, onshore wind and geothermal: relatively close same-year national
  totals do not validate cohort retirement or repowering behavior.
- Vehicles: UK versus EUR totals are not like-for-like stock errors. HGV is
  broader than the native 40t-truck category; hybrids and first-use/manufacture
  date differences remain explicit.

## Priority 2: historical evaluation

`stock_validation.py` implements three separate experiment contracts:

- **A:** opening-cohort conditional survival. Power metrics use confirmed
  operating retention in opening-capacity units; unresolved identity, category
  and date changes are excluded with a coverage ledger. Vehicle results measure
  net licensed cohort retention, which also reflects trade and reactivation.
- **B:** independently observed additions. The model interface is tested, but
  this campaign reports the experiment as unsupported. Closing-stock youngest
  cohorts and newly appearing EIA records are not silently converted to sales.
- **C:** composition conditional on observed aggregate dated stocks. Prediction
  receives only opening cohorts, priors and aggregate totals. Scoring receives
  the withheld later composition afterwards. Conditioned totals receive no
  prediction credit.

The transition ledger reconciles continuing units, capacity changes, reported
retirements, status/boundary changes, revised cohort dates, newly covered old
assets, dated new entries and unresolved disappearances. It does not equate
absence from a later survey with scrappage.

Outputs include annual-age TV and W1, mean/median/p90 bias, five-year-bin TV,
tail-share error, unknown-age coverage and appropriate stock errors. The
no-retirement and equilibrium-initialization benchmarks use the same declared
drivers. All failures remain visible; no retirement law is fitted after scoring.

## Priority 3: service weighting

`stock_service.py` matches EIA-923 generator output by plant/generator identity.
Numeric zero-padding aliases require a unique one-to-one mapping. Conflicting
generator rows and ambiguous plant/fuel totals are retained as unresolved.
Missing values, measured zeros and negative net output remain different states.

Direct generator output and complete single-cohort plant residuals qualify as
observed. Multi-cohort residual capacity allocations do not. Coverage includes
new/changed units in its denominator while excluding their partial-year output
from the measured full-year factor calibration. Promotion requires at least
90% observed capacity overall and 80% within each five-year age bin containing
at least 5% of the stock. Allocation, imputation and unassigned plant output are
reported separately. These are one-year cross-sectional factors, not causal
age-degradation laws; future entrant factors remain explicitly equal to one.

Only offshore wind clears coverage and the scenario-wide physical check. Six
other power candidates are exported as labelled sensitivities. Geothermal fails
at 2022/cohort 1988: 0.036454265 EJ/GW/year versus the 0.031536 bound. The candidate
is rejected rather than clipped. PV/CCGT national factors remain geographic
proxies on the unchanged earlier cohort quantities.

The NAEI report supplies historical relative mileage curves in Tables 5-2 and
5-3. Its 2019 New Fleet petrol/diesel curves and HGV curve are optional
sensitivities. They do not establish future passenger-km or tonne-km by age.
Constant occupancy/payload and stationarity are explicit assumptions; factors
beyond age 24 hold the last reported value. No suitable BEV curve was identified.
All vehicle defaults remain equal service. Three additional assumed absolute-age
3% decay cases provide a common comparison. See the [NAEI report](https://naei.energysecurity.gov.uk/sites/default/files/2025-03/4_NAEI_Improvement_Report_Road_Transport_Fleet_Turnover_Model_Development.pdf).

### Opt-in annual-age profiles

```yaml
service_weighting:
  kind: age_profile
  annual_age_decay: 0
  age_profile_file: vehicle-usage.csv
  tail_policy: hold_last
  provenance: Historical mileage sensitivity; constant occupancy by age assumed.
```

The CSV has exactly `age,factor` columns, consecutive integer ages starting at
zero, and finite nonnegative factors with positive support. Each annual service
calculation uses `service_year - cohort_year`, including initial observed
cohorts. The final factor is held beyond the last age. Additional exponential
decay is prohibited for this kind to avoid hidden double ageing. New-cohort
exposure remains explicit. Existing `equal` and `observed_factors` configurations
retain their behavior. The curve checksum is included in the processing report.

This changes the distribution of the existing production coefficient over
service-producing cohorts. It changes neither the stock reconstruction nor the
total inventory production coefficient. Consumer namespace `Stock Vintage|v1|`
and common amortisation remain unchanged.

## Verification

- 78 producer tests pass, including year-aware source schemas, missing values,
  ambiguous generation, coverage gates, retention/conditioning contracts,
  evolving annual-age profiles, physical bounds and coefficient invariants.
- Ruff, formatting and Sphinx documentation checks pass.
- 106 accepted cases, 3,074 annual profiles and all 1,545,099 original IAM anchor
  values independently checked. All 81,321 original source rows are retained.
- Existing stock distributions, flows and aggregate service are unchanged
  against the preserved 93-case baseline.
- All 3,074 profiles agree for plain and encrypted runtime reads; 106 cached
  profiles agree for each variant.
- 176 signed-demand checks pass through premise → TRAILS: 88 for constant and
  88 for varying synthetic backgrounds. They test propagation and conserved
  coefficients, not real inventory representativeness.

No premise or TRAILS runtime changes were required. Paired consumer revisions:
`premise` `8a8376155b316745734f29ae01c4e656424c38d2`;
`trails` `ad961ef7d8a2925da3da48ce98cf7515f9f098c7`.

## Reproduce and review

Raw observations, private scenarios and generated outputs remain outside Git.
The immutable historical snapshot is
`/Users/romain/Library/Application Support/trails/stock-vintage-evidence/2026-10-10-validation`;
its manifest checksum is
`18efb92c24a92a46629f48be0484d58e1dac1e07ca2e1b02b11f6f8651e1f0e1`.
A separate `2026-10-10-validation-supplemental` snapshot pins the NAEI PDF without
mutating the frozen historical protocol.

From this checkout, with `iam-preprocessor[stocks]`, openpyxl, matplotlib,
pytest and Poppler's `pdftotext` installed:

```bash
PYTHONPATH=src python examples/run_remind_evidence_validation.py \
  --manifest '/Users/romain/Library/Application Support/trails/stock-vintage-evidence/2026-10-10-validation/manifest.json' \
  --baseline /Users/romain/GitHub/trails/build/reports/remind-npi2025-sector-expansion \
  --naei-pdf '/Users/romain/Library/Application Support/trails/stock-vintage-evidence/2026-10-10-validation-supplemental/naei-fleet-turnover.pdf' \
  --output-dir /path/to/new-output
PYTHONPATH=src python examples/validate_stock_output.py \
  /path/to/new-output/REMIND_generic_SSP2-NPi2025_stock_vintages_report.json
```

Use the existing filtered/encrypted/runtime workflow in
[stock-vintage-validation.md](stock-vintage-validation.md) with this output and
configuration. The eleven-group exporter is
`examples/export_sector_runtime_fixture.py`. Run paired premise
`check_iam_enrichment_runtime.py`, export constant/varying fixtures, then paired
TRAILS `check_iam_enrichment.py` on the integration directory. Isolate caches and
Brightway data; use a random local encryption test key and delete it after the
checks. The campaign output includes the cache-isolation wrapper and logs.

Finally generate the standalone assessment and figures:

```bash
MPLCONFIGDIR=/private/tmp/iam-evidence-mpl PYTHONPATH=src \
  python examples/plot_remind_evidence_validation.py /path/to/new-output
```

The completed local output is
`/Users/romain/GitHub/trails/build/reports/remind-npi2025-evidence-validation`.
Review `assessment.md`, `remind-evidence-validation-report.pdf`, seven PNG figures,
`distribution-plot-data.csv`, the source/transition/generation ledgers and
`artifact-manifest.json`. The report distinguishes remaining empirical gaps from
passed software/accounting checks. Source definitions:
[EIA-860](https://www.eia.gov/electricity/data/eia860/),
[EIA-923](https://www.eia.gov/electricity/data/eia923/),
[DfT licensing tables](https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-tables).
