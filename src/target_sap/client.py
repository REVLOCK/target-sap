import os

import paramiko
import singer

from target_sap.exceptions import SftpConnectionError, SftpUploadError

logger = singer.get_logger()


class SapSftpClient:
    """SFTP client for uploading CSV files to a SAP server."""

    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._transport = None
        self._sftp = None

    def connect(self):
        try:
            self._transport = paramiko.Transport((self.host, self.port))
            self._transport.connect(username=self.username, password=self.password)
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            logger.info(f"Connected to SFTP server {self.host}:{self.port}")
        except paramiko.AuthenticationException as e:
            raise SftpConnectionError(f"Authentication failed for {self.username}@{self.host}: {e}")
        except Exception as e:
            raise SftpConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def disconnect(self):
        if self._sftp:
            self._sftp.close()
        if self._transport:
            self._transport.close()
        logger.info("Disconnected from SFTP server")

    def upload_csv(self, csv_content, remote_path, filename):
        """Upload CSV string content to the SFTP server."""
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

    def _ensure_remote_dir(self, remote_path):
        """Create remote directory tree if it doesn't exist."""
        dirs_to_create = []
        current = remote_path
        while current and current != '/':
            try:
                self._sftp.stat(current)
                break
            except FileNotFoundError:
                dirs_to_create.append(current)
                current = os.path.dirname(current)

        for d in reversed(dirs_to_create):
            try:
                self._sftp.mkdir(d)
                logger.info(f"Created remote directory {d}")
            except IOError:
                pass

    def test_connection(self):
        """Verify SFTP connectivity and return True on success."""
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


def get_client(*, host, port, username, password):
    """Factory function to create a configured SapSftpClient."""
    return SapSftpClient(
        host=host,
        port=port,
        username=username,
        password=password,
    )
