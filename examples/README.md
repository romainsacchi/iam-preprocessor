# Example scripts

The examples are grouped by purpose below. Most scripts expect local IAM or
evidence files, which are intentionally not stored in Git.

## First stock-vintage run

- `run_remind_stock_pilot.py`: build a small reviewed REMIND pilot.
- `validate_stock_output.py`: inspect balances, shares, and package consistency.
- `plot_joint_annualisation.py`: visualize stock anchors and fitted additions.

Start with the command-line workflow in the main README when working with a new
scenario. The scripts are useful when reproducing the research setup.

## Coverage and evidence preparation

- `run_remind_sector_expansion.py`: extend the reviewed REMIND asset set.
- `export_sector_runtime_fixture.py`: create a small runtime test fixture.

## Validation campaign

- `run_remind_evidence_validation.py`: run historical evidence checks.

`remind_evidence_campaign.yaml` records campaign settings. Generated data and
figures belong under an ignored output directory rather than beside the scripts.
