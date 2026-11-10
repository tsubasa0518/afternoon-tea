"""Atomic JSON checkpoints and a process lock; no historical research store."""
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from afternoon_tea.collection.catalog import dumps

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(dumps(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

@contextmanager
def store_lock(directory):
    """Prevent overlapping local writers; kernel releases the lock on process exit."""
    import fcntl
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.lock').open('a') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('another_research_process_holds_store_lock')
        try:yield
        finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
