import glob
import io
import json
import os
import socket
from datetime import datetime
from pathlib import Path

import pandas as pd
import singer

from target_sap.client import get_client
from target_sap.const import (
    DEFAULT_SFTP_PORT,
    REQUIRED_CONFIG_KEYS,
)
from target_sap.exceptions import MappingConfigError

logger = singer.get_logger()


def discover_input_files(input_dir):
    """Scan for entity-specific JournalEntries-<entityId>.csv files.

    Skips files with 'default' as entity ID (JournalEntries-default.*).
    Falls back to JournalEntries.csv first, then JournalEntries-default.csv 
    if no entity files are found.
    Returns a list of (file_path, entity_id) tuples where entity_id is
    None for the fallback case.
    """
    pattern = os.path.join(input_dir, 'JournalEntries-*.csv')
    entity_files = sorted(glob.glob(pattern))
    logger.info(f"Scanning input directory: {input_dir}")
    logger.info(f"Files in directory: {os.listdir(input_dir)}")


    if entity_files:
        results = []
        for fp in entity_files:
            basename = os.path.basename(fp)
            entity_id = basename[len('JournalEntries-'):-len('.csv')]
            if entity_id == 'default':
                logger.info(f"Skipping default file: {basename}")
                continue
                
            results.append((fp, entity_id))
            logger.info(f"Discovered entity file: {basename} (entity={entity_id})")
        
        if results:
            return results

    # Try fallback files in priority order
    fallback_files = [
        'JournalEntries.csv',
        'JournalEntries-default.csv'
    ]
    
    for fallback_file in fallback_files:
        fallback_path = os.path.join(input_dir, fallback_file)
        if os.path.exists(fallback_path):
            logger.info(f"No entity-specific files found, falling back to {fallback_file}")
            return [(fallback_path, None)]
        else:
            logger.info(f"Fallback file {fallback_file} not found")
    
    # If no fallback files exist, return the primary fallback anyway
    primary_fallback = os.path.join(input_dir, 'JournalEntries.csv')
    logger.warning(f"No fallback files found, returning {primary_fallback} (may not exist)")
    return [(primary_fallback, None)]


def load_mapping_config(config_path):
    """Load field mapping configuration defining SAP journal entry transformations."""
    path = Path(config_path)
    if not path.exists():
        raise MappingConfigError(f"Mapping config not found: {config_path}")

    with open(path) as f:
        mapping = json.load(f)

    if 'field_mappings' not in mapping:
        raise MappingConfigError("Mapping config must contain 'field_mappings' key")

    return mapping['field_mappings']


def _resolve_column(df, col_name, sap_field, numeric=False):
    """Return column series or None if missing (with warning logged)."""
    if col_name not in df.columns:
        logger.warning(f"Column '{col_name}' not found for '{sap_field}' - using fallback")
        return None
    series = df[col_name]
    if numeric:
        return pd.to_numeric(series, errors='coerce').fillna(0)
    return series


def _parse_config_json(config, config_key, sap_field):
    """Parse a config value as JSON, returning the parsed dict or None if empty."""
    raw = config.get(config_key, '')
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError) as e:
        raise MappingConfigError(
            f"Invalid JSON in config key '{config_key}' for '{sap_field}': {e}"
        )


def _handle_column(df, sap_field, mapping, config, entity_id):
    """Read a CSV column with optional date formatting, value mapping, or config-driven mapping."""
    col_name = mapping['column']
    fallback_col = mapping.get('fallback_column')
    empty = pd.Series('', index=df.index)

    # Resolve primary column; fall back to fallback_column if missing
    series = _resolve_column(df, col_name, sap_field)
    if series is None:
        if fallback_col:
            fallback = _resolve_column(df, fallback_col, sap_field)
            return fallback.fillna('') if fallback is not None else empty
        return empty

    if 'format' in mapping:
        return pd.to_datetime(series).dt.strftime(mapping['format'])

    # Value mapping: inline dict takes precedence, then config-driven
    value_map = mapping.get('mapping')
    if not value_map and 'mapping_config_key' in mapping:
        config_key = mapping['mapping_config_key']
        value_map = _parse_config_json(config, config_key, sap_field)
        if value_map is None:
            if fallback_col:
                fallback = _resolve_column(df, fallback_col, sap_field)
                if fallback is not None:
                    logger.info(f"Config key '{config_key}' is empty for '{sap_field}', using fallback column '{fallback_col}'")
                    return fallback.fillna('')
            logger.info(f"Config key '{config_key}' is empty for '{sap_field}' - using empty string")
            return empty

    if value_map:
        mapped = series.fillna('').map(value_map)
        unmapped = mapped.isna()
        if unmapped.any():
            bad_values = series.loc[unmapped].unique().tolist()
            logger.warning(f"Unmapped values for '{sap_field}': {bad_values}")
        return mapped.fillna('')

    return series.fillna('')


def _handle_static(df, sap_field, mapping, config, entity_id):
    """Set all rows to a hardcoded value."""
    return pd.Series(mapping['value'], index=df.index)


def _handle_config(df, sap_field, mapping, config, entity_id):
    """Set all rows to a config value, with optional JSON lookup by entity_id."""
    config_key = mapping['config_key']

    if 'json_lookup' in mapping:
        parsed = _parse_config_json(config, config_key, sap_field)
        if parsed is None:
            logger.info(f"Config key '{config_key}' is empty for '{sap_field}' - using empty string")
            return pd.Series('', index=df.index)

        lookup_key = mapping['json_lookup']
        if lookup_key == 'entity_id':
            if entity_id is None:
                logger.info(f"No entity_id available for '{sap_field}' - using empty string")
                return pd.Series('', index=df.index)
            value = parsed.get(entity_id, '')
            if value:
                logger.info(f"Config lookup for '{sap_field}': entity '{entity_id}' -> '{value}'")
            else:
                logger.warning(f"Entity '{entity_id}' not found in '{config_key}' for '{sap_field}' - using empty string")
            return pd.Series(value, index=df.index)

        raise MappingConfigError(f"Unknown json_lookup key '{lookup_key}' for '{sap_field}'")

    if config_key not in config:
        raise MappingConfigError(
            f"Config key '{config_key}' required by '{sap_field}' not found in config"
        )
    return pd.Series(config[config_key], index=df.index)


def _handle_signed_amount(df, sap_field, mapping, config, entity_id):
    """Numeric amount negated based on a sign column value."""
    amount = _resolve_column(df, mapping['column'], sap_field, numeric=True)
    sign = _resolve_column(df, mapping['sign_column'], sap_field)

    if amount is None or sign is None:
        return pd.Series('', index=df.index)

    negate_when = mapping['negate_when']
    return amount.where(
        sign.str.strip().str.upper() != negate_when.upper(),
        -amount
    )


def _handle_dual_column_amount(df, sap_field, mapping, config, entity_id):
    """Pick from debit/credit columns; negate the specified side."""
    debit = _resolve_column(df, mapping['debit_column'], sap_field, numeric=True)
    credit = _resolve_column(df, mapping['credit_column'], sap_field, numeric=True)

    if debit is None or credit is None:
        return pd.Series('', index=df.index)

    if mapping.get('negate', 'debit') == 'debit':
        return credit.where(credit > 0, -debit)
    return debit.where(debit > 0, -credit)


def _handle_conditional(df, sap_field, mapping, config, entity_id):
    """Include column value only when a condition column matches a value."""
    value_series = _resolve_column(df, mapping['column'], sap_field)
    cond_series = _resolve_column(df, mapping['condition_column'], sap_field)

    if value_series is None or cond_series is None:
        return pd.Series('', index=df.index)

    return value_series.where(cond_series == mapping['condition_value'], '')


def _handle_grouping(df, sap_field, mapping, config, entity_id):
    """Assign sequential D1, D2, D3... group identifiers by a grouping column."""
    group_col = mapping['group_by_column']
    series = _resolve_column(df, group_col, sap_field)

    if series is None:
        logger.info(f"Applied fallback grouping for '{sap_field}': all {len(df)} entries assigned to D1")
        return pd.Series('D1', index=df.index)

    unique_groups = series.unique()
    group_map = {group: f"D{i+1}" for i, group in enumerate(unique_groups)}
    logger.info(f"Created grouping for '{sap_field}': {len(unique_groups)} unique groups")
    return series.map(group_map)


def _handle_parse_middle(df, sap_field, mapping, config, entity_id):
    """Extract middle part from a space-separated string (e.g., '202601 A/R teya-cz' → 'A/R')."""
    series = _resolve_column(df, mapping['column'], sap_field)
    
    if series is None:
        return pd.Series('', index=df.index)
    
    def extract_middle_part(text):
        if pd.isna(text) or text == '':
            return ''
        try:
            parts = str(text).strip().split()
            if len(parts) >= 2:
                return parts[1]  # Return the middle part (index 1)
            return ''  # Skip if can't parse
        except Exception:
            return ''
    
    return series.apply(extract_middle_part)


SOURCE_HANDLERS = {
    'column': _handle_column,
    'static': _handle_static,
    'config': _handle_config,
    'signed_amount': _handle_signed_amount,
    'dual_column_amount': _handle_dual_column_amount,
    'conditional': _handle_conditional,
    'grouping': _handle_grouping,
    'parse_middle': _handle_parse_middle,
}


def apply_field_mapping(df, field_mappings, config, entity_id=None):
    """Transform journal entry data into SAP-compliant format using configurable mappings."""
    result = pd.DataFrame()

    for sap_field, mapping in field_mappings.items():
        source = mapping.get('source')
        handler = SOURCE_HANDLERS.get(source)
        if not handler:
            raise MappingConfigError(f"Unknown mapping source '{source}' for field '{sap_field}'")
        result[sap_field] = handler(df, sap_field, mapping, config, entity_id)
        
        # TODO: Remove this detailed field mapping logging after testing
        field_values = result[sap_field].tolist()
        logger.info(f"Processed SAP field '{sap_field}' (source: {source}): {json.dumps(field_values[:5], default=str)} {'... (truncated)' if len(field_values) > 5 else ''}")

    return result


def transform_to_sap_xlsx(csv_path, field_mappings, config, entity_id=None):
    """Load journal entries from a CSV file and transform to SAP-compliant XLSX format."""
    logger.info(f"Reading input CSV from {csv_path}")
    df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} rows from input CSV")
    
    # TODO: Remove this detailed input logging after testing
    logger.info(f"Input CSV columns: {list(df.columns)}")
    for idx, row in df.iterrows():
        input_row_data = {col: row[col] for col in df.columns}
        logger.info(f"Input row {idx} data: {json.dumps(input_row_data, default=str)}")
        if idx >= 4:  # Log only first 5 rows to avoid spam
            logger.info(f"... (logging limited to first 5 rows, total {len(df)} rows)")
            break

    # Pre-validate all required columns to prevent SAP posting failures
    # SAP requires complete data sets - missing fields cause entire batch rejection
    column_sources = ('column', 'conditional', 'grouping')
    required_columns = set()
    for m in field_mappings.values():
        if m.get('source') in column_sources:
            if 'column' in m:
                required_columns.add(m['column'])
            elif 'group_by_column' in m:
                required_columns.add(m['group_by_column'])
        if m.get('source') == 'conditional' and 'condition_column' in m:
            required_columns.add(m['condition_column'])

    missing = required_columns - set(df.columns)
    if missing:
        logger.warning(f"Input CSV is missing optional columns: {sorted(missing)} - will use fallback values")
        logger.info("Processing will continue with available columns and default values for missing data")

    sap_df = apply_field_mapping(df, field_mappings, config, entity_id=entity_id)
    logger.info(f"Transformed {len(sap_df)} rows into SAP XLSX format")

    return sap_df


def upload(config):
    """Complete SAP journal entry processing pipeline: load, transform, and upload.
    """
    logger.info('Starting upload.')

    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        logger.info(f"Running on host={hostname} ip={local_ip}")
    except Exception:
        logger.info("Running on host=unknown ip=unknown")

    mapping_path = os.path.join(os.path.dirname(__file__), 'mapping_config.json')
    field_mappings = load_mapping_config(mapping_path)
    logger.info(f"Loaded field mappings: {list(field_mappings.keys())}")

    input_files = discover_input_files(config['input_path'])
    logger.info(f"Found {len(input_files)} file(s) to process")

    date_stamp = datetime.now().strftime('%m%d%Y')
    remote_path = config['sftp_remote_path']

    sftp_client = get_client(
        host=config['sftp_host'],
        port=int(config.get('sftp_port', DEFAULT_SFTP_PORT)),
        username=config['sftp_username'],
        password=config['sftp_password'],
    )

    with sftp_client:
        for csv_path, entity_id in input_files:
            logger.info(f"Processing file: {csv_path}")
            sap_df = transform_to_sap_xlsx(csv_path, field_mappings, config, entity_id=entity_id)

            xlsx_buffer = io.BytesIO()
            sap_df.to_excel(xlsx_buffer, index=False, engine='xlsxwriter')
            xlsx_content = xlsx_buffer.getvalue()
            xlsx_buffer.close()

            if entity_id:
                filename = f'JournalEntries-{date_stamp}-{entity_id}.xlsx'
            else:
                filename = f'JournalEntries-{date_stamp}.xlsx'

            sftp_client.upload_xlsx(xlsx_content, remote_path, filename)
            logger.info(f"Uploaded {filename}")

    logger.info('Upload completed')


@singer.utils.handle_top_exception(logger)
def main():
    """Entry point for SAP journal entry processing with Singer framework integration."""
    args = singer.utils.parse_args(REQUIRED_CONFIG_KEYS)
    config = args.config
    upload(config)


if __name__ == '__main__':
    main()
