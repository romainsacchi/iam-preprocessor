Security and reproducibility
============================

The repository ignores common scenario and key file extensions. Tests generate
all scenario-like tables and Fernet keys at runtime.

Encryption keys are read from ``PREMISE_KEY`` or the backwards-compatible
``IAM_PREPROCESSOR_KEY``. When neither is already present in the process
environment, the nearest ``.env`` file in the current directory or its parents
is loaded with ``python-dotenv`` without overwriting existing variables. A key
file takes precedence and generates a warning when group or other users can read
it. Keys are never accepted as CLI values, logged, or serialized in processing
reports.

The repository ignores ``.env`` and provides a safe-to-track ``.env.example``
without a value. Restrict the real file to its owner with ``chmod 600 .env``.

Each model workflow writes a JSON report containing input and output hashes,
effective SEC assumptions, row counts, derived and skipped variables, and
validation warnings. The report deliberately contains no secret material.
