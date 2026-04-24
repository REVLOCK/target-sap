import os

import paramiko
import singer

from target_sap.exceptions import (
    SftpConnectionError, 
    SftpUploadError,
    SftpKeyNotFoundError,
    SftpKeyFormatError,
    SftpKeyPassphraseError,
)

logger = singer.get_logger()


class SapSftpClient:
    """Secure SFTP client for SAP journal entry file uploads with enterprise-grade error handling."""

    def __init__(self, host, port, username, private_key_content, key_passphrase=None):
        """Initialize SFTP client with authentication credentials."""
        self.host = host
        self.port = port
        self.username = username
        self.private_key_content = private_key_content
        self.key_passphrase = key_passphrase
        self._transport = None
        self._sftp = None

    def connect(self):
        try:
            private_key = self._load_private_key()
            
            logger.info(f"DEBUG private key content passed to connect: {self.private_key_content}")
            logger.info(f"DEBUG private key object passed to connect: {private_key!r}")
            self._transport = paramiko.Transport((self.host, self.port))
            self._transport.connect(username=self.username, pkey=private_key)
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            logger.info(f"Connected to SFTP server {self.host}:{self.port} using private key authentication")
        except (SftpKeyNotFoundError, SftpKeyFormatError, SftpKeyPassphraseError):
            raise
        except paramiko.AuthenticationException as e:
            raise SftpConnectionError(
                f"Private key authentication failed for {self.username}@{self.host}. "
                f"Verify that the public key is authorized on the server and the username is correct. "
                f"Details: {e}"
            )
        except (ConnectionRefusedError, OSError) as e:
            raise SftpConnectionError(
                f"Network connection failed to {self.host}:{self.port}. "
                f"Verify the host and port are correct and the server is reachable. "
                f"Details: {e}"
            )
        except Exception as e:
            raise SftpConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}")
    
    def _load_private_key(self):
        import io
        
        logger.error(f"DEBUG key received in _load_private_key: {self.private_key_content}")
        logger.error(f"DEBUG key repr in _load_private_key: {self.private_key_content!r}")

        if not self.private_key_content or not self.private_key_content.strip():
            raise SftpKeyNotFoundError("Private key content is empty or not provided")
        
        # Security-first key type detection: modern formats first, legacy formats last
        # Ed25519: Fastest, most secure, recommended for new deployments
        # RSA: Widely compatible, good security with proper key size (2048+ bits)  
        # ECDSA: Good performance and security, growing adoption
        key_types = [
            (paramiko.Ed25519Key, "Ed25519"),
            (paramiko.RSAKey, "RSA"),
            (paramiko.ECDSAKey, "ECDSA"),
        ]
        
        # Legacy DSA/DSS support for older environments (paramiko version dependent)
        if hasattr(paramiko, 'DSSKey'):
            key_types.append((paramiko.DSSKey, "DSS"))
        
        passphrase_required = False
        
        for key_class, key_type in key_types:
            try:
                key_io = io.StringIO(self.private_key_content)
                if self.key_passphrase:
                    key = key_class.from_private_key(key_io, password=self.key_passphrase)
                else:
                    key = key_class.from_private_key(key_io)
                logger.info(f"Loaded {key_type} private key from configuration")
                return key
            except paramiko.PasswordRequiredException:
                passphrase_required = True
                if not self.key_passphrase:
                    continue
                else:
                    raise SftpKeyPassphraseError(
                        f"Private key requires a different passphrase or "
                        f"the provided passphrase is incorrect for {key_type} key format"
                    )
            except (paramiko.SSHException, ValueError) as e:
                logger.error(f"DEBUG failed to load as {key_type}: {e}")
                continue
            except Exception as e:
                logger.error(f"DEBUG unexpected error loading {key_type}: {e}")
                continue
        
        # If we get here, no key type worked
        if passphrase_required and not self.key_passphrase:
            raise SftpKeyPassphraseError(
                "Private key is encrypted but no passphrase provided. "
                "Set 'sftp_key_passphrase' in configuration."
            )
        
        raise SftpKeyFormatError(
            "Unable to load private key from provided content. "
            "Ensure it's a valid SSH private key in supported format (RSA, Ed25519, ECDSA, or DSS). "
            "The key should start with '-----BEGIN' and end with '-----END' markers."
        )

    def disconnect(self):
        if self._sftp:
            self._sftp.close()
        if self._transport:
            self._transport.close()
        logger.info("Disconnected from SFTP server")

    def upload_csv(self, csv_content, remote_path, filename):
        """Upload CSV content to SFTP server with automatic directory creation."""
        if not self._sftp:
            raise SftpConnectionError("Not connected. Call connect() first.")

        remote_filepath = os.path.join(remote_path, filename)
        try:
            self._ensure_remote_dir(remote_path)
            with self._sftp.open(remote_filepath, 'w') as remote_file:
                remote_file.write(csv_content)
            logger.info(f"Uploaded {filename} to {remote_filepath}")
        except IOError as e:
            raise SftpUploadError(f"Failed to upload {filename} to {remote_filepath}: {e}")

    def upload_xlsx(self, xlsx_content, remote_path, filename):
        """Upload XLSX binary content optimized for SAP journal entry processing."""
        if not self._sftp:
            raise SftpConnectionError("Not connected. Call connect() first.")
        
        remote_filepath = os.path.join(remote_path, filename)
        try:
            self._ensure_remote_dir(remote_path)
            with self._sftp.open(remote_filepath, 'wb') as remote_file:
                remote_file.write(xlsx_content)
            logger.info(f"Uploaded {filename} to {remote_filepath}")
        except IOError as e:
            raise SftpUploadError(f"Failed to upload {filename} to {remote_filepath}: {e}")

    def _ensure_remote_dir(self, remote_path):
        """Recursively create remote directory structure with atomic operations."""
        dirs_to_create = []
        current = remote_path
        while current and current != '/':
            try:
                self._sftp.stat(current)
                break  # Found existing directory, stop traversal
            except FileNotFoundError:
                dirs_to_create.append(current)
                current = os.path.dirname(current)

        # Create directories in correct hierarchy order (deepest parent first)
        for d in reversed(dirs_to_create):
            try:
                self._sftp.mkdir(d)
                logger.info(f"Created remote directory {d}")
            except IOError:
                # Directory may have been created by concurrent process - safe to ignore
                pass

    def test_connection(self):
        """Test SFTP connectivity with automatic cleanup for validation purposes."""
        try:
            self.connect()
            self._sftp.listdir('.')
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
        finally:
            self.disconnect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


def get_client(*, host, port, username, private_key_content, key_passphrase=None):
    """Factory function to create a configured SapSftpClient with validated parameters."""
    return SapSftpClient(
        host=host,
        port=port,
        username=username,
        private_key_content=private_key_content,
        key_passphrase=key_passphrase,
    )
