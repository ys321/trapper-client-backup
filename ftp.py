import os
from ftplib import FTP, FTP_TLS, error_perm


class FTPS(FTP_TLS):
    """
    Explicit FTPS, with shared TLS session
    https://stackoverflow.com/questions/14659154/ftps-with-python-ftplib-session-reuse-required
    """

    def ntransfercmd(self, cmd, rest=None):
        conn, size = FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session
            )
        return conn, size


class FTPClient:
    server = None
    account = None
    password = None
    ftp = None
    port = 21
    connected = False

    def __init__(self, server, account, password, passive=True, tls=True):
        self.server = server
        self.account = account
        self.password = password
        self.passive = passive
        self.tls = tls
        self.ftp = None
        if len(server.split(":")) == 2:
            self.server, self.port = tuple(server.split(":"))
        try:
            self.port = int(self.port)
        except (TypeError, ValueError):
            self.port = 21

    def connect(self):
        if self.connected:
            self.close_connection()
        try:
            if self.tls:
                self.ftp = FTPS(timeout=None)
            else:
                self.ftp = FTP(timeout=None)
            self.ftp.connect(self.server, self.port)
            self.ftp.set_pasv(self.passive)
            self.ftp.login(self.account, self.password)
            if self.tls:
                self.ftp.prot_p()
            self.connected = True
        except error_perm:
            pass
        return self.connected

    def set_ftp_directory(self, directory="/collections"):
        try:
            self.ftp.cwd(directory)
        except IOError:
            self.ftp.mkd(directory)

    def upload(self, filepath, bsize=8192, callback=None, rest_pos=None):
        """ """
        filename = os.path.basename(filepath)
        cmd = "STOR " + filename
        file_obj = open(filepath, "rb")
        if rest_pos is not None:
            file_obj.seek(rest_pos, 0)
        self.ftp.storbinary(
            cmd, file_obj, blocksize=bsize, callback=callback, rest=rest_pos
        )

    def close_connection(self):
        self.ftp.quit()
        self.connected = False
