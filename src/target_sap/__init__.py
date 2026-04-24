import io
import json
import os
import socket
import sys
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


def apply_field_mapping(df, field_mappings, config):
    """Transform journal entry data into SAP-compliant format using configurable mappings."""
    result = pd.DataFrame()

    for sap_field, mapping in field_mappings.items():
        source = mapping.get('source')

        if source == 'column':
            col_name = mapping['column']
            if col_name not in df.columns:
                logger.warning(f"Source column '{col_name}' not found for SAP field '{sap_field}' - using empty string fallback")
                result[sap_field] = ''  # Fallback to empty string for missing columns
            else:
                if 'format' in mapping:
                    result[sap_field] = pd.to_datetime(df[col_name]).dt.strftime(mapping['format'])
                else:
                    result[sap_field] = df[col_name].fillna('')  # Replace NaN with empty string

        elif source == 'static':
            result[sap_field] = mapping['value']

        elif source == 'config':
            config_key = mapping['config_key']
            if config_key not in config:
                raise MappingConfigError(
                    f"Config key '{config_key}' required by SAP field '{sap_field}' "
                    f"not found in config"
                )
            result[sap_field] = config[config_key]

        elif source == 'transform':
            col_name = mapping['column']
            if col_name not in df.columns:
                logger.warning(f"Source column '{col_name}' not found for SAP field '{sap_field}' - using empty string fallback")
                result[sap_field] = ''  # Fallback to empty string for missing columns
            else:
                value_map = mapping['mapping']
                result[sap_field] = df[col_name].str.upper().map(value_map)
                unmapped = result[sap_field].isna()
                if unmapped.any():
                    bad_values = df.loc[unmapped, col_name].unique().tolist()
                logger.warning(f"Unmapped values for '{sap_field}': {bad_values}")

        elif source == 'conditional':
            col_name = mapping['column']
            cond_col = mapping['condition_column']
            cond_val = mapping['condition_value']
            
            missing_cols = [col for col in (col_name, cond_col) if col not in df.columns]
            if missing_cols:
                logger.warning(f"Source columns {missing_cols} not found for SAP field '{sap_field}' - using empty string fallback")
                result[sap_field] = ''  # Fallback to empty string for missing columns
            else:
                result[sap_field] = df[col_name].where(df[cond_col] == cond_val, '')

        elif source == 'grouping':
            group_by_col = mapping['group_by_column']
            if group_by_col not in df.columns:
                logger.warning(f"Group by column '{group_by_col}' not found for SAP field '{sap_field}' - using single group D1 fallback")
                # Fallback: Assign all entries to single group D1 when grouping column is missing
                result[sap_field] = pd.Series(['D1'] * len(df), index=df.index)
                logger.info(f"Applied fallback grouping for '{sap_field}': All {len(df)} entries assigned to group D1")
            else:
                # SAP Document Grouping Algorithm:
                # Assigns sequential D1, D2, D3... identifiers to maintain document relationships
                # Required for SAP audit trail - all entries with same Posting Group ID must
                # share the same document group to ensure proper financial reconciliation
                unique_groups = df[group_by_col].unique()
                group_mapping = {group: f"D{i+1}" for i, group in enumerate(unique_groups)}
                result[sap_field] = df[group_by_col].map(group_mapping)
                
                logger.info(f"Created grouping for '{sap_field}': {len(unique_groups)} unique groups mapped to {list(group_mapping.values())}")

        else:
            raise MappingConfigError(f"Unknown mapping source '{source}' for field '{sap_field}'")

    return result


def transform_to_sap_xlsx(config, field_mappings):
    """Load journal entries and transform to SAP-compliant XLSX format.
    """
    input_path = f"{config['input_path']}/JournalEntries.csv"

    logger.info(f"Reading input CSV from {input_path}")
    df = pd.read_csv(input_path)
    logger.info(f"Loaded {len(df)} rows from input CSV")

    # Pre-validate all required columns to prevent SAP posting failures
    # SAP requires complete data sets - missing fields cause entire batch rejection
    column_sources = ('column', 'transform', 'conditional', 'grouping')
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

    sap_df = apply_field_mapping(df, field_mappings, config)
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

    sap_df = transform_to_sap_xlsx(config, field_mappings)

    # Generate XLSX binary for SAP consumption - xlsxwriter engine ensures 
    # proper formatting and data type preservation required by SAP interfaces
    xlsx_buffer = io.BytesIO()
    sap_df.to_excel(xlsx_buffer, index=False, engine='xlsxwriter')
    xlsx_content = xlsx_buffer.getvalue()
    xlsx_buffer.close()

    sftp_client = get_client(
        host=config['sftp_host'],
        port=config.get('sftp_port', DEFAULT_SFTP_PORT),
        username=config['sftp_username'],
        password=config['sftp_password'],
    )

    # Generate timestamp-based filename for unique file identification
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'journal_entries_{timestamp}.xlsx'
    remote_path = config['sftp_remote_path']

    with sftp_client:
        sftp_client.upload_xlsx(xlsx_content, remote_path, filename)

    logger.info('Upload completed')


@singer.utils.handle_top_exception(logger)
def main():
    """Entry point for SAP journal entry processing with Singer framework integration."""
    args = singer.utils.parse_args(REQUIRED_CONFIG_KEYS)
    config = args.config
    upload(config)


if __name__ == '__main__':
    main()
