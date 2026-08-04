Security and reproducibility
============================

The repository ignores common scenario and key file extensions. Tests generate
all scenario-like tables and Fernet keys at runtime.

Encryption keys are read from ``IAM_PREPROCESSOR_KEY`` or a key file. Key files
take precedence and generate a warning when group or other users can read them.
Keys are never accepted as CLI values, logged, or serialized in processing
reports.

Each model workflow writes a JSON report containing input and output hashes,
effective SEC assumptions, row counts, derived and skipped variables, and
validation warnings. The report deliberately contains no secret material.
