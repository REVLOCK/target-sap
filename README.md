# target-sap

A [Singer](https://www.singer.io/) / [hotglue](https://hotglue.xyz)-style target that reads journal entry data from CSV, transforms it to SAP journal entry format with dynamic grouping logic, and uploads the result as XLSX to an SFTP server.

## What it does
1. Reads `JournalEntries.csv` from a configured `input_path`.
2. Loads comprehensive field mappings from `mapping_config.json` (path configurable).
3. Applies dynamic grouping logic that assigns D1, D2, D3... values based on unique Posting Group IDs.
4. Builds SAP-compliant XLSX output with complete field mappings including company codes, account details, amounts, dates, and grouping identifiers.
5. Uploads the XLSX file to the remote path on SFTP using private key authentication.
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
| `sftp_private_key` | Private key content for SFTP authentication |
| `sftp_remote_path` | Remote directory where the output file is written (created if missing) |
| `input_path` | Local directory containing `JournalEntries.csv` |
Optional keys:
| Key | Default | Description |
| --- | --- | --- |
| `sftp_port` | `22` | SFTP port |
| `sftp_key_passphrase` | `""` | Passphrase for private key (if encrypted) |

SAP field values (used by `source: "config"` mappings):

| Key | SAP Field | Description |
| --- | --- | --- |
| `company_code` | Company Code (BUKRS) | SAP company code posted on every journal line (e.g. `CZ12`) |
| `document_type` | Document Type (BLART) | SAP document type (e.g. `FC` for journal entries) |
| `account_type` | Account Type (Koart) | SAP account type indicator (e.g. `S` for G/L account) |
| `profit_center` | Profit Center | SAP profit center assigned to every line (e.g. `1007`) |

## Dynamic Grouping Logic
The system implements dynamic grouping that assigns D1, D2, D3... values based on unique Posting Group IDs:
- Each unique Posting Group ID gets assigned a sequential D value (D1, D2, D3, etc.)
- All journal entries with the same Posting Group ID receive the same D value
- This ensures proper grouping of related journal entries in SAP

## Automatic File Naming
The system automatically generates unique output filenames with timestamps to prevent file overwrites:
- **Format**: `journal_entries_YYYYMMDD_HHMMSS.xlsx`
- **Example**: `journal_entries_20240423_143022.xlsx`
- **Benefits**: Multiple uploads per day without conflicts, clear upload timing identification

The mapping configuration is fixed to `./mapping_config.json` to ensure consistency across deployments.

### Example `config.json`
```json
{
  "sftp_host": "sap-server.example.com",
  "sftp_port": 22,
  "sftp_username": "sap_user",
  "sftp_private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n[Your private key content here]\n-----END OPENSSH PRIVATE KEY-----",
  "sftp_key_passphrase": "",
  "sftp_remote_path": "/incoming/journal_entries/",
  "input_path": "./data",
  "company_code": "CZ12",
  "document_type": "FC",
  "account_type": "S",
  "profit_center": "1007"
}
```
## Input CSV
The target always reads:
`<input_path>/JournalEntries.csv`
Every column referenced in `mapping_config.json` with `source` `column`, `transform`, `conditional`, or `grouping` must exist in that file. The default mapping expects Chargebee RevRec journal entry columns:
- `Transaction Date` - Used for posting and document dates
- `Account Number` - SAP account code
- `Amount` - Transaction amount in document currency
- `Currency Code` - Document currency (USD, EUR, etc.)
- `Account Name` - Account description
- `Posting Group Id` - **Key field for grouping logic** - generates D1, D2, D3... values
- `Posting Id` - Individual transaction identifier
- `Customer Id` - Customer reference
- `Product Id` - Product reference (mapped to Text_SGTXT)
- `Actg Period` - Accounting period
- `Accounting Event Type` - Type of accounting event (A/R, Revenue, Tax, etc.)

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
### `source: "config"`
Read a value from the runtime config file. Every row gets the same value, but the value is user-configurable rather than hardcoded in the mapping.
```json
"CompanyCode_BUKRS": {
  "source": "config",
  "config_key": "company_code"
}
```
### `source: "conditional"`
Copy a column value only when a condition column matches a specified value; outputs empty string otherwise.
```json
"TaxAmountLC_HWSTE": {
  "source": "conditional",
  "column": "Amount",
  "condition_column": "Accounting Event Type",
  "condition_value": "Tax"
}
```
### `source: "grouping"`
Assigns D1, D2, D3... values based on unique values in the specified column. All rows with the same value in the group_by_column get the same D identifier.
```json
"Grouping": {
  "source": "grouping",
  "group_by_column": "Posting Group Id"
}
```
This creates a sequential mapping where unique Posting Group IDs are assigned D1, D2, D3, etc., ensuring consistent grouping across related journal entries.

## SAP Output Fields
The current mapping configuration generates the following SAP journal entry fields:

| SAP Field | Description | Source Type | Notes |
|-----------|-------------|-------------|-------|
| `Grouping` | Document grouping (D1, D2, D3...) | grouping | Based on unique Posting Group IDs |
| `CompanyCode_BUKRS` | Company Code | config | From company_code config (e.g., CZ12) |
| `PostingDate_BUDAT` | Posting Date | column | Transaction Date in YYYYMMDD format |
| `DocumentDate_BLDAT` | Document Date | column | Transaction Date in YYYYMMDD format |
| `DocumentType_BLART` | Document Type | config | From document_type config (FC) |
| `DocumentHeaderText_BKTXT` | Document Header Text | static | Empty (pending implementation) |
| `Reference_XBLNR` | Reference | static | Empty (pending implementation) |
| `AccountCode` | Account/Vendor/Customer Code | column | From Account Number |
| `AccountType_Koart` | Account Type | config | From account_type config (S) |
| `AmountDC_WRBTR` | Amount in Document Currency | column | From Amount |
| `DocumentCurrency` | Document Currency | column | From Currency Code |
| `TaxCode` | Tax Code | static | Empty (pending implementation) |
| `TaxAmountDC_WMWST` | Tax Amount in Document Currency | static | Empty (pending implementation) |
| `BusinessArea` | Business Area | static | Empty (pending implementation) |
| `ProfitCenter` | Profit Center | config | From profit_center config (1007) |
| `Text_SGTXT` | Line Item Text | column | From Product Id |

### Pending Fields
Fields marked as "pending implementation" are currently set to empty strings and can be configured later based on business requirements for:
- Document header text rules
- Reference number generation
- Tax code mapping
- Tax amount calculations
- Business area assignment logic

## Run
```bash
target-sap --config config.json
```

### Example Output
The system generates XLSX output with columns like:
```
Grouping | CompanyCode_BUKRS | PostingDate_BUDAT | DocumentDate_BLDAT | DocumentType_BLART | AccountCode | AccountType_Koart | AmountDC_WRBTR | DocumentCurrency | ProfitCenter | ...
D1       | CZ12             | 20260327         | 20260327          | FC                | 10001      | S                | 113.67        | USD             | 1007        | ...
D1       | CZ12             | 20260329         | 20260329          | FC                | 20000      | S                | 10.83         | USD             | 1007        | ...
D2       | CZ12             | 20260328         | 20260328          | FC                | 30000      | S                | 10.00         | USD             | 1007        | ...
```

- All entries with the same Posting Group ID get the same `Grouping` value (D1, D2, etc.)
- Static configuration values are applied consistently across all rows
- Dates are formatted in SAP-compatible YYYYMMDD format
- Empty fields for pending implementations are set to empty strings

## Validation & Testing
The implementation includes comprehensive validation:
- **Grouping Algorithm**: Verifies unique Posting Group IDs are correctly mapped to D1, D2, D3... sequence
- **Field Mapping**: Validates all SAP fields are properly populated from source data or configuration
- **Data Consistency**: Ensures rows with the same Posting Group ID always get the same grouping value
- **Format Compliance**: Checks date formats (YYYYMMDD) and static value assignments

Example validation output:
```
INFO Created grouping for 'Grouping': 62 unique groups mapped to ['D1', 'D2', 'D3', ..., 'D62']
SUCCESS: All 62 unique groups correctly mapped to ['D1', 'D2', 'D3', ...]
```

## Project layout
- `src/target_sap/__init__.py` — entry point, field mapping logic, XLSX generation, SFTP upload orchestration
- `src/target_sap/client.py` — Paramiko SFTP client with private key authentication
- `src/target_sap/const.py` — required config keys and defaults
- `src/target_sap/exceptions.py` — `SftpConnectionError`, `SftpUploadError`, `MappingConfigError`
- `mapping_config.json` — complete SAP field mappings with grouping logic
- `config.json` — runtime configuration with SFTP and SAP settings
- `sample_config.json` — sample runtime config template

### Key Features Implemented
- **Dynamic Grouping**: Automatic D1, D2, D3... assignment based on unique Posting Group IDs
- **Complete SAP Mapping**: All standard SAP journal entry fields supported
- **XLSX Output**: Generates Excel format for SAP consumption
- **Private Key Auth**: Secure SFTP authentication using private keys
- **Flexible Configuration**: Config-driven field mappings and static values
## License
See `LICENSE` in the repository (GNU Affero General Public License v3 per `setup.cfg`).
