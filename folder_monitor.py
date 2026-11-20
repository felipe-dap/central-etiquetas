"""Watchdog notifications + stable-file debounce, independent of Tk."""
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

def signature(folder):
    folder=Path(folder)
    result=[]
    for path in sorted(folder.iterdir(),key=lambda p:p.name.lower()):
        if path.is_file() and path.suffix.lower() in ('.pdf','.crdownload','.part','.tmp'):
            stat=path.stat();result.append((path.name,stat.st_size,stat.st_mtime_ns))
    return tuple(result)

class StableChanges:
    def __init__(self,delay=3):
        self.delay=delay;self.candidate=None;self.since=0;self.handled=None;self.dirty=True
    def touch(self,now):
        self.dirty=True;self.since=now
    def poll(self,snapshot,now):
        if snapshot!=self.candidate:
            self.candidate=snapshot;self.since=now;self.dirty=True
            return False
        if not self.dirty or now-self.since<self.delay:return False
        if any(not row[0].lower().endswith('.pdf') for row in snapshot):return False
        self.dirty=False
        if snapshot==self.handled:return False
        self.handled=snapshot
        return True

class PdfHandler(FileSystemEventHandler):
    def __init__(self,folder,notify):
        self.folder=Path(folder).resolve();self.notify=notify
    def on_any_event(self,event):
        if event.is_directory or event.event_type not in ('created','modified','moved','deleted'):return
        paths=[getattr(event,'src_path',''),getattr(event,'dest_path','')]
        for path in paths:
            p=Path(path)
            if path and p.parent.resolve()==self.folder and p.suffix.lower() in ('.pdf','.crdownload','.part','.tmp'):
                self.notify(str(self.folder));return

class FolderMonitor:
    def __init__(self,folder,notify):
        self.observer=Observer()
        self.observer.schedule(PdfHandler(folder,notify),str(folder),recursive=False)
        self.observer.start()
    def stop(self):
        self.observer.stop();self.observer.join(timeout=2)
