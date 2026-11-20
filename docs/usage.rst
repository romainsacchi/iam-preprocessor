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

The MESSAGE adapter removes exact duplicate rows, strips ``R12_`` from region
labels, and removes ``GLB``. It also splits reported finished DRI/EAF steel
into hydrogen, natural gas with CCS, and a remaining route. For each scenario
and year, it applies the global ratio of finished steel to sponge iron to
the reported regional hydrogen and gas-with-CCS sponge iron. If the file
lacks a global row, the ratio comes from regional totals. The remaining route
uses the natural-gas inventory in premise for both gas and coal without CCS.
The three routes add up to the reported total for every region and year.
The reported DRI/EAF energy use applies to the three routes together.

REMIND processing removes legacy aggregate regions and splits cement production
and energy into CCS and non-CCS portions.

TIAM-UCL hydrogen demand
------------------------

.. code-block:: console

   iam-prep-for-premise tiam-ucl INPUT... --output-dir OUTPUT

This command estimates hydrogen final-energy demand from reported finished
hydrogen-based DRI/EAF steel production. It converts production in Mt/yr to
hydrogen demand in PJ/yr using the hydrogen lower heating value of 120 GJ/t.
The default of 66.52317888 kg of hydrogen per tonne of finished steel comes
from the premise inventory. Set ``--h-dri-hydrogen-kg-per-tonne-steel`` to use a
different value. The report records the conversion and the intensity used.
The command keeps the transport-efficiency variants that TIAM-UCL reports
under shared variable names.

Stock vintages
--------------

List the input variables, check the YAML settings, and estimate the build-year groups.
The starter YAML applies each asset's settings to every region in the scenario.

.. code-block:: console

   iam-prep-for-premise stock-inventory scenario.csv -o stock-inventory.csv
   iam-prep-for-premise stock-config scenario.csv --mapping stock-mapping.yaml -o stocks.yaml
   iam-prep-for-premise stock-inventory scenario.csv --config stocks.yaml -o mapped-inputs.csv
   iam-prep-for-premise stock-vintages scenario.csv --config stocks.yaml \
       --output-dir output/stocks

The estimate depends on the IAM data and assumptions. ``stock-inventory`` can
list a file with several scenarios. Choose a single model and scenario before
making the settings file and running the calculation. The stock command reads
the reported year columns and writes a separate Parquet package and report. See
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
