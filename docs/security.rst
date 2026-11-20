Security and reproducibility
============================

Git ignores common file types used for scenarios and encryption keys. Tests
make their own input tables and keys.

Encryption keys are read from ``PREMISE_KEY`` or the backwards-compatible
``IAM_PREPROCESSOR_KEY``. When neither is already present in the process
environment, the nearest ``.env`` file in the current directory or its parents
is loaded with ``python-dotenv`` without overwriting existing variables. A key
file takes precedence and generates a warning when group or other users can read
it. Supply keys through the environment or a key file. Keys stay out of logs
and run reports.

Git ignores ``.env``. Start with ``.env.example`` and restrict the real file to
its owner with ``chmod 600 .env``.

Each workflow writes a JSON run report. It records fingerprints of the input
and output files, the assumptions used, the row counts, any calculated or
skipped variables, and warnings.
