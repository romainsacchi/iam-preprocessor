# Example scripts

## For a new scenario

- [stock-mapping.yaml](stock-mapping.yaml) shows how to choose input rows and
  state assumptions for a new scenario.
  Use it with the commands in the [main README](../README.md).
- `validate_stock_output.py` compares the saved results with the input scenario
  and checks that the stock balance closes.

## Research reproduction

These scripts repeat earlier REMIND runs. They need local scenario files and
observations. The export script also needs the corresponding version of `premise`.

- `run_remind_stock_pilot.py` runs the original REMIND example.
- `run_remind_sector_expansion.py` extends that pilot to more assets.
- `run_remind_evidence_validation.py` and `remind_evidence_campaign.yaml`
  reproduce the later evidence campaign.
- `export_sector_runtime_fixture.py` uses the archived CSV outputs to repeat the earlier premise trial.
- `plot_joint_annualisation.py` produces plots for the original pilot outputs.
