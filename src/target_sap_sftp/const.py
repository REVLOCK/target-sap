REQUIRED_CONFIG_KEYS = [
    'sftp_host',
    'sftp_username',
    'sftp_password',
    'sftp_remote_path',
    'input_path',
]

DEFAULT_SFTP_PORT = 22
DEFAULT_OUTPUT_FILENAME = 'journal_entries.csv'

SAP_CSV_COLUMNS = [
    'CompanyCode',
    'AccountCode',
    'PostingDate',
    'DocumentType',
    'Amount',
    'DebitCredit',
    'Description',
]
