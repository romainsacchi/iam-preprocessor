# iam-preprocessor

`iam-preprocessor` prepares integrated assessment model (IAM) scenario files for
[`premise`](https://github.com/polca/premise). Its main research feature
reconstructs the annual build-up of stock assets: for each model year, it reports
how much surviving capacity comes from each construction year.

The reconstruction is preliminary. Generated vintages are derived from IAM stock,
addition, and lifetime data plus explicit assumptions about the opening stock.
They are not native IAM output.

## Start here

- [Stock-vintage guide](docs/stock-vintages.md): inputs, equations, assumptions,
  output, and limitations.
- [Documentation map](docs/README.md): short guides and detailed research records.
- [Example map](examples/README.md): which scripts are suitable for a first run.
- [Python API](docs/api.rst): module-level reference.

## Installation

Python 3.10 or newer is required.

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[stocks]'
```

For tests and documentation:

```console
python -m pip install -e '.[dev]'
```

## Build stock vintages

A typical REMIND run has three steps:

```console
iam-preprocessor remind-stock-inventory scenario.mif -o stock-inventory.csv \
  --region DEU --region FRA --region UKI

iam-preprocessor remind-stock-config scenario.mif -o stocks.yaml \
  --region DEU --region FRA --region UKI --reconciliation joint

iam-preprocessor stock-vintages scenario.mif --config stocks.yaml \
  -o output/stocks --package-only
```

The inventory is a coverage check. The YAML file records variable mappings and
scientific assumptions. The final command writes a sparse Parquet table, a
validation summary, a checksum-bound manifest, and a JSON processing report.

The workflow accepts a normalized IAM table from another model when the YAML file
identifies exact rows for installed stock and additions and defines a lifetime
assumption. Opening cohorts can come from observations or an explicit prior.

## How the code is divided

The production path follows this order:

| Module | Responsibility |
| --- | --- |
| `stock_config.py` | Validate the YAML contract and resolve evidence files. |
| `vintage_inputs.py` | Select exact IAM rows and expand them to annual series. |
| `stock_model.py` | Apply survival and annual stock-flow accounting. |
| `flodym_stock.py` | Define lifetime models and run the FLODyM stock solvers. |
| `stock_annualisation.py` | Reconcile stock anchors and reported additions in joint mode. |
| `vintage_reconstruction.py` | Build one asset's cohorts and service shares. |
| `stock_vintages.py` | Process all configured assets and assemble public output. |
| `stock_package.py` | Validate and write the canonical data package. |

Production uses FLODyM for fixed and Weibull survival and implements the REMIND
retirement curve as a FLODyM lifetime model. The stock extra installs the pinned
revision from [FLODyM PR #261](https://github.com/pik-piam/flodym/pull/261).
FLODyM initializes and projects cohorts and handles proportional, oldest-first,
and hazard-scaled retirement in stock-driven mode. The joint fit uses SciPy and
OSQP to determine annual additions, then FLODyM projects the resulting cohorts.

The `stock_evidence`, `stock_history`, `stock_observations`, `stock_service`,
`stock_survival_fit`, and `stock_validation` modules support evidence preparation
and validation campaigns. They are useful research tools but are not called by a
normal `stock-vintages` run.

Repository folders have distinct roles: `src/iam_preprocessor` contains library
code, `tests` contains synthetic regression cases, `examples` contains reproducible
research scripts, and `docs` contains guides and research records.

## Other preprocessing workflows

| IAM | Processing |
| --- | --- |
| IMAGE | Derive transport energy-service variables from reviewed SEC assumptions. |
| MESSAGE | Normalize region labels and remove the global aggregate. |
| REMIND | Split cement production and energy use into CCS and non-CCS variables. |
| Any supported table | Keep variables accepted by the `premise` allowlist. |

Examples:

```console
iam-preprocessor image image-inputs --output-dir processed/image \
  --sec-config assumptions.yaml
iam-preprocessor message message-inputs --output-dir processed/message
iam-preprocessor remind remind-inputs --output-dir processed/remind
```

Run `iam-preprocessor COMMAND --help` for command options.

## Development checks

```console
ruff check src tests examples
ruff format --check src tests examples
pytest
sphinx-build -W -b html docs docs/_build/html
```

Tests use small synthetic fixtures. Scenario files, evidence archives, generated
outputs, reports, encryption keys, and local environment files are excluded from
Git. Existing outputs are protected unless `--overwrite` is supplied.

The project uses the BSD 3-Clause License.
