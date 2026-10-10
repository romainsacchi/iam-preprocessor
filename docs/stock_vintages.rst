Stock-vintage enrichment
========================

Install ``iam-preprocessor[stocks]`` to use the optional flodym backend. The
runtime consumer does not need flodym. The supported local example uses REMIND
SSP2-NPi2025 for passenger BEVs, heavy trucks, PV and unabated CCGT.

.. code-block:: console

   iam-preprocessor stock-vintages scenario.mif --config stocks.yaml -o output/stocks

The command reads one model/scenario per file, checks exact variable names and
units, and appends annual variables under ``Stock Vintage|v1|``. Its report pins
source, observation and output hashes, software versions and assumptions.
``--filter-output`` keeps the enrichment namespace; ``--encrypt-to`` uses the
existing premise-compatible encryption workflow. Preserve the associated JSON
report and use the paired premise implementation branch.

Choose a stock-driven or inflow-driven reconstruction explicitly. Lifetimes
can come from a scenario variable or a declared prior, with either fixed or
Weibull survival. Initial observed survivors are conditioned on being alive at
the reference year. In stock mode, additional exits either raise an error or
follow an explicitly selected proportional-exit assumption.

Stock shares and service shares are distinct. Service weighting can use observed
relative cohort factors, an age-decay sensitivity and new-cohort service
exposure. Aggregate IAM service alone cannot identify relative cohort use.
Original inventory coefficients and common amortisation remain unchanged.

The complete YAML contract, equations, example and limitations are maintained in
``docs/stock-vintages.md`` in the repository. The reproducible local campaign and
acceptance checks are in ``docs/stock-vintage-validation.md``.
