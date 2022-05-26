import paramiko
import logging
import os
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from .webpath import WebPath


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(level=logging.DEBUG)


class ServerClient:
    def __init__(self, client):
        self.client = client

    @classmethod
    def ssh(cls):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return cls(ssh_client)

    def connect(self, **cfg):
        return ClientHandler(self.client, cfg)

    def sftp_connect(self, **cfg):
        return ClientSFTPHandler.from_config(self.client, cfg)


class Handler:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        self.close()


@contextmanager
def SFTPClient(**cfg):
    client = ServerClient.ssh()
    sftp_handler = client.sftp_connect(**cfg)
    try:
        yield sftp_handler.sftp
    finally:
        sftp_handler.close()



class ClientHandler(Handler):
    def __init__(self, client, config):
        self.client = client
        self.client.connect(**config)

    def close(self):
        self.client.close()

    def sftp(self):
        return SFTPHandler.from_transport(self.client.get_transport())


class TreeList(namedtuple("TreeList", "root paths")):
    @classmethod
    def from_walk(cls, walk, root):
        return cls(root, list(walk))

    @property
    def directories(self):
        return filter(lambda p: p.is_dir(), self.paths)

    @property
    def files(self):
        return filter(lambda p: p.is_file(), self.paths)

    @property
    def unknowns(self):
        return filter(lambda p: not (p.is_dir or p.is_file()), self.paths)

    def __contains__(self, path):
        return any(path == p for p in self.files)

    def _key(self, path):
        # * st_mtime is a float on a system, an int on the web
        # * stat.st_size can additionally be used for files
        #   but can be different on system and web
        stat = path.stat()
        rel = path.relative_to(self.root).as_posix()
        return (rel, int(stat.st_mtime))

    def _rel(self, path):
        return path.relative_to(self.root).as_posix()

    def diff(self, other):
        # Returns a new tree which contains the different paths
        paths = set(map(other._rel, other.paths))

        return self.__class__(
            self.root,
            list(map(lambda p: self._rel(p) not in paths, self.paths)),
        )

    def mod(self, other):
        # Returns a new tree which contains the modified paths
        paths = set(map(other._key, other.paths))

        return self.__class__(
            self.root,
            list(map(lambda p: self._key(p) not in paths, self.paths)),
        )


class SFTPHandler(paramiko.sftp_client.SFTPClient):
    _Path = WebPath

    def chdir(self, path=None):
        # Since _adjust_cwd is not exposed, we can't normalize paths
        raise NotImplementedError

    def open(self, filename, mode="rb", buffering=-1, encoding=None,
             errors=None, newline=None):

        return FileHandler(
            super().open(filename, mode=mode, bufsize=buffering),
            encoding, errors, newline)

    def _walk(self, path=".", recurse=True):
        for attr in self.listdir_attr(path):
            node = self._Path.from_attr(path, self, attr)
            yield node
            if recurse and node.is_dir():
                yield from self._walk(node.as_posix(), recurse)

    def listdir_r(self, path="."):
        for node in self._walk(path):
            yield node.as_posix()

    def _remote_tree(self, path="."):
        return TreeList.from_walk(self._walk(path), root=path)

    tree = _remote_tree

    def _local_tree(self, path="."):
        return TreeList.from_walk(Path(path).rglob("*"), root=path)

    def _copy_remote_time(self, localpath, remotepath):
        stat = self.stat(remotepath)
        os.utime(localpath, (stat.st_atime, stat.st_mtime))

    def _copy_local_time(self, localpath, remotepath):
        stat = os.stat(localpath)
        self.utime(remotepath, (stat.st_atime, stat.st_mtime))

    def Path(self, remotepath):
        return self._Path(Path(remotepath), self)

    def isdir(self, remotepath):
        # os.isdir == Path.is_dir
        # we just copy the naming conventions here
        try:
            return self.Path(remotepath).is_dir()
        except IOError: # no such file
            return False

    def get(self, remotepath, localpath, callback=None, prefetch=True,
            preserve_mtime=False):
        # Copied from https://bitbucket.org/dundeemt/pysftp

        super().get(remotepath, localpath, callback=callback,
            prefetch=prefetch)

        if preserve_mtime:
            self._copy_remote_time(localpath, remotepath)

    def get_r(self, remotepath, localpath, callback=None, prefetch=True,
            preserve_mtime=False):

        remotepath = Path(remotepath)
        localpath = Path(localpath)

        tree = self._remote_tree(remotepath.as_posix())

        for rd in tree.directories:
            ld = localpath / rd.relative_to(remotepath)
            ld.mkdir(exist_ok=True)
            if preserve_mtime:
                self._copy_remote_time(ld, rd)

        for rf in tree.files:
            lf = localpath / rf.relative_to(remotepath)
            self.get(rf, lf, callback=callback, prefetch=prefetch,
                preserve_mtime=preserve_mtime)

    def put(self, localpath, remotepath, callback=None, confirm=True,
            preserve_mtime=False):

        sftpattrs = super().put(localpath, remotepath, callback=callback,
                                confirm=confirm)
        logger.debug(f"Created {remotepath}")

        if preserve_mtime:
            self._copy_local_time(localpath, remotepath)
            sftpattrs = self.stat(remotepath)

        return sftpattrs

    def _put_tree(self, tree, remotepath, callback=None, confirm=True,
            preserve_mtime=False):

        for ld in tree.directories:
            rd = (remotepath / ld.relative_to(tree.root)).as_posix()
            if rd == '.':
                continue

            if not self.isdir(rd):
                logger.debug(f"Created {rd}")
                self.mkdir(rd)

            if preserve_mtime:
                self._copy_remote_time(ld, rd)

        for lf in tree.files:
            rf = (remotepath / lf.relative_to(tree.root)).as_posix()
            self.put(lf, rf, callback=callback, confirm=confirm,
                     preserve_mtime=preserve_mtime)

    def put_r(self, localpath, remotepath, callback=None, confirm=True,
            preserve_mtime=False):

        remotepath = Path(remotepath)
        localpath = Path(localpath)

        tree = self._local_tree(localpath)

        self._put_tree(tree, remotepath, callback=callback, confirm=confirm,
            preserve_mtime=preserve_mtime)

    def put_diff(self, localpath, remotepath, callback=None, confirm=True,
            preserve_mtime=True):
        rem_tree = self._remote_tree(remotepath)
        loc_tree = self._local_tree(localpath)

        # Modified tree
        tree = loc_tree.mod(rem_tree)

        self._put_tree(tree, remotepath, callback=callback, confirm=confirm,
            preserve_mtime=preserve_mtime)

    def rm(self):
        raise NotImplementedError

    def _rm_tree(self, tree):
        for rf in tree.files:
            self.remove(rf)

        for rd in reversed(tree.directories):
            self.rmdir(rd)

    def rm_r(self, remotepath, remove_root=False):
        tree = self._remote_tree(remotepath)

        self._rm_tree(tree)

        if remove_root:
            self.rmdir(remotepath)

    def rm_diff(self, localpath, remotepath):
        rem_tree = self._remote_tree(remotepath)
        loc_tree = self._local_tree(localpath)

        rm_tree = rem_tree.diff(loc_tree)
        self._rm_tree(rm_tree)


class ClientSFTPHandler(Handler):
    def __init__(self, client, sftp):
        self.client = client
        self.sftp = sftp

    @classmethod
    def from_config(cls, client, config):
        client = ClientHandler(client, config)
        sftp = client.sftp()

        return cls(client, sftp)

    def close(self):
        # close in reverse order
        self.sftp.close()
        self.client.close()


# overload paramiko.sftp_file.SFTPFile?
#  * tricky because the constructor is paramiko.sftp_client.SFTPClient.open
# FileHandler is missing a .prefetch attribute
class FileHandler(Handler):
    def __init__(self, file_handler, encoding, errors, newline):
        self.file_handler = file_handler
        self.encoding = encoding
        self.errors = errors
        self.newline = newline

    @property
    def prefetch(self):
        return self.file_handler.prefetch

    @property
    def _is_binary(self):
        return self.file_handler._flags & self.file_handler.FLAG_BINARY

    def close(self):
        self.file_handler.close()

    def read(self, size=None):
        # SFTPFile ignores binary/text flag, so we have to check it ourself
        text = self.file_handler.read(size)

        if not self._is_binary:
            text = text.decode(self.encoding)

        return text

    def write(self, text):
        if not self._is_binary:
            text = text.encode(self.encoding)

        self.file_handler.write(text)
