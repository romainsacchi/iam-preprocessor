# iam-preprocessor

`iam-preprocessor` is a Python library and command-line application that turns
integrated assessment model (IAM) scenario exports into files ready to be
consumed by [`premise`](https://github.com/polca/premise).

It provides reproducible model-specific transformations, selects the variables
used by `premise`, writes consistently formatted scenario files, and can encrypt
the results with the standard Premise key.

## Supported workflows

| IAM | Processing |
| --- | --- |
| IMAGE | Derives transport energy-service variables, including explicit battery-electric medium- and heavy-truck variables when SEC assumptions are supplied. |
| MESSAGE | Normalizes region labels and removes the unsupported global aggregate. |
| REMIND | Splits cement production and energy use into CCS and non-CCS variables and removes legacy aggregate regions. |
| Any supported table | Filters variables using the `premise` variable-prefix allowlist. |
| Opt-in stock vintages | Uses flodym lifetime models and explicit initial cohorts to append stock/service vintage variables. First reviewed example: REMIND SSP2-NPi2025, cars, trucks, PV and CCGT. |

Inputs can be CSV or Excel files. Each model workflow writes a semicolon-delimited
CSV and a JSON processing report containing source and output hashes, row counts,
effective non-secret assumptions, and validation warnings. Existing outputs are
protected unless `--overwrite` is supplied.

## Installation

Python 3.10 or newer is required.

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Install the development dependencies when running tests or building the API
documentation:

```console
python -m pip install -e ".[dev]"
```

## Command-line usage

Process one file, several files, or every supported file directly inside an
input directory:

```console
iam-preprocessor message message-inputs --output-dir processed/message
iam-preprocessor remind remind-inputs --output-dir processed/remind
iam-preprocessor image image-inputs --output-dir processed/image \
  --sec-config assumptions.yaml
```

Run `iam-preprocessor COMMAND --help` for all options available to a workflow.

To reconstruct stock vintages from a CSV, REMIND MIF or Excel table:

```console
python -m pip install -e '.[stocks]'
iam-preprocessor stock-vintages scenario.mif --config stocks.yaml -o output/stocks
```

The feature is opt-in and produces labelled reconstructions, not native IAM
vintages. No new lifetime defaults are applied to other preprocessing commands.
See the [configuration, method and variable contract](docs/stock-vintages.md)
and [single-scenario validation strategy](docs/stock-vintage-validation.md).

## Model-specific transformations

### IMAGE

The IMAGE workflow:

- converts final-energy rows from PJ/yr to EJ/yr when needed and rejects
  unsupported transport-energy units;
- derives passenger and freight energy-service variables from final energy using
  the configured specific energy consumption (SEC), with outputs expressed in
  billion pkm/yr or billion tkm/yr; and
- derives explicit battery-electric medium- and heavy-truck final energy and
  service variables from the residual between total truck electricity and
  reconstructed plug-in-hybrid electricity use.

World BEV truck values are calculated as the sum of the derived regional values
because IMAGE does not provide the World-level plug-in-hybrid efficiency rows
needed for a direct calculation.

The BEV derivation requires reviewed medium- and heavy-truck SEC assumptions in
MJ/tkm:

```yaml
bev_truck_sec_mj_per_tkm:
  Medium Truck: 1.0
  Heavy Truck: 0.5
```

The numbers above only illustrate the configuration format; they are not
recommended scientific assumptions. Values can instead be passed with
`--medium-bev-sec` and `--heavy-bev-sec`. Use `--skip-bev` to disable the BEV
derivation or `--strict` to reject material negative residuals.

### MESSAGE

The MESSAGE workflow normalizes the region dimension by removing the `R12_`
prefix from region labels and dropping `GLB` aggregate rows. Other columns and
regional values remain unchanged before the shared variable filter is applied.

### REMIND

The REMIND workflow:

- removes `EU27` rows;
- also removes the overlapping `EUR` and `NEU` aggregates when processing an
  input whose filename contains `EU21`; and
- derives a cement CCS share from reported carbon capture and process emissions,
  then splits cement production and final-energy use between the original
  non-CCS rows and new `w CCS` rows.

Zero capture-plus-emissions denominators produce a zero CCS share. Rates outside
the interval from zero to one are clipped and recorded as validation warnings.

## Variable filtering

Model workflows filter their results by default. A scenario table can also be
filtered independently:

```console
iam-preprocessor filter scenario.csv --output-dir processed
```

Pass `--no-filter` to a model workflow when the complete transformed table is
needed.

## Encryption

The application loads `PREMISE_KEY` from the process environment or from the
nearest `.env` file in the current directory or its parents. Create a local file
from the tracked template and restrict it to the current user:

```console
cp .env.example .env
chmod 600 .env
```

```dotenv
PREMISE_KEY=your-fernet-key
```

The `.env` file is ignored by Git. An existing `PREMISE_KEY` or the compatible
`IAM_PREPROCESSOR_KEY` environment variable takes precedence over `.env`. A
protected `--key-file` takes precedence over all environment sources.

Encrypt or decrypt individual files with:

```console
iam-preprocessor encrypt processed.csv encrypted.csv
iam-preprocessor decrypt encrypted.csv recovered.csv
```

Model workflows can create encrypted copies directly:

```console
iam-preprocessor message message-inputs \
  --output-dir processed \
  --encrypt-to encrypted
```

Keys are never accepted as command-line values, written to processing reports,
or included in tracked files.

## Python API

The same workflows are available as Python functions:

```python
from iam_preprocessor import prepare_message

reports = prepare_message(
    ["/path/to/MESSAGE.csv"],
    "/path/to/processed",
)

for report in reports:
    print(report.output_path, report.output_rows)
```

The public API also provides `prepare_image`, `prepare_remind`,
`filter_variables`, `encrypt_file`, `decrypt_file`, and the transport derivation
functions. Build the complete API reference with:

```console
sphinx-build -W -b html docs docs/_build/html
```

## Development

```console
ruff check src tests
ruff format --check src tests
pytest
sphinx-build -W -b html docs docs/_build/html
```

The project is licensed under the BSD 3-Clause License.
