# iam-preprocessor

`iam-preprocessor` turns the mixed preprocessing cells from the former
`encryption.ipynb` notebook into tested, reusable model workflows. It prepares
IMAGE, MESSAGE, and REMIND scenario tables for `premise`, filters variables, and
optionally encrypts the resulting CSV files without storing secrets.

The repository deliberately contains no IAM scenario files, generated outputs,
or encryption keys.

## Install for development

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Prepare IMAGE files

IMAGE reports total medium- and heavy-truck electricity, but not explicit BEV
transport service. The application subtracts electricity reconstructed from the
reported plug-in-hybrid activity, then converts the remaining BEV electricity to
transport service using explicit assumptions supplied at runtime.

```console
iam-preprocessor image /path/to/image-inputs \
  --output-dir /path/to/processed \
  --medium-bev-sec 1.0 \
  --heavy-bev-sec 0.5
```

SEC values are in MJ/tkm; the example numbers above are placeholders, not
recommended scientific assumptions. Put reviewed values in an override file for
reproducible work:

```yaml
bev_truck_sec_mj_per_tkm:
  Medium Truck: 1.0
  Heavy Truck: 0.5
```

```console
iam-preprocessor image /path/to/image-inputs \
  --output-dir /path/to/processed \
  --sec-config assumptions.yaml
```

Use `--strict` to fail rather than clip material negative BEV residuals, or
`--skip-bev` when only the legacy carrier-service transformation is wanted.

## Other workflows

```console
iam-preprocessor message message.csv --output-dir processed
iam-preprocessor remind remind.csv --output-dir processed
iam-preprocessor filter scenario.csv --output-dir processed
```

Every model workflow writes semicolon-delimited CSV plus a JSON run report with
hashes, effective non-secret assumptions, and validation warnings. Existing files
are protected unless `--overwrite` is explicitly supplied.

## Encryption

Supply Fernet keys through `IAM_PREPROCESSOR_KEY` or a protected key file. Raw
keys are not accepted as command-line values and are never added to reports.

```console
export IAM_PREPROCESSOR_KEY="$(< /secure/path/iam.key)"
iam-preprocessor encrypt processed.csv encrypted.csv
iam-preprocessor decrypt encrypted.csv recovered.csv
```

Model workflows can also write an encrypted copy:

```console
iam-preprocessor image /path/to/image-inputs \
  --output-dir processed \
  --encrypt-to encrypted \
  --key-file /secure/path/iam.key \
  --sec-config assumptions.yaml
```

## Python API

```python
from iam_preprocessor import load_sec_config, prepare_image

config = load_sec_config("assumptions.yaml")
reports = prepare_image(
    ["/path/to/IMAGE.xlsx"],
    "/path/to/processed",
    config,
)
```

Build the complete API documentation with:

```console
sphinx-build -W -b html docs docs/_build/html
```

## Development checks

```console
ruff check src tests
ruff format --check src tests
pytest
```

Licensed under the BSD 3-Clause License.
