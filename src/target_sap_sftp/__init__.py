import json
import sys
from pathlib import Path

import pandas as pd
import singer

from target_sap_sftp.client import get_client
from target_sap_sftp.const import (
    DEFAULT_OUTPUT_FILENAME,
    DEFAULT_SFTP_PORT,
    REQUIRED_CONFIG_KEYS,
)
from target_sap_sftp.exceptions import MappingConfigError

logger = singer.get_logger()


def load_mapping_config(config_path):
    """Load field mapping configuration from a JSON file."""
    path = Path(config_path)
    if not path.exists():
        raise MappingConfigError(f"Mapping config not found: {config_path}")

    with open(path) as f:
        mapping = json.load(f)

    if 'field_mappings' not in mapping:
        raise MappingConfigError("Mapping config must contain 'field_mappings' key")

    return mapping['field_mappings']


def apply_field_mapping(df, field_mappings):
    """Apply field mappings to transform input DataFrame into SAP CSV format.

    Supported mapping sources:
      - "column":    copies a column value directly, with optional date format
      - "static":    fills every row with a fixed value
      - "transform": maps source values through a lookup dictionary
    """
    result = pd.DataFrame()

    for sap_field, mapping in field_mappings.items():
        source = mapping.get('source')

        if source == 'column':
            col_name = mapping['column']
            if col_name not in df.columns:
                logger.error(f"Source column '{col_name}' not found for SAP field '{sap_field}'")
                sys.exit(1)

            if 'format' in mapping:
                result[sap_field] = pd.to_datetime(df[col_name]).dt.strftime(mapping['format'])
            else:
                result[sap_field] = df[col_name]

        elif source == 'static':
            result[sap_field] = mapping['value']

        elif source == 'transform':
            col_name = mapping['column']
            if col_name not in df.columns:
                logger.error(f"Source column '{col_name}' not found for SAP field '{sap_field}'")
                sys.exit(1)
            value_map = mapping['mapping']
            result[sap_field] = df[col_name].str.upper().map(value_map)
            unmapped = result[sap_field].isna()
            if unmapped.any():
                bad_values = df.loc[unmapped, col_name].unique().tolist()
                logger.warning(f"Unmapped values for '{sap_field}': {bad_values}")

        else:
            raise MappingConfigError(f"Unknown mapping source '{source}' for field '{sap_field}'")

    return result


def transform_to_sap_csv(config, field_mappings):
    """Read input JournalEntries.csv and transform to SAP CSV format."""
    input_path = f"{config['input_path']}/JournalEntries.csv"

    logger.info(f"Reading input CSV from {input_path}")
    df = pd.read_csv(input_path)
    logger.info(f"Loaded {len(df)} rows from input CSV")

    required_columns = {
        m['column']
        for m in field_mappings.values()
        if m.get('source') in ('column', 'transform')
    }
    missing = required_columns - set(df.columns)
    if missing:
        logger.error(f"Input CSV is missing required columns: {sorted(missing)}")
        sys.exit(1)

    sap_df = apply_field_mapping(df, field_mappings)
    logger.info(f"Transformed {len(sap_df)} rows into SAP CSV format")

    return sap_df


def upload(config):
    """Load CSV, transform to SAP format, and upload via SFTP."""
    logger.info('Starting upload.')

    mapping_path = config.get('mapping_config_path', './mapping_config.json')
    field_mappings = load_mapping_config(mapping_path)
    logger.info(f"Loaded field mappings: {list(field_mappings.keys())}")

    sap_df = transform_to_sap_csv(config, field_mappings)

    csv_content = sap_df.to_csv(index=False)

    sftp_client = get_client(
        host=config['sftp_host'],
        port=config.get('sftp_port', DEFAULT_SFTP_PORT),
        username=config['sftp_username'],
        password=config['sftp_password'],
    )

    filename = config.get('output_filename', DEFAULT_OUTPUT_FILENAME)
    remote_path = config['sftp_remote_path']

    with sftp_client:
        sftp_client.upload_csv(csv_content, remote_path, filename)

    logger.info('Upload completed')


@singer.utils.handle_top_exception(logger)
def main():
    args = singer.utils.parse_args(REQUIRED_CONFIG_KEYS)
    config = args.config
    upload(config)


if __name__ == '__main__':
    main()
