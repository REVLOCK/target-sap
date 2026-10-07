# target-sap-sftp

A [Singer](https://www.singer.io/) / [hotglue](https://hotglue.xyz)-style target that reads journal entry data from CSV, transforms it to SAP journal entry format, and uploads the result as XLSX to an SFTP server.

## What it does

1. Scans `input_path` for entity-specific CSV files (`JournalEntries-<entityId>.csv`). Falls back to `JournalEntries.csv` if none found.
2. Loads field mappings from `mapping_config.json` (bundled with the package).
3. Transforms each CSV into SAP-compliant XLSX using a registry-based mapping engine.
4. Uploads each file to SFTP as `JournalEntries-MMDDYYYY-<entityId>.xlsx`.

## Requirements

- Python 3.7+

## Install

```bash
pip install -e .
```

This installs the console script `target-sap-sftp`.

## Run

```bash
target-sap-sftp --config config.json
```

## Configuration

Create a JSON config file (see `sample_config.json`).

### Required keys

| Key | Description |
| --- | --- |
| `sftp_host` | SFTP server hostname |
| `sftp_username` | SFTP user |
| `sftp_password` | Password for SFTP authentication |
| `sftp_remote_path` | Remote directory where output files are written (created if missing) |
| `input_path` | Local directory containing input CSV files |

### Optional keys

| Key | Default | Description |
| --- | --- | --- |
| `sftp_port` | `22` | SFTP port |

### SAP field values

These are used by `source: "config"` mappings and applied to every row:

| Key | SAP Field | Example |
| --- | --- | --- |
| `document_type` | DocumentType (BLART) | `"FC"` |
| `account_type` | AccountType (Koart) | `"S"` |
| `profit_center` | ProfitCenter | `"1007"` |

### Config-driven lookup keys

These are optional JSON strings used for dynamic per-row or per-entity mappings:

| Key | Description | Example |
| --- | --- | --- |
| `company_code_mapping` | JSON mapping `Business Entity Id` values to CompanyCode (BUKRS). Empty string when no entity match. | `"{\"teya-cz\": \"CZ12\"}"` |
| `tax_code_mapping` | JSON mapping Product Id to tax codes. Falls back to the CSV `Tax Code` column when empty. | `"{\"product_a\": \"V1\"}"` |
| `business_area_mapping` | JSON mapping entity IDs to business area codes. Empty string when no entity match. | `"{\"teya-cz\": \"BA01\"}"` |

### Custom fields

The optional `custom_fields` key accepts an array of `{ "name": "...", "value": "..." }` objects. This allows passing behaviour-altering flags without adding new top-level config keys. The array and any individual field can be absent or null — all custom field handling is fully optional.

#### `skip_tax_code_for_accounts`

**Why it exists:** SAP requires that certain balance-sheet or clearing accounts (e.g., bank accounts, intercompany accounts) carry no tax code. Populating `TaxCode` for those accounts causes SAP to reject the posting. Rather than hard-coding account exclusions in the mapping config, this field lets you supply the list at runtime per-tenant without any code change.

**How it works:** After all field mappings have been applied, a post-processing step reads this value, splits it on commas, and sets `Tax Code` to an empty string for every row whose `Account Code` matches one of the listed accounts. Rows for accounts that are not in the list are unaffected.

| Field name | Value format | Example |
| --- | --- | --- |
| `skip_tax_code_for_accounts` | Comma-separated account codes | `"10100,20200,30300"` |

```json
"custom_fields": [
  {
    "name": "skip_tax_code_for_accounts",
    "value": "10100,20200,30300"
  }
]
```

#### `skip_tax_code_if_tax_amount_zero`

**Why it exists:** SAP rejects postings that carry a tax code but have no actual tax amount. When a journal entry's `Tax Amount DC WMWST` is zero, the tax code should not be populated even if the product type mapping would normally assign one. This flag lets you enable that behaviour at runtime without changing the mapping config.

**How it works:** After all field mappings have been applied (including the `skip_tax_code_for_accounts` step), a post-processing step checks this flag. If it is present and truthy, `Tax Code` is set to an empty string for every row whose `Tax Amount DC WMWST` is zero (absolute value). Rows with a non-zero tax amount are unaffected.

| Field name | Value format | Example |
| --- | --- | --- |
| `skip_tax_code_if_tax_amount_zero` | Any non-empty truthy string enables the behaviour | `"true"` |

```json
"custom_fields": [
  {
    "name": "skip_tax_code_if_tax_amount_zero",
    "value": "true"
  }
]
```

### Example `config.json`

```json
{
  "sftp_host": "sap-server.example.com",
  "sftp_port": 22,
  "sftp_username": "sap_user",
  "sftp_password": "your_password_here",
  "sftp_remote_path": "/incoming/journal_entries/",
  "input_path": "./data",
  "document_type": "FC",
  "account_type": "S",
  "profit_center": "1007",
  "company_code_mapping": "{\"teya-cz\": \"CZ12\", \"teya-sk\": \"CZ12\"}",
  "tax_code_mapping": "{\"product_a\": \"V1\", \"product_b\": \"V2\"}",
  "business_area_mapping": "{\"teya-cz\": \"BA01\", \"teya-sk\": \"BA02\"}",
  "custom_fields": [
    {
      "name": "skip_tax_code_for_accounts",
      "value": "10100,20200,30300"
    }
  ]
}
```

## Input files

### Multi-entity processing

The target scans `input_path` for files matching `JournalEntries-<entityId>.csv`:

```
data/
  JournalEntries-teya-cz.csv   ->  JournalEntries-04272026-teya-cz.xlsx
  JournalEntries-teya-sk.csv   ->  JournalEntries-04272026-teya-sk.xlsx
```

If no entity-specific files are found, it falls back to `JournalEntries.csv` and outputs `JournalEntries-MMDDYYYY.xlsx`.

The entity ID extracted from the filename is used by `config` mappings with `json_lookup: "entity_id"` (e.g., BusinessArea).

### Expected CSV columns

| Column | Used by |
| --- | --- |
| `Transaction Date` | PostingDate, DocumentDate (formatted as M/D/YYYY) |
| `Account Number` | AccountCode |
| `Amount` | AmountDC_WRBTR (negated when Type is Debit) |
| `Type` | Sign column for AmountDC_WRBTR |
| `Currency Code` | DocumentCurrency |
| `Posting Group Id` | Grouping (D1, D2, ...) and DocumentHeaderText |
| `Accounting Event Type` | Reference_XBLNR |
| `Product Id` | Text_SGTXT and TaxCode lookup key |
| `Tax Code` | TaxCode fallback column |
| `Debit Tax` | TaxAmountDC_WMWST (negated) |
| `Credit Tax` | TaxAmountDC_WMWST (positive) |

Missing columns are handled gracefully with warnings and empty string fallbacks.

## Field mapping engine (`mapping_config.json`)

The mapping file contains a top-level `field_mappings` object. Each key is an output column name; the value describes how to populate it. The engine uses a handler registry -- each source type is a separate function, making it easy to extend.

### `source: "column"`

Read a CSV column. Supports optional modifiers that can be combined:

**Basic column copy:**

```json
"AccountCode": {
  "source": "column",
  "column": "Account Number"
}
```

**With date formatting** (`format` -- strftime syntax):

```json
"PostingDate_BUDAT": {
  "source": "column",
  "column": "Transaction Date",
  "format": "%-m/%-d/%Y"
}
```

**With inline value mapping** (`mapping` -- replaces the old `transform` type):

```json
"DebitCredit": {
  "source": "column",
  "column": "Type",
  "mapping": { "DEBIT": "H", "CREDIT": "S" }
}
```

**With config-driven value mapping** (`mapping_config_key` -- replaces the old `config_key_lookup` type):

```json
"TaxCode": {
  "source": "column",
  "column": "Product Id",
  "mapping_config_key": "tax_code_mapping",
  "fallback_column": "Tax Code"
}
```

When `mapping_config_key` is provided, the config value is parsed as JSON and used as the mapping dict. If the config key is empty/missing, `fallback_column` is read instead. If neither is available, empty string is used.

### `source: "static"`

Same value for every row.

```json
"DocumentHeaderText_BKTXT": {
  "source": "static",
  "value": ""
}
```

### `source: "config"`

Read a value from the runtime config. Every row gets the same value.

```json
"DocumentType_BLART": {
  "source": "config",
  "config_key": "document_type"
}
```

**With JSON lookup** (`json_lookup` -- replaces the old `config_entity_lookup` type):

```json
"BusinessArea": {
  "source": "config",
  "config_key": "business_area_mapping",
  "json_lookup": "entity_id"
}
```

When `json_lookup: "entity_id"` is set, the config value is parsed as JSON and the current file's entity ID is used as the lookup key. If the entity ID is not found or the config is empty, empty string is used.

### `source: "signed_amount"`

Numeric amount from one column, negated when a sign column matches a specified value.

```json
"AmountDC_WRBTR": {
  "source": "signed_amount",
  "column": "Amount",
  "sign_column": "Type",
  "negate_when": "Debit"
}
```

### `source: "dual_column_amount"`

Pick from two columns (debit/credit); negate the specified side.

```json
"TaxAmountDC_WMWST": {
  "source": "dual_column_amount",
  "debit_column": "Debit Tax",
  "credit_column": "Credit Tax",
  "negate": "debit"
}
```

If `Debit Tax > 0`, the value is negated. If `Credit Tax > 0`, it is used as-is.

### `source: "conditional"`

Include a column value only when a condition column matches a specified value; empty string otherwise.

```json
"TaxAmountLC_HWSTE": {
  "source": "conditional",
  "column": "Amount",
  "condition_column": "Accounting Event Type",
  "condition_value": "Tax"
}
```

### `source: "grouping"`

Assigns sequential D1, D2, D3... identifiers based on unique values in the specified column.

```json
"Grouping": {
  "source": "grouping",
  "group_by_column": "Posting Group Id"
}
```

## SAP output fields

The current `mapping_config.json` produces these output columns:

| SAP Field | Source | Details |
| --- | --- | --- |
| Grouping | grouping | Sequential D1, D2... by Posting Group Id |
| CompanyCode_BUKRS | config | `company_code` |
| PostingDate_BUDAT | column | Transaction Date as M/D/YYYY |
| DocumentDate_BLDAT | column | Transaction Date as M/D/YYYY |
| DocumentType_BLART | config | `document_type` |
| DocumentHeaderText_BKTXT | column | Posting Group Id |
| Reference_XBLNR | column | Accounting Event Type |
| AccountCode | column | Account Number |
| AccountType_Koart | config | `account_type` |
| AmountDC_WRBTR | signed_amount | Amount, negated when Type is Debit |
| DocumentCurrency | column | Currency Code |
| TaxCode | column | Product Id mapped via `tax_code_mapping`, fallback to Tax Code column |
| TaxAmountDC_WMWST | dual_column_amount | Debit Tax (negated) or Credit Tax |
| BusinessArea | config | `business_area_mapping` looked up by entity ID |
| ProfitCenter | config | `profit_center` |
| Text_SGTXT | column | Product Id |

## Architecture

### Handler registry

The mapping engine uses a `SOURCE_HANDLERS` dictionary that maps source type names to handler functions. Each handler has the signature:

```python
def _handle_<type>(df, sap_field, mapping, config, entity_id) -> pd.Series
```

Adding a new source type requires writing one function and adding one entry to the registry dict. No changes to the main loop are needed.

### Shared helpers

- `_resolve_column(df, col_name, sap_field, numeric=False)` -- checks if a column exists, logs a warning if missing, optionally coerces to numeric.
- `_parse_config_json(config, config_key, sap_field)` -- parses a config value as JSON with error handling.
- `_get_custom_field(config, field_name)` -- safely retrieves a named value from the `custom_fields` array; returns `None` if the array is absent or the field is not present.
- `_apply_skip_tax_code(sap_df, config)` -- post-processing step that reads `skip_tax_code_for_accounts` via `_get_custom_field` and blanks `Tax Code` for any row whose `Account Code` is in the list.
- `_apply_skip_tax_code_if_zero(sap_df, config)` -- post-processing step that reads `skip_tax_code_if_tax_amount_zero` via `_get_custom_field` and blanks `Tax Code` for any row whose `Tax Amount DC WMWST` is zero.

### Processing pipeline

```
discover_input_files()
  -> for each (csv_path, entity_id):
       transform_to_sap_xlsx()
         -> pd.read_csv()
         -> apply_field_mapping()          # loops through SOURCE_HANDLERS
         -> _apply_skip_tax_code()         # clears Tax Code for excluded accounts
         -> _apply_skip_tax_code_if_zero() # clears Tax Code when tax amount is zero
       -> to_excel() as XLSX buffer
       -> sftp_client.upload_xlsx()
```

## Project layout

| Path | Description |
| --- | --- |
| `src/target_sap/__init__.py` | Entry point, mapping engine, XLSX generation, SFTP upload |
| `src/target_sap/client.py` | Paramiko SFTP client with password authentication |
| `src/target_sap/const.py` | Required config keys and defaults |
| `src/target_sap/exceptions.py` | `SftpConnectionError`, `SftpUploadError`, `MappingConfigError` |
| `src/target_sap/mapping_config.json` | SAP field mapping definitions |
| `sample_config.json` | Example runtime config |

## License

GNU Affero General Public License v3 (see `LICENSE`).
