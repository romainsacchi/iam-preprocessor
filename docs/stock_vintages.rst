Stock-vintage enrichment
========================

This workflow reconstructs the construction-year composition of an IAM stock.
The result is preliminary: it is derived from installed stock, additions,
lifetimes, and an explicit opening-stock assumption.

Install the stock dependencies and inspect the input coverage:

.. code-block:: console

   python -m pip install -e '.[stocks]'
   iam-preprocessor remind-stock-inventory scenario.mif -o stock-inventory.csv
   iam-preprocessor remind-stock-config scenario.mif -o stocks.yaml \
     --reconciliation joint

Build the canonical package:

.. code-block:: console

   iam-preprocessor stock-vintages scenario.mif --config stocks.yaml \
     -o output/stocks --package-only

The calculation proceeds through focused modules:

#. ``vintage_inputs`` selects exact IAM rows and produces annual series.
#. ``vintage_reconstruction`` prepares and reconstructs one asset.
#. ``stock_model`` applies survival and stock-flow accounting.
#. ``flodym_stock`` defines the lifetime models and runs the FLODyM stock solvers.
#. ``stock_annualisation`` reconciles stock anchors and additions in joint mode.
#. ``stock_vintages`` and ``stock_package`` assemble, validate, and write output.

FLODyM supplies the survival tables and projects cohorts from annual additions,
including additions fitted in joint mode. Its stock-driven solver handles
proportional, oldest-first, and hazard-scaled retirement. The joint fit uses
SciPy and OSQP to reconcile the IAM inputs. The stock extra pins the revision from `FLODyM PR #261
<https://github.com/pik-piam/flodym/pull/261>`_.

The package contains a sparse Parquet vintage table, ``validation.json``, and a
checksum-bound manifest. The processing report records the exact input,
configuration, assumptions, software versions, and numerical diagnostics.

See ``docs/stock-vintages.md`` in the repository for the equations, complete
configuration example, evidence labels, output contract, and limitations.
