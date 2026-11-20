# Example scripts

## For a new scenario

- [stock-mapping.yaml](stock-mapping.yaml) shows how to choose input rows and
  state assumptions for a new scenario.
  Use it with the commands in the [main README](../README.md).
- [stock-mapping-remind.yaml](stock-mapping-remind.yaml) fills in 53 asset
  groups for REMIND 3.5.2 from 2005 through 2100. It uses stock mode, the
  reported lifetimes for capacity, and fixed retirement ages for vehicles.
  Starting ages follow the steady-additions assumption from the earlier
  REMIND runs.
- `validate_stock_output.py` compares the saved results with the input scenario
  and checks that the stock balance closes. Keep the `stocks.yaml` used for
  the run so this script can check the results from a short report.

## Research reproduction

These scripts repeat earlier REMIND runs. They need local scenario files and
observations. The export script also needs the corresponding version of `premise`.

- `run_remind_stock_pilot.py` runs the original REMIND example.
- `run_remind_sector_expansion.py` extends that pilot to more assets.
- `run_remind_evidence_validation.py` and `remind_evidence_campaign.yaml`
  reproduce the later evidence campaign.
- `export_sector_runtime_fixture.py` uses the archived CSV outputs to repeat the earlier premise trial.
- `plot_joint_annualisation.py` produces plots for the original pilot outputs.
- `build_remind_vehicle_opening_evidence.py` prepares starting ages for vehicles
  from UK registration data.
- `build_remind_jrc_vehicle_stock_run.py` prepares a 2005 starting-stock example
  using JRC-IDEES vehicle data. `report_remind_jrc_vehicle_stock_run.py` plots
  the results alongside an earlier run. Run `stock-vintages` with
  `--detailed-report` for these plots.
