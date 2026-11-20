Stock vintages
==============

This workflow estimates when the assets in use in each year were built. It uses
installed stock, additions, lifetimes, and information about the assets already
in use at the start. The estimates are preliminary.

Install the tools, list the input variables, and check the stock settings.
The starter YAML uses the same asset settings for every region in the scenario.

.. code-block:: console

   python -m pip install -e '.[stocks]'
   iam-prep-for-premise stock-inventory scenario.csv -o stock-inventory.csv
   iam-prep-for-premise stock-config scenario.csv --mapping stock-mapping.yaml -o stocks.yaml

Calculate and save the build-year estimates.

.. code-block:: console

   iam-prep-for-premise stock-vintages scenario.csv --config stocks.yaml \
     -o output/stocks

The calculation uses these Python modules.

#. ``vintage_inputs`` reads the selected rows and fills in missing years.
#. ``vintage_reconstruction`` estimates the build-year groups for one asset.
#. ``stock_model`` tracks the stock as assets are added or retired.
#. ``flodym_stock`` uses FLODyM to calculate how much stock survives.
#. ``stock_annualisation`` fits annual additions to the reported values in joint mode.
#. ``stock_vintages`` and ``stock_package`` check and save the results.

FLODyM tracks what survives and what retires for each build-year group. The
joint fit uses SciPy and OSQP to estimate annual additions from the IAM input.
The installation above uses the revision from
`FLODyM PR #261 <https://github.com/pik-piam/flodym/pull/261>`_.

The separate Parquet table contains the build-year estimates. The run report shows which
inputs and settings were used and where the estimates differ from the input data.

See ``docs/stock-vintages.md`` for the equations, example settings, output
formats, and limitations.
