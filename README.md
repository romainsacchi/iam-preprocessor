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
| MESSAGE | Splits aggregate DRI/EAF steel into mutually exclusive NG-DRI, NG-DRI+CCS, and H-DRI routes, normalizes region labels, and removes the unsupported global aggregate. |
| REMIND | Splits cement production and energy use into CCS and non-CCS variables and removes legacy aggregate regions. |
| Any supported table | Filters variables using the `premise` variable-prefix allowlist. |

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
prefix from region labels and dropping `GLB` aggregate rows. Exact duplicate
source rows are removed before validation.

MESSAGE reports reduction-route activity as sponge iron but only reports
finished primary DRI/EAF steel as an aggregate. The workflow derives three
mutually exclusive finished-steel variables:

- `Production|Industry|Iron and Steel|NG-DRI/EAF`;
- `Production|Industry|Iron and Steel|NG-DRI/EAF + CCS`; and
- `Production|Industry|Iron and Steel|H-DRI/EAF`.

For each scenario and year, the reported World finished DRI/EAF steel-to-total
sponge-iron conversion factor is applied to regional hydrogen and gas-with-CCS
sponge iron. The remaining non-H2/non-CCS output uses premise's existing
NG-DRI inventory proxy. This residual includes MESSAGE's coal-without-CCS
sponge-iron remainder because premise has no separate coal-DRI inventory
category. This construction preserves the original aggregate DRI/EAF output in
every region and year and preserves World versus regional totals. When no
explicit World row is available, regional sums determine the conversion
factor. Missing inputs skip the derivation with a report warning; inconsistent
units, negative residuals, or non-closing results fail validation.

The workflow does not invent route-specific energy-use series. MESSAGE's
reported DRI/EAF energy use remains aggregate and should not be assigned to one
of the derived routes as if it were route-specific.

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
