# REMIND stock-vintage project: findings and restart report

**Restart checkpoint, 27 October 2026.** Further implementation remains paused
pending additional exact-run REMIND/EDGE-T data. This report is the entry point
for resuming the project without the original conversation. Read the findings
below, then the [restart instructions](#restart-instructions-and-project-checkpoint).
The validation counts describe the completed 10 October campaign; they were not
rerun for this documentation checkpoint. The current input/output audit and
recovery gaps are recorded separately below.

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

The historical completed output location was
`/Users/romain/GitHub/trails/build/reports/remind-npi2025-evidence-validation`.
That directory is absent at the restart checkpoint; recover or regenerate it
as described below. Expected outputs are `assessment.md`,
`remind-evidence-validation-report.pdf`, seven PNG figures,
`distribution-plot-data.csv`, the source/transition/generation ledgers and
`artifact-manifest.json`. The report distinguishes remaining empirical gaps from
passed software/accounting checks. Source definitions:
[EIA-860](https://www.eia.gov/electricity/data/eia860/),
[EIA-923](https://www.eia.gov/electricity/data/eia923/),
[DfT licensing tables](https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-tables).

## Restart instructions and project checkpoint

### Scope, architecture and accounting decisions

The reviewed producer is one scenario, `REMIND / SSP2-NPi2025`, for annual
service years **2022–2050**. Transport assets are `passenger-bev`, `heavy-trucks`
and `passenger-liquids` in EUR. Power assets are `pv`, `ccgt`, `wind-onshore`,
`wind-offshore`, `nuclear`, `gas-turbine`, `geothermal` and `csp` in USA.
`passenger-liquids` combines petrol and diesel; fuel-specific initial-state and
usage sensitivities are not separate IAM fleet forecasts. The earlier bounded
pilots also covered `SSP2-PkBudg650` and an external-data water case; those do
not extend the eleven-group producer's validated scenario scope.

The workflow is:

```text
original IAM stock/capacity + gross additions/sales + service + lifetime inputs
  + observed initial cohorts + explicit survival/utilisation assumptions
  -> iam-preprocessor / flodym: annual cohort stocks and service shares
  -> enriched CSV and matching hashed JSON report, optional filtering/encryption
  -> premise: exact annual profile access and explicit inventory bindings
  -> TRAILS: dated manufacturing pulses, with stock_vintage=True
```

Preserve these decisions when restarting:

- Reconstruct stocks using surviving initial cohorts and later inflows times
  their survival probabilities, with documented additional exits. A lifetime
  probability density is not a stock-age distribution. Initial observations
  are survivors, not historical sales. Technical lifetime is not automatically
  a measured mean survival time.
- Keep stock shares and service shares separate. Service shares are proportional
  to surviving cohort quantities times cohort-specific utilisation. A common
  annual scaling to match aggregate generation/transport does not identify
  relative utilisation: it cancels when weights are normalised.
- Under the retained `common_amortisation` convention, the existing capital
  coefficient `q(t)` becomes pulses `q(t) * w(cohort, t)`, with weights summing to
  one. Do not divide the already amortised coefficient by lifetime again.
  Individual lifetime-service allocation would require a separate reviewed
  accounting change; it is not inferred from a stock histogram.
- Preserve physical manufacture dates even outside inventory anchors. Clamp
  only the inventory lookup where required. Use exact annual profiles and
  explicit caller/supplier identities and units; missing coverage must fail.
- Keep parent manufacture, replacement components, maintenance, occupation and
  disposal as separately assigned roles. Operating-stock exits do not establish
  physical disposal dates. Do not apply parent age profiles indiscriminately.
- Joint annualisation preserves native stock anchors and distinguishes sampled
  annual sales from period-average power additions. Incompatible inflow
  constraints remain reported under the explicit penalty policy. Additional
  exit fractions are inherited from the stock baseline, not freely fitted.
- UK-to-EUR and selected-WECC-to-USA composition transfers remain proxies.
  Equal-service defaults, lifetime/shape priors, within-year exposure and
  unresolved technology boundaries remain assumptions. Do not promote global
  defaults or extend post-2050 reporting semantics without new evidence.

### Code checkpoints and where to work

The remote branch tips below were checked directly on 27 October 2026, before
this report update. All project worktrees were clean. The main
`iam-preprocessor` checkout was on an unrelated PyPSA experiment with pending
changes; use the feature worktree rather than changing that checkout.

| Repository and purpose | Branch | Checkpoint before this report |
|---|---|---|
| [iam-preprocessor](https://github.com/romainsacchi/iam-preprocessor/tree/feat/stock-evidence-validation), complete eleven-group producer | `feat/stock-evidence-validation` | `0e2359b5895b790a97c1d633674435945b392c96` |
| [premise](https://github.com/polca/premise/tree/feat/iam-stock-vintage-enrichment), annual reader/export | `feat/iam-stock-vintage-enrichment` | Tested: `8a8376155b316745734f29ae01c4e656424c38d2`; remote: `13a26fb733cbdce038d94cc8d94c39b370766e62` |
| [TRAILS integration](https://github.com/Laboratory-for-Energy-Systems-Analysis/trails/tree/feat/iam-stock-vintage-enrichment) | `feat/iam-stock-vintage-enrichment` | `ad961ef7d8a2925da3da48ce98cf7515f9f098c7` |
| [TRAILS pilots, report generator and data specification](https://github.com/Laboratory-for-Energy-Systems-Analysis/trails/tree/feat/stock-vintage-pilots) | `feat/stock-vintage-pilots` | `7bec4c1e1eaa34ae191184aad79f12bcb6f19706` |

The premise remote has one later commit, `13a26fb7` (`Black reformating`). The
recorded integration evidence used `8a837615`; reproduce that revision before
testing the later branch tip. Do not describe an untested tip as the tested pair.
Use the commit containing this report as the documentation checkpoint; its
parent producer checkpoint is the hash in the table. Branches remain separate
from main; this checkpoint does not merge or release them.

Existing local worktrees are:

```text
/Users/romain/GitHub/iam-preprocessor-evidence-validation
/Users/romain/GitHub/premise-iam-stock-vintages
/Users/romain/GitHub/trails-iam-stock-vintages
/Users/romain/GitHub/trails                         # pilot checkpoint branch
```

Producer history: `b5d5067` (flodym reconstruction), `409e1de` (joint annualisation),
`83cf844b169a9057131cf906941488701b58a50d` (eleven-group comparison baseline),
`4eda2aa` (frozen evidence plan), `5c79f1c` (evidence implementation), `0e2359b`
(completed campaign). The complete producer branch contains these stages;
separate old feature worktrees are not needed except to regenerate a baseline.

Relevant source and documentation:

- Producer: `src/iam_preprocessor/stock_{config,model,annualisation,vintages}.py`,
  `stock_{observations,history,validation,service,usage}.py`,
  `src/iam_preprocessor/data/remind_stock_assets.yaml`, and the `examples/`
  scripts named in this report.
- [Schema and configuration](stock-vintages.md),
  [joint annualisation](joint-stock-annualisation.md),
  [integration/validation boundaries](stock-vintage-validation.md),
  [sector mappings](remind-sector-expansion.md),
  [frozen protocol](remind-evidence-protocol.md), and
  [evidence plan](remind-evidence-work-package.md).
- premise: `premise/iam_stock_vintage.py`, `premise/stock_vintage.py`,
  `docs/development/stock-asset-temporal/iam-enrichment.md`,
  `dev/stock_vintage/check_iam_enrichment_runtime.py`, and
  `dev/stock_vintage/export_iam_enrichment_fixture.py` at the tested revision.
- TRAILS integration: `trails/stock_vintage.py`,
  `docs/stock-vintage-development.md`, and
  `dev/stock_vintage/check_iam_enrichment.py` at the tested revision.
- TRAILS pilot checkpoint: `docs/remind-stock-vintage-data-specification.md`,
  `docs/remind-stock-vintage-robustness-plan.md`, and
  `dev/stock_vintage/diagnose_remind_reconstruction.py`. The older roadmap's
  four-technology/2030 limitations describe the bounded pilots; use this report
  for the later eleven-group/2050 implementation status.

### Private evidence inventory and recovery gaps

The durable private root is
`/Users/romain/Library/Application Support/trails/stock-vintage-evidence`.
Preserve it separately from Git; it contains licensed inventories and IAM data.
Keep encryption keys outside both Git and this report. Raw data, generated
profiles and full-inventory packages are not included in the code push.

| Archive below the private root | Manifest SHA-256 | Audit on 27 October |
|---|---|---|
| `2026-10-10-pilots` | `c15467bdb209ece5c556248c16edc6257dae034dd121b9a6c935b4f5fe726231` | All 163 manifest-listed files SHA-256 verified |
| `2026-10-10-validation` | `18efb92c24a92a46629f48be0484d58e1dac1e07ca2e1b02b11f6f8651e1f0e1` | 13 available manifest inputs hash-verified; two external baseline artifacts missing |
| `2026-10-10-validation-supplemental` | `b8108dada4726d430f266dbcc37d6588c11887345dccd8b5b9e8327c73a57f52` | NAEI PDF hash-verified |

The pilots archive contains `cohorts/`, `iam-inputs/`, `public-sources/`,
restricted full-inventory evidence, source snapshots and environment inventories.
Its pinned source snapshots describe the earlier pilots, not the latest
eleven-group producer; use the Git checkpoints above for that producer.
The validation manifest pins EIA-860 2020–2022, EIA-923 2022, DfT vehicle tables,
archived EDGE/reporttransport code, the scenario, protocol and campaign YAML.
Some entries refer into the pilots archive; retain the entire private root.

Critical file identities:

| File | SHA-256 |
|---|---|
| `2026-10-10-pilots/iam-inputs/remind 3.5.2/REMIND_generic_SSP2-NPi2025.mif` | `b19b71690d672b5e5cc2e908eeb5486fe723103f6ab6c852cdffc45486feb6dd` |
| `2026-10-10-validation-supplemental/naei-fleet-turnover.pdf` | `facb7aa1690a2ab40328243797f6790ed85f1526e79d601f5a0def4cf8c08706` |
| Missing sector-expansion baseline report JSON | `2132f094a71eacac607f8cf2409b9d159b6dae4dfce34e08a22dbb1eac32e345` |
| Missing sector-expansion baseline enriched CSV | `69b2fd30cad2a87f31ea1cb3f07251faa7544d3a0262a802b74381005f51cde0` |

Both the sector-expansion baseline directory and the completed evidence output
directory under `/Users/romain/GitHub/trails/build/reports/` are absent. Therefore
the reproduction command above cannot currently pass the frozen manifest gate.
Recover the whole baseline directory from a private backup if available: the
JSON/CSV alone are insufficient. Its config and all initial-cohort files
referenced by that config are also needed. Otherwise regenerate as below.

The original `/private/tmp/stock-vintage-premise-venv/bin/python` no longer
exists. Neither current `premise` nor `trails` conda environment has flodym.
The surviving TRAILS environment has changed dependencies since the campaign;
do not assume its current installed package is the pinned source. Use isolated
environments and check imported module paths. `pdftotext` is available locally.

### Restart sequence and baseline recovery

1. Inspect worktree status, select the checkpoints above, and verify the private
   manifests before changing data. Retain the original manifests unmodified.
2. Prefer exact native cohort data if they have arrived. Apply the acceptance
   checks below before adapting the producer. Otherwise reconstruct the old
   comparison baseline first, then rerun the existing evidence campaign.
3. Create a **new durable private run directory** outside Git and outside
   `/private/tmp`; preserve environments or dependency inventories, inputs,
   config-referenced observations, enriched CSV/JSON pairs, logs and results
   together. The paths below are shell variables to set to those local paths.

Use Python 3.11 for the producer and TRAILS, with an isolated premise environment
compatible with its pinned source. Install the producer's `.[stocks,dev]` extra
plus matplotlib; `flodym==1.1.0` is pinned. Install each consumer from its paired
source, using its declared requirements. Do not overwrite shared environments.
The pilot archive manifest retains earlier complete package inventories;
those inventories are historical evidence, not a lockfile for the new producer.

```bash
# Run from a clean producer worktree; set these to absolute local paths first.
export VINTAGE_PRIVATE_ROOT='/Users/romain/Library/Application Support/trails/stock-vintage-evidence'
export VINTAGE_RUN_ROOT='/absolute/private/path/to/a/new-resume-run'
export VINTAGE_PRODUCER='/Users/romain/GitHub/iam-preprocessor-evidence-validation'
export VINTAGE_PREMISE='/Users/romain/GitHub/premise-iam-stock-vintages'
export VINTAGE_TRAILS='/Users/romain/GitHub/trails-iam-stock-vintages'
python3.11 -m venv "$VINTAGE_RUN_ROOT/producer-env"
export VINTAGE_PY="$VINTAGE_RUN_ROOT/producer-env/bin/python"
"$VINTAGE_PY" -m pip install -e "${VINTAGE_PRODUCER}[stocks,dev]" matplotlib

# Recover the comparison with its original code, not the later evidence adapter.
git -C "$VINTAGE_PRODUCER" worktree add --detach \
  "$VINTAGE_RUN_ROOT/baseline-code" 83cf844b169a9057131cf906941488701b58a50d
cd "$VINTAGE_RUN_ROOT/baseline-code"
PYTHONPATH=src "$VINTAGE_PY" examples/run_remind_sector_expansion.py \
  --archive "$VINTAGE_PRIVATE_ROOT/2026-10-10-pilots" \
  --output-dir "$VINTAGE_RUN_ROOT/sector-expansion" --end-year 2050
```

Report bytes contain absolute paths, dependency versions and implementation
hashes. A regenerated baseline may therefore differ from the historical hashes;
that is not an exact restoration. Keep the old manifest and create a **new
explicitly labelled recovery manifest**, preserving unchanged source pins and
recording the replacement baseline and its origin. The following does that for
the existing campaign runner without bypassing its hash checks:

```bash
"$VINTAGE_PY" - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["VINTAGE_PRIVATE_ROOT"])
run = Path(os.environ["VINTAGE_RUN_ROOT"])
original = root / "2026-10-10-validation/manifest.json"
manifest = json.loads(original.read_text())
for item in manifest["files"].values():
    item["file"] = str((original.parent / item["file"]).resolve())
for role, suffix in (("baseline_report", "_report.json"), ("baseline_output", ".csv")):
    path = run / "sector-expansion" / ("REMIND_generic_SSP2-NPi2025_stock_vintages" + suffix)
    manifest["files"][role] = {
        "file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
    }
manifest["recovery"] = {
    "origin": "regenerated comparison; not the original frozen artifacts",
    "original_manifest_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
    "baseline_code_commit": "83cf844b169a9057131cf906941488701b58a50d",
}
(run / "recovery-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
cd "$VINTAGE_PRODUCER"
PYTHONPATH=src "$VINTAGE_PY" examples/run_remind_evidence_validation.py \
  --manifest "$VINTAGE_RUN_ROOT/recovery-manifest.json" \
  --baseline "$VINTAGE_RUN_ROOT/sector-expansion" \
  --naei-pdf "$VINTAGE_PRIVATE_ROOT/2026-10-10-validation-supplemental/naei-fleet-turnover.pdf" \
  --output-dir "$VINTAGE_RUN_ROOT/evidence"
PYTHONPATH=src "$VINTAGE_PY" examples/validate_stock_output.py \
  "$VINTAGE_RUN_ROOT/evidence/REMIND_generic_SSP2-NPi2025_stock_vintages_report.json"
MPLCONFIGDIR="$VINTAGE_RUN_ROOT/mpl" PYTHONPATH=src \
  "$VINTAGE_PY" examples/plot_remind_evidence_validation.py "$VINTAGE_RUN_ROOT/evidence"
```

If an exact backup is restored instead, use the original frozen manifest and
original command. A recovered or regenerated run must retain its own provenance
and newly executed results. Do not copy the historical pass counts into a new
validation record without running the checks.

### Runtime reproduction and verification gates

Prepare the new evidence directory and a random Fernet test key with mode 0600.
From the producer worktree, run the integrated command on the pinned source MIF,
using the new evidence config `remind-npi2025-stock-config.yaml`:

```bash
"$VINTAGE_PY" - <<'PY'
import os
from pathlib import Path
from cryptography.fernet import Fernet

run = Path(os.environ["VINTAGE_RUN_ROOT"])
for kind in ("plain", "encrypted"):
    (run / "evidence/runtime" / kind).mkdir(parents=True, exist_ok=True)
fd = os.open(run / "test-key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as stream:
    stream.write(Fernet.generate_key())
PY
PYTHONPATH=src "$VINTAGE_RUN_ROOT/producer-env/bin/iam-preprocessor" stock-vintages \
  "$VINTAGE_PRIVATE_ROOT/2026-10-10-pilots/iam-inputs/remind 3.5.2/REMIND_generic_SSP2-NPi2025.mif" \
  --config "$VINTAGE_RUN_ROOT/evidence/remind-npi2025-stock-config.yaml" \
  -o "$VINTAGE_RUN_ROOT/evidence/runtime/plain" --filter-output \
  --encrypt-to "$VINTAGE_RUN_ROOT/evidence/runtime/encrypted" \
  --key-file "$VINTAGE_RUN_ROOT/test-key"
```

For premise's filename lookup, copy each plain/encrypted output CSV byte for
byte to `remind_SSP2-NPi2025.csv` inside its respective runtime directory. Also
copy the unfiltered evidence CSV to that accepted name in the evidence root.
Retain the original report filenames; copying under an accepted source name
preserves hashes, whereas rewriting or separately filtering it does not.
Copy `sector-observation-audit.json` from the recovered baseline directory into
the evidence directory: the eleven-group fixture exporter reads that catalogue.

```bash
"$VINTAGE_PY" - <<'PY'
import os
import shutil
from pathlib import Path

run = Path(os.environ["VINTAGE_RUN_ROOT"])
for folder in (run / "evidence", run / "evidence/runtime/plain", run / "evidence/runtime/encrypted"):
    shutil.copyfile(folder / "REMIND_generic_SSP2-NPi2025_stock_vintages.csv",
                    folder / "remind_SSP2-NPi2025.csv")
shutil.copyfile(run / "sector-expansion/sector-observation-audit.json",
                run / "evidence/sector-observation-audit.json")
PY
```

Define `VINTAGE_PREMISE_PY` and `VINTAGE_TRAILS_PY` as the isolated consumers'
Python executables. Set `BRIGHTWAY2_DIR`, `XDG_DATA_HOME` and `XDG_CACHE_HOME` to
separate private run paths before imports. Use each source checkout as the
working directory (or set `PYTHONPATH`) and verify `premise.__file__` and
`trails.__file__`; installed release names alone do not prove the feature code
is loaded. Then run:

```bash
cd "$VINTAGE_PREMISE"
"$VINTAGE_PREMISE_PY" dev/stock_vintage/check_iam_enrichment_runtime.py \
  "$VINTAGE_RUN_ROOT/evidence" --test-key "$VINTAGE_RUN_ROOT/test-key"
cd "$VINTAGE_PRODUCER"
"$VINTAGE_PREMISE_PY" examples/export_sector_runtime_fixture.py \
  --premise-checkout "$VINTAGE_PREMISE" --directory "$VINTAGE_RUN_ROOT/evidence"
cd "$VINTAGE_TRAILS"
"$VINTAGE_TRAILS_PY" dev/stock_vintage/check_iam_enrichment.py \
  "$VINTAGE_RUN_ROOT/evidence/integration"
```

The TRAILS checker accepts the integration parent and checks both constant and
varying packages. Require 176 passing signed cases across the eleven primary
assets, exact event years, absent-year rejection and unchanged coefficients.
The runtime reader must verify matching source/report hashes for plain,
encrypted and cached profiles. Remove the disposable test key after these
checks; retain logs and hashes, not the secret.

Run producer Ruff/format, pytest and Sphinx commands from the earlier validation
section after implementation changes. Run premise's `test_iam_stock_vintage.py`
and relevant stock-export tests, and TRAILS' stock-vintage/lifecycle tests when
their interfaces or routing change. Preserve new dependency versions and exact
Git revisions with the run. The three release requirements remain accounting
conservation, defensible reconstruction and actual producer-consumer evidence.

### Exact REMIND/EDGE-T data request and first work after arrival

The user paused the project on 10 October to request additional REMIND variables.
No response or new exact-run extract is established by this checkpoint. This
report update does not resume modelling or contact providers.

Request tables keyed by **run/scenario × region × native technology/class/grade
× evaluation year/period × original construction/commissioning vintage**:

| Priority | Required data | Purpose |
|---|---|---|
| 1 | Surviving installed/operating capacity or vehicle numbers by vintage, including historical initial stock | Replace survival-based vintage reconstruction and regional initial-state proxies |
| 1 | Electricity generation or transport service by the same vintage, with mileage/load/occupancy where represented | Replace assumed utilisation weights; distinguish capacity from service fidelity |
| 2 | Gross new entries and retirements by vintage, distinguishing natural, early, idle/reactivated and territorial exits | Reproduce the stock equation without inventing balancing flows or physical disposal |
| 2 | Actual survival/depreciation schedules, initialisation and early-exit rules from the run | Reproduce cohorts when direct outputs are unavailable |
| Required metadata | Run/model/config/input hashes; EDGE/reporttransport/remind2 versions; regional and technology crosswalks; units and native reporting windows | Establish exact-run and MIF reporting identity |

For transport, explicitly ask for exact-run equivalents of
`fleetVehNumbersConstrYears`, `fleetESdemandConstrYears` and
`reportEarlyRetirement`. For power, native capacity-equation leads include
`vm_deltaCap`, `vm_cap`, `pm_omeg`, `pm_ts` and `vm_capEarlyReti`; confirm their
actual run meanings and dimensions rather than treating names as a schema.
If generation is not represented by vintage, state that limitation: native
capacity fidelity still leaves a service-allocation assumption.

Start with the four original technologies/regions and the two original
scenarios (`SSP2-NPi2025`, `SSP2-PkBudg650`), requesting native periods covering
2020–2035 and their historical initial cohorts, preferably the full available
horizon. Confirm annual rate versus period total/sample, beginning/end/average
stock timing, lead times, AC/DC and gross/net capacity/generation, curtailment,
and transport service units. Preserve unavailable values separately from zeros.
The folder label `remind 3.5.2` is not proof of exact model/reporting lineage.

On arrival, work in this order:

1. Freeze the new extract and metadata in a new private manifest, retaining the
   current reconstruction as the comparator. Check unique keys, units, missing
   dimensions, compatible stock dates and reporting precision.
2. Sum native cohorts to native stock/service totals, then reproduce the native
   transition equation and the corresponding published MIF leaves separately.
   Set tolerances from export precision before reviewing residuals.
3. Diagnose discrepancies in units, categories/regions, reporting intervals,
   initial state, survival indexing and early exits. Keep native results,
   observation-initialised reconstructions and regional proxies distinguishable.
4. Add a small native-data adapter and compare full annual distributions,
   service weights and residuals with this eleven-group baseline. Preserve
   existing namespaces/contracts unless a separately versioned change is needed.
5. Extend historical and service validation, then review post-2050 five-to-ten-
   year reporting transitions, selective exits, broader regions/scenarios and
   varying real-inventory backgrounds. Components/disposal remain separately
   evidenced work. Do not expand scope before the native benchmark is understood.

If only aggregate stocks/additions/lifetimes arrive, retain the labelled
constrained-reconstruction route and its residuals; these inputs alone do not
uniquely determine historical cohorts or service by age.

For historical context only, the original Codex conversation was
**“Investigate Arblaster’s modeling”**, 9–10 October 2026, thread
`01a120ca-cf45-7060-82a9-9d12956412e9`. All restart decisions and paths needed
from that discussion are recorded above; the chat transcript is not an input.

### Checks performed for this documentation checkpoint

All 163 private pilot archive files, the 13 available frozen-validation inputs
and the supplemental NAEI PDF match their recorded SHA-256 hashes. The two
missing baseline artifacts remain explicitly identified above. Embedded shell
and Python snippets passed syntax checks, local Markdown document links resolve,
the Sphinx build passed with warnings treated as errors, and Git whitespace
checks passed. Numerical reconstruction and consumer integration were not rerun;
the recovery commands are documented procedures, not newly executed evidence.
