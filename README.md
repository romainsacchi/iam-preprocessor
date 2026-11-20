# iam-preprocessor

`iam-preprocessor` prepares energy and climate scenarios for `premise`. It also
estimates when the assets in use in a given year were built. For example, it can
estimate how much of the solar capacity still operating in 2040 was built in
2025. [premise](https://github.com/polca/premise)

The estimates are preliminary. They use reported capacity and additions,
equipment lifetimes, and information about the assets already in use at the
start. The same workflow is designed for integrated assessment models (IAMs)
used with `premise`, including REMIND, IMAGE, and MESSAGE. Each asset needs
matching input rows and a documented lifetime assumption.

## Start here

- The method, inputs, outputs, and limitations. [Stock-vintage guide](docs/stock-vintages.md)
- The short guides and research notes. [Documentation list](docs/README.md)
- The files to use for a first run. [Examples](examples/README.md)
- The Python modules and functions. [Python API](docs/api.rst)

## Installation

Python 3.10 or newer is required.

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[stocks]'
```

## Build stock vintages

Inspect the variables, adapt the example YAML to your scenario, and run the
reconstruction. Use one model and scenario per stock-vintage run.

```console
iam-preprocessor stock-inventory scenario.csv -o stock-inventory.csv
iam-preprocessor stock-config scenario.csv --mapping stock-mapping.yaml -o stocks.yaml
iam-preprocessor stock-vintages scenario.csv --config stocks.yaml \
  -o output/stocks --package-only
```

`stock-inventory` lists the regions, variables, and units in the file. Copy and
edit the template to specify the rows and assumptions for each asset.
`stock-config` records the model and scenario names and checks that the rows
match. `stock-vintages` writes the build-year estimates in a Parquet table, a
summary of the checks, a list of the output files, and a run report.
[Stock mapping template](examples/stock-mapping.yaml)

Input files can be CSV, MIF, or Excel. Use one column per year. Start with
observations of when existing assets were built, or state an assumption about
their ages. The current workflow requires rows for both installed stock and
additions.

## How the code is divided

| Module | Responsibility |
| --- | --- |
| `stock_workflow.py` | List variables and check the selected rows against the scenario. |
| `stock_config.py` | Check the YAML settings and find the files they refer to. |
| `vintage_inputs.py` | Read the selected rows and fill in years between reported values. |
| `vintage_reconstruction.py` | Estimate one asset's build-year groups and their shares. |
| `stock_model.py` and `flodym_stock.py` | Work out how much stock survives, is added, or retires. |
| `stock_annualisation.py` | Fit annual additions to reported stock and addition data. |
| `stock_vintages.py` and `stock_package.py` | Check and write the results for all selected assets. |

FLODyM tracks the assets built in each year as they age and retire. In `joint`
mode, SciPy and OSQP first estimate annual additions using both the stock and
addition data. The installation command above uses a specific FLODyM revision
for reproducible results. [FLODyM PR #261](https://github.com/pik-piam/flodym/pull/261)

Every IAM uses the same YAML format for the stock calculation. Optional code
that corrects input files lives under `adapters/`. The older REMIND stock
mapping tools live under `research/remind/` for reproducing past studies.

## Prepare scenario files

Use `prepare` to put the table in a standard format and write a CSV. Use
`--no-filter` to retain all rows for stock reconstruction.
Use `--scenario` to select one scenario from a workbook with several runs.

```console
iam-preprocessor prepare scenario.xlsx --output-dir processed --no-filter
```

The YAML files define which variables to read, how to name newly calculated
variables, and what to keep when filtering. Optional corrections for specific
models are listed in the [command-line guide](docs/usage.rst).

## Development checks

```console
ruff check src tests examples
ruff format --check src tests examples
pytest
sphinx-build -W -b html docs docs/_build/html
```

Tests use small made-up datasets. The repository excludes private input files,
generated results, and encryption keys. Use `--overwrite` to replace existing
outputs.

The project uses the BSD 3-Clause License.
