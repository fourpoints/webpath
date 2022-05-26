# webpath
Path/os-like interface to SFTP using paramiko.

## Example

```python
from webpath import SFTPClient
from getpass import getpass

config = dict(
    hostname="sftp.example.com",
    port=22,
    username="website",
    password=getpass(),
)

with SFTPClient(**config) as sftp:
    path = sftp.Path("/root/")
    print(path.is_dir())  # True, assuming this exists
    
    # Create dir
    ndir = path / "hello"
    print(ndir.is_dir())  # False
    fpath.mkdir()
    print(ndir.is_dir())  # True
    
    # Create file
    fpath = path / "world.txt"
    print(fpath.is_file())  # False
    fpath.touch()
    print(fpath.is_file())  # True
    
    # Write to file
    print(fpath.read_text(encoding="utf-8"))  # ""
    fpath.write_text("Hello world", encoding="utf-8")
    print(fpath.read_text(encoding="utf-8"))  # "Hello world"
    
    # Alternatively
    with fpath.open(mode="wt", encoding="utf-8") as f:
        f.write("Hello world")
    
    # Remove file and directory
    fpath.unlink()
    print(fpath.is_file())  # False
    ndir.rmdir()
    print(ndir.is_dir())  # False
    
    # Clone (recursively) local directory source onto remote directory target
    sftp.put_r("C:/users/user/documents/site/", "/root")
    # To go the other way, use sftp.get_r(remote_root, local_root)
    
    # Remove a remote directory (recursively)
    sftp.rm_r("/root")  # Don't do this in production
    
    # Clone (recursively) local files that are new or have been modified to remote directory, relative to root
    # A file is modified if int(path.stat().st_mtime()) are different.
    sftp.put_diff(local_root, "/root")
    
    # Remove (recursively) remote files that does not exist in the local directory, relative to root
    sftp.rm_diff(local_root, remote_root)
```

`sftp` is an `SFTPHandler` object, which is a subclass of `paramiko.sftp_client.SFTPClient`. For more properties, read the [SFTPClient Documentation](https://docs.paramiko.org/en/stable/api/sftp.html).

One notable exception is that `chdir` has been removed, so `SFTPHandler` only handles absolute paths.
