# target-sap

A [Singer](https://www.singer.io/) / [hotglue](https://hotglue.xyz)-style target that reads journal entry data from CSV, maps columns to a SAP-oriented layout, and uploads the result to an SFTP server (for example, a drop folder SAP consumes).
## What it does
1. Reads `JournalEntries.csv` from a configured `input_path`.
2. Loads field rules from `mapping_config.json` (path configurable).
3. Builds an output CSV with the columns you define in the mapping (defaults align with a common SAP journal layout: company code, account, posting date, document type, amount, debit/credit indicator, text).
4. Uploads that file to the remote path on SFTP using password authentication.
## Requirements
- Python 3.7+
## Install
From the repository root:
```bash
pip install -e .
```
This installs the console script `target-sap`.
## Configuration
Create a JSON config file (see `sample_config.json`). The following keys are **required**:
| Key | Description |
| --- | --- |
| `sftp_host` | SFTP server hostname |
| `sftp_username` | SFTP user |
| `sftp_password` | SFTP password |
| `sftp_remote_path` | Remote directory where the output file is written (created if missing) |
| `input_path` | Local directory containing `JournalEntries.csv` |
Optional keys:
| Key | Default | Description |
| --- | --- | --- |
| `sftp_port` | `22` | SFTP port |
| `mapping_config_path` | `./mapping_config.json` | Path to the mapping JSON |
| `output_filename` | `journal_entries.csv` | Remote (and logical) output file name |
### Example `config.json`
```json
{
  "sftp_host": "sap-server.example.com",
  "sftp_port": 22,
  "sftp_username": "sap_user",
  "sftp_password": "your_password",
  "sftp_remote_path": "/incoming/journal_entries/",
  "input_path": "/data/input/",
  "mapping_config_path": "./mapping_config.json",
  "output_filename": "journal_entries.csv"
}
```
## Input CSV
The target always reads:
`<input_path>/JournalEntries.csv`
Every column referenced in `mapping_config.json` with `source` `column` or `transform` must exist in that file. Typical columns (matching the default mapping) include:
- `Transaction Date`
- `Account Number`
- `Amount`
- `Posting Type` (e.g. `DEBIT` / `CREDIT`, case-insensitive for mapping)
- `Description`
Add or rename columns in the mapping file if your source file differs.
## Field mapping (`mapping_config.json`)
The file must contain a top-level `field_mappings` object. Each key is an **output column name**; the value describes how to fill it.
### `source: "column"`
Copy from an input column. Optional `format` uses [strftime](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior) after parsing with pandas (e.g. `"%Y%m%d"` for `YYYYMMDD`).
```json
"PostingDate": {
  "source": "column",
  "column": "Transaction Date",
  "format": "%Y%m%d"
}
```
### `source: "static"`
Same value for every row.
```json
"CompanyCode": {
  "source": "static",
  "value": "1000"
}
```
### `source: "transform"`
Map normalized uppercase source values to output codes (e.g. debit/credit indicators).
```json
"DebitCredit": {
  "source": "transform",
  "column": "Posting Type",
  "mapping": {
    "DEBIT": "H",
    "CREDIT": "S"
  }
}
```
Unmapped values produce `NaN` in the output and a warning in the log; extend `mapping` as needed.
## Run
```bash
target-sap --config config.json
```
## Project layout
- `src/target_sap/__init__.py` — entry point, mapping, CSV build, upload orchestration
- `src/target_sap/client.py` — Paramiko SFTP client
- `src/target_sap/const.py` — required config keys and defaults
- `src/target_sap/exceptions.py` — `SftpConnectionError`, `SftpUploadError`, `MappingConfigError`
- `mapping_config.json` — default mapping (edit for your SAP layout)
- `sample_config.json` — sample runtime config
## License
See `LICENSE` in the repository (GNU Affero General Public License v3 per `setup.cfg`).
