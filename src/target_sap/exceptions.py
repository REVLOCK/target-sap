class SapSftpError(Exception):
    """Base exception for SAP SFTP target."""

    def __init__(self, msg, response=None):
        super().__init__(msg)
        self.message = msg
        self.response = response

    def __str__(self):
        return repr(self.message)


class SftpConnectionError(SapSftpError):
    """Failed to connect to the SFTP server."""


class SftpUploadError(SapSftpError):
    """Failed to upload a file to the SFTP server."""


class MappingConfigError(SapSftpError):
    """Invalid or missing field mapping configuration."""


class SftpKeyError(SftpConnectionError):
    """SSH private key related error."""


class SftpKeyNotFoundError(SftpKeyError):
    """SSH private key file not found."""


class SftpKeyFormatError(SftpKeyError):
    """SSH private key format is invalid or unsupported."""


class SftpKeyPassphraseError(SftpKeyError):
    """SSH private key passphrase is required or incorrect."""
