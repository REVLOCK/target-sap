class SapSftpError(Exception):
    """Base exception for SAP SFTP target with structured error handling.
    """

    def __init__(self, msg, response=None):
        """Initialize base SAP SFTP error with context information.
        
        Args:
            msg: Human-readable error description for logging and user display
            response: Optional response data from failed operation for debugging
        """
        super().__init__(msg)
        self.message = msg
        self.response = response

    def __str__(self):
        return repr(self.message)


class SftpConnectionError(SapSftpError):
    """SFTP connection establishment failure - network, authentication, or server issues."""


class SftpUploadError(SapSftpError):
    """File upload operation failure - transfer interrupted or server-side rejection.
 
    """


class MappingConfigError(SapSftpError):
    """Field mapping configuration error - invalid structure or missing required mappings."""


class SftpKeyError(SftpConnectionError):
    """Base SSH private key authentication error with diagnostic capabilities."""


class SftpKeyNotFoundError(SftpKeyError):
    """SSH private key content missing or empty - configuration issue."""


class SftpKeyFormatError(SftpKeyError):
    """SSH private key format invalid or unsupported by paramiko library."""


class SftpKeyPassphraseError(SftpKeyError):
    """SSH private key passphrase missing or incorrect for encrypted key."""
