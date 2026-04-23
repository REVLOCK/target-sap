REQUIRED_CONFIG_KEYS = [
    'sftp_host',
    'sftp_username',
    'sftp_private_key',
    'sftp_remote_path',
    'input_path',
]

DEFAULT_SFTP_PORT = 22

SAP_CSV_COLUMNS = [
    'CompanyCode_BUKRS',
    'PostingDate_BUDAT',
    'DocumentDate_BLDAT',
    'DocumentType_BLART',
    'DocumentHeaderText_BKTXT',
    'Reference_XBLNR',
    'AccountCode',
    'AccountType_Koart',
    'SpecialGLInd_Umskz',
    'AmountLC_DMBTR',
    'AmountDC_WRBTR',
    'DocumentCurrency',
    'TaxCode',
    'TaxAmountLC_HWSTE',
    'TaxAmountDC_WMWST',
    'BusinessArea',
    'CostCenter',
    'InternalOrder',
    'ProfitCenter',
    'ValeurDate',
    'Text_SGTXT',
    'Assignment_ZUONR',
    'ReferenceKey1_XREF1',
    'ReferenceKey3_XREF3',
    'TradingPartner',
    'Period',
]
