Command-line usage
==================

IMAGE
-----

Process a file or every supported file directly inside a directory:

.. code-block:: console

   iam-preprocessor image INPUT... --output-dir OUTPUT \
       --medium-bev-sec VALUE --heavy-bev-sec VALUE

Use ``--sec-config`` to load reviewed assumptions from YAML, ``--strict`` to
reject material negative BEV residuals, and ``--skip-bev`` to disable that
derivation explicitly. Directory processing excludes names containing
``_filtered`` or ``_allocated`` to prevent accidental reprocessing.

MESSAGE and REMIND
------------------

.. code-block:: console

   iam-preprocessor message INPUT... --output-dir OUTPUT
   iam-preprocessor remind INPUT... --output-dir OUTPUT

MESSAGE processing derives mutually exclusive finished NG-DRI, NG-DRI+CCS,
and H-DRI steel routes from reported sponge-iron activity and aggregate DRI/EAF
steel output. It also removes exact duplicate rows, strips ``R12_`` from region
labels, and removes ``GLB``. The DRI split uses each scenario-year World
finished-steel-to-sponge-iron conversion factor and validates regional closure.
The NG-DRI residual is the existing non-H2/non-CCS inventory proxy and includes
MESSAGE's coal-without-CCS remainder because premise has no separate coal-DRI
inventory category.
REMIND processing removes legacy aggregate regions and splits cement production
and energy into CCS and non-CCS portions.

Filtering and cryptography
--------------------------

.. code-block:: console

   iam-preprocessor filter INPUT... --output-dir OUTPUT
   iam-preprocessor encrypt SOURCE DESTINATION [--key-file KEY]
   iam-preprocessor decrypt SOURCE DESTINATION [--key-file KEY]

Without ``--key-file``, these commands load ``PREMISE_KEY`` from the process
environment or the nearest ``.env`` file. ``IAM_PREPROCESSOR_KEY`` remains
supported for compatibility.

All writes protect existing files unless ``--overwrite`` is present.
