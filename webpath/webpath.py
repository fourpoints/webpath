import logging
import io
from paramiko import sftp, sftp_attr, sftp_file


from stat import S_ISDIR, S_ISREG

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(level=logging.DEBUG)


class WebPath:
    """Partially copies the interface of pathlib.Path"""
    # Everywhere with __fspath__ should be removed once paramiko supports
    # the Path interface
    def __init__(self, path, accessor=None, stat=None):
        # Reference to the sftp handler is necessary; in pathlib this is
        # equivalent to a reference to the os module; but this module is
        # assumed to be a singleton since it's unexpected for the os to
        # change when running a Python script. In comparison a webpath
        # can refer to different sources.

        # In pathlib _accessor is a union of io and os. open() uses the io
        # module, while mkdir() and touch() uses os.
        self._path = path
        self._accessor = accessor  # sftp handler
        self._stat = stat  # cached stat

    @classmethod
    def from_attr(cls, parent, accessor=None, stat=None):
        return cls(Path(parent) / stat.filename, accessor, stat)

    def stat(self):
        if self._stat is None:
            self._stat = self._accessor.stat(self._path.__fspath__())
        return self._stat

    def _reset_stat(self):
        self._stat = None  # reset cache

    @property
    def parent(self):
        return self._path.parent

    @property
    def name(self):
        return self._path.name

    def as_posix(self):
        return self._path.as_posix()

    def relative_to(self, ancestor):
        # loses stat information
        return self.__class__(self._path.relative_to(ancestor), self._system)

    def __repr__(self):
        return f"{self.__class__.__name__}('{self.as_posix()}')"

    def __str__(self):
        return self.as_posix()

    # Required for PathLike objects
    def __fspath__(self):
        return str(self)

    def __lt__(self, other):
        return str(self) < str(other)

    def __truediv__(self, other):
        return self.__class__(self._path / other, self._accessor)

    @property
    def _mode(self):
        return self.stat().st_mode

    def is_dir(self):
        try:
            return S_ISDIR(self._mode)
        except FileNotFoundError:
            return False

    def is_file(self):
        try:
            return S_ISREG(self._mode)
        except FileNotFoundError:
            return False

    def open(self, mode="rb", buffering=-1, encoding=None,
             errors=None, newline=None):
        self._reset_stat()
        return self._accessor.open(self.__fspath__(), mode, buffering, encoding,
                                   errors, newline)

    def read_text(self, encoding=None, errors=None):
        encoding = io.text_encoding(encoding)
        with self.open("rt", encoding=encoding, errors=errors) as f:
            return f.read()

    def write_text(self, data, encoding=None, errors=None, newline=None):
        encoding = io.text_encoding(encoding)
        # This is PEP8 compliant
        with self.open(mode='w', encoding=encoding, errors=errors, newline=newline) as f:
            return f.write(data)

    def read_bytes(self):
        with self.open("rb") as f:
            return f.read()

    def write_bytes(self, data):
        with self.open("wb") as f:
            return f.write(data)

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        assert parents is False, "parents argument is not supported"
        self._reset_stat()
        self._accessor.mkdir(self.__fspath__())

    def rmdir(self):
        self._reset_stat()
        self._accessor.rmdir(self.__fspath__())

    def touch(self, mode=0o666, exist_ok=True):
        self._reset_stat()
        # Apparently there's no such thing as touch, only open
        # Note that exist_ok is True for touch, but False for mkdir

        flags = sftp.SFTP_FLAG_CREATE | sftp.SFTP_FLAG_WRITE
        if not exist_ok:
            flags |= sftp.SFTP_FLAG_EXCL

        attrblock = sftp_attr.SFTPAttributes()
        t, msg = self._accessor._request(
            sftp.CMD_OPEN, self.__fspath__(), flags, attrblock)

        if t != sftp.CMD_HANDLE:
            raise sftp.SFTPError("Expected handle")

        handle = msg.get_binary()

        try:
            self._accessor._request(sftp.CMD_CLOSE, handle)
        except Excpetion as e:
            pass

    def unlink(self):
        self._reset_stat()
        self._accessor.remove(self.__fspath__())
