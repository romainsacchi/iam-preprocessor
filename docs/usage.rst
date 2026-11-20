Command-line usage
==================

Prepare scenario files
----------------------

Process files or every supported file directly inside a directory.

.. code-block:: console

   iam-prep-for-premise prepare INPUT... --output-dir OUTPUT

By default, ``prepare`` puts the table in a standard format and keeps the rows
listed in the export filter. Use ``--no-filter`` to keep every input row.
For a workbook with several scenarios, use ``--scenario LABEL`` and add
``--model LABEL`` when the same scenario name occurs under multiple models.
Use the exact labels shown by ``stock-inventory``.

Optional model adapters
-----------------------

Choose an adapter when you need the corrections it applies to your model's file.

.. code-block:: console

   iam-prep-for-premise prepare INPUT... --output-dir OUTPUT --adapter image \
       --medium-bev-sec VALUE --heavy-bev-sec VALUE
   iam-prep-for-premise prepare INPUT... --output-dir OUTPUT --adapter message
   iam-prep-for-premise prepare INPUT... --output-dir OUTPUT --adapter remind

The IMAGE adapter estimates transport use from energy use. Use ``--sec-config``
to load assumptions from YAML. Use ``--strict`` to stop if the calculation gives
a substantial negative value for battery-electric truck energy, or ``--skip-bev``
to skip that calculation.
MESSAGE processing strips ``R12_`` from region labels and removes ``GLB``.
REMIND processing removes legacy aggregate regions and splits cement production
and energy into CCS and non-CCS portions.

Stock vintages
--------------

List the input variables, check the YAML settings, and estimate the build-year groups.

.. code-block:: console

   iam-prep-for-premise stock-inventory scenario.csv -o stock-inventory.csv
   iam-prep-for-premise stock-config scenario.csv --mapping stock-mapping.yaml -o stocks.yaml
   iam-prep-for-premise stock-inventory scenario.csv --config stocks.yaml -o mapped-inputs.csv
   iam-prep-for-premise stock-vintages scenario.csv --config stocks.yaml \
       --output-dir output/stocks --package-only

The estimate depends on the IAM data and assumptions. ``stock-inventory`` can
list a file with several scenarios. Choose a single model and scenario before
making the settings file and running the calculation. See
``docs/stock-vintages.md`` for the method and limitations.

Filtering and cryptography
--------------------------

.. code-block:: console

   iam-prep-for-premise filter INPUT... --output-dir OUTPUT
   iam-prep-for-premise encrypt SOURCE DESTINATION [--key-file KEY]
   iam-prep-for-premise decrypt SOURCE DESTINATION [--key-file KEY]

Without ``--key-file``, these commands load ``PREMISE_KEY`` from the process
environment or the nearest ``.env`` file. ``IAM_PREPROCESSOR_KEY`` remains
supported for compatibility.

All writes protect existing files unless ``--overwrite`` is present.
