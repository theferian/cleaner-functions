"""Mass Reader V01: user-scoped, read-only, resumable folder/file inventory.

Python standard library only. No workbook opens, no file content reads, no ML claims.
Persistent SQLite state lives under working/mass_reader and is not part of Git.
"""
from __future__ import annotations
import datetime as dt
from contextlib import contextmanager
import fnmatch
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

KNOWN = {
    '.xlsx': 'EXCEL', '.xlsm': 'EXCEL_MACRO', '.xls': 'EXCEL_LEGACY', '.xlsb': 'EXCEL_BINARY',
    '.csv': 'CSV', '.tsv': 'TSV', '.pdf': 'PDF', '.docx': 'WORD', '.doc': 'WORD_LEGACY',
    '.pptx': 'SLIDES', '.ppt': 'SLIDES_LEGACY', '.txt': 'TEXT', '.md': 'MARKDOWN',
    '.json': 'JSON', '.xml': 'XML', '.html': 'HTML', '.htm': 'HTML', '.jpg': 'IMAGE',
    '.jpeg': 'IMAGE', '.png': 'IMAGE', '.tiff': 'IMAGE', '.tif': 'IMAGE', '.bmp': 'IMAGE',
    '.zip': 'ARCHIVE', '.7z': 'ARCHIVE', '.rar': 'ARCHIVE', '.eml': 'EMAIL', '.msg': 'EMAIL',
    '.xer': 'P6_XER', '.mpp': 'MS_PROJECT', '.mpx': 'MS_PROJECT', '.dwg': 'CAD', '.dxf': 'CAD',
    '.ifc': 'BIM', '.rvt': 'BIM', '.db': 'DATABASE', '.sqlite': 'DATABASE', '.py': 'CODE',
}
STEPS = ['DISCOVERED', 'CLASSIFICATION_PENDING', 'EVALUATION_PENDING']
DEFAULT_EXCLUDES = ['~$*', '**/.git/**', '**/__pycache__/**']


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def js(value):
    return json.dumps(value, ensure_ascii=False)


def read_patterns(x, default=None):
    if x is None:
        return list(default or [])
    if isinstance(x, str):
        x = x.replace('\r', '\n').replace(';', '\n').split('\n')
    if not isinstance(x, list) or not all(isinstance(k, str) for k in x):
        raise ValueError('Patterns must be a list of strings or newline-separated text')
    return [k.strip().replace('\\', '/') for k in x if k.strip()]


def pathmatch(relative, pattern, is_dir=False):
    """Match relative POSIX paths, folder/** subtrees, or any-depth basenames."""
    relative = relative.replace('\\', '/').lstrip('/')
    pattern = pattern.replace('\\', '/').strip().lstrip('/')
    if not pattern:
        return False
    r = relative.casefold()
    p = pattern.casefold()
    if p.endswith('/**'):
        base = p[:-3].rstrip('/')
        if r == base or r.startswith(base + '/'):
            return True
        if fnmatch.fnmatchcase(r, p):
            return True
    if '/' not in p:
        return fnmatch.fnmatchcase(r.rsplit('/', 1)[-1], p) or fnmatch.fnmatchcase(r, p)
    if p.startswith('**/') and pathmatch(relative, pattern[3:], is_dir=is_dir):
        return True
    return fnmatch.fnmatchcase(r, p) or (is_dir and fnmatch.fnmatchcase(r+'/', p))


def overridden(rel, overrides):
    return any(pathmatch(rel, p) for p in overrides)


def override_descendant(rel, overrides):
    """If an excluded ancestor holds an explicitly requested subpath, tunnel to it."""
    rel = rel.casefold().strip('/')
    for raw in overrides:
        p = raw.casefold().strip('/')
        while p.startswith('**/'):
            p = p[3:]
        base = p.split('*', 1)[0].rstrip('/')
        if not rel or base.startswith(rel + '/') or base == rel:
            return True
    return False


def decision(rel, is_dir, includes, excludes, overrides):
    if overridden(rel, overrides):
        return 'INCLUDED'
    if any(pathmatch(rel, p, is_dir=is_dir) for p in excludes):
        return 'EXCLUDED'
    if is_dir:
        return 'INCLUDED'  # Inclusion masks apply to files, not traversal.
    return 'INCLUDED' if not includes or any(pathmatch(rel, p) for p in includes) else 'OUTSIDE_INCLUDE'


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS workspaces (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scopes (
  id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  label TEXT NOT NULL, root TEXT NOT NULL, recursive INTEGER NOT NULL DEFAULT 1,
  max_depth INTEGER NOT NULL DEFAULT -1, include_json TEXT NOT NULL DEFAULT '["*"]',
  exclude_json TEXT NOT NULL DEFAULT '[]', override_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, updated_at TEXT NOT NULL,
  pause_requested INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
  processed_files INTEGER NOT NULL DEFAULT 0, included_files INTEGER NOT NULL DEFAULT 0,
  excluded_files INTEGER NOT NULL DEFAULT 0, outside_include_files INTEGER NOT NULL DEFAULT 0,
  new_files INTEGER NOT NULL DEFAULT 0, changed_files INTEGER NOT NULL DEFAULT 0,
  unchanged_files INTEGER NOT NULL DEFAULT 0, inaccessible INTEGER NOT NULL DEFAULT 0,
  budget INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_scopes (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  scope_id INTEGER NOT NULL, label TEXT NOT NULL, root TEXT NOT NULL,
  recursive INTEGER NOT NULL, max_depth INTEGER NOT NULL,
  include_json TEXT NOT NULL, exclude_json TEXT NOT NULL, override_json TEXT NOT NULL,
  PRIMARY KEY(run_id,scope_id)
);
CREATE TABLE IF NOT EXISTS dirs (
  id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  scope_id INTEGER NOT NULL, path TEXT NOT NULL, relative TEXT NOT NULL,
  depth INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
  cursor TEXT NOT NULL DEFAULT '', file_count INTEGER NOT NULL DEFAULT 0,
  excluded_count INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
  UNIQUE(run_id,scope_id,path)
);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  scope_id INTEGER NOT NULL, path TEXT NOT NULL, relative TEXT NOT NULL,
  filename TEXT NOT NULL, extension TEXT NOT NULL, file_type TEXT NOT NULL,
  size INTEGER, mtime_ns INTEGER, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  last_run_id TEXT NOT NULL, scope_decision TEXT NOT NULL, observation_status TEXT NOT NULL DEFAULT 'SEEN',
  UNIQUE(workspace_id,scope_id,path)
);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  scope_id INTEGER NOT NULL, path TEXT NOT NULL, relative TEXT NOT NULL,
  kind TEXT NOT NULL, scope_decision TEXT NOT NULL,
  file_type TEXT NOT NULL, size INTEGER, mtime_ns INTEGER, observed_at TEXT NOT NULL,
  UNIQUE(run_id,scope_id,path)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  recorded_at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_workspace ON files(workspace_id,scope_id);
CREATE INDEX IF NOT EXISTS idx_observations_run ON observations(run_id,scope_id);
CREATE INDEX IF NOT EXISTS idx_dirs_run ON dirs(run_id,scope_id,status);
'''


class Store:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript(SCHEMA)
            # An interrupted process must not leave a permanently 'running' run.
            # On restart, leave no pending stop request running in a stale state.
            c.execute("UPDATE runs SET status='CANCELLED', finished_at=?, updated_at=? WHERE status='CANCELLING' OR (status IN ('RUNNING','PAUSING') AND cancel_requested=1)", (now(),now()))
            c.execute("UPDATE runs SET status='PAUSED', pause_requested=0, updated_at=? WHERE status IN ('RUNNING','PAUSING')", (now(),))
            c.execute("UPDATE dirs SET status='PENDING' WHERE status='PROCESSING'")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(str(self.path), timeout=30)
        try:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA busy_timeout=30000')
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('PRAGMA foreign_keys=ON')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def all_workspaces(self):
        with self.connect() as c:
            return [dict(x) for x in c.execute('''SELECT w.*, (SELECT COUNT(*) FROM scopes s WHERE s.workspace_id=w.id) AS scope_count,
              (SELECT COUNT(*) FROM files f WHERE f.workspace_id=w.id) AS file_count,
              (SELECT status FROM runs r WHERE r.workspace_id=w.id ORDER BY started_at DESC LIMIT 1) AS last_status
              FROM workspaces w ORDER BY id DESC''')]

    def create_workspace(self, name, description=''):
        name = str(name).strip()
        if not name or len(name)>150: raise ValueError('Workspace name required (max 150 chars)')
        with self.connect() as c:
            cur = c.execute('INSERT INTO workspaces(name,description,created_at) VALUES(?,?,?)', (name,str(description)[:1500],now()))
            return cur.lastrowid

    def workspace(self, wid):
        with self.connect() as c:
            w = c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone()
            if not w: raise ValueError('Workspace not found')
            scopes = [dict(x) for x in c.execute('SELECT * FROM scopes WHERE workspace_id=? ORDER BY id',(wid,))]
            for s in scopes:
                for key in ('include_json','exclude_json','override_json'):
                    s[key[:-5]] = json.loads(s.pop(key))
            runs = [dict(x) for x in c.execute('SELECT * FROM runs WHERE workspace_id=? ORDER BY started_at DESC LIMIT 30',(wid,))]
            ext = [dict(x) for x in c.execute("SELECT extension,file_type,COUNT(*) n FROM files WHERE workspace_id=? GROUP BY extension,file_type ORDER BY n DESC LIMIT 16",(wid,))]
            return dict(workspace=dict(w),scopes=scopes,runs=runs,extensions=ext)

    def active(self, wid):
        with self.connect() as c:
            return c.execute("SELECT id,status FROM runs WHERE workspace_id=? AND status IN ('PAUSED','RUNNING','PAUSING','CANCELLING') ORDER BY started_at DESC LIMIT 1",(wid,)).fetchone()

    def save_scope(self,wid,payload,sid=None):
        if self.active(wid): raise ValueError('Pause/finish or cancel the existing run before editing scopes')
        root = str(payload.get('root','')).strip().strip('"')
        if not root: raise ValueError('A folder or file path is required')
        if len(root)>4096: raise ValueError('Path too long')
        if not os.path.isabs(root): raise ValueError('Use an absolute drive, UNC or local path')
        incl=read_patterns(payload.get('include'),['*'])
        excl=read_patterns(payload.get('exclude'),DEFAULT_EXCLUDES)
        override=read_patterns(payload.get('override'),[])
        maxdepth=int(payload.get('max_depth',-1))
        if maxdepth<-1 or maxdepth>1000: raise ValueError('max_depth must be -1 (unlimited) or 0..1000')
        label=str(payload.get('label','')).strip() or Path(root).name or root
        args=(label,root,int(bool(payload.get('recursive',True))),maxdepth,js(incl),js(excl),js(override),int(bool(payload.get('enabled',True))))
        with self.connect() as c:
            if not c.execute('SELECT id FROM workspaces WHERE id=?',(wid,)).fetchone(): raise ValueError('Workspace not found')
            if sid:
                cur=c.execute('''UPDATE scopes SET label=?,root=?,recursive=?,max_depth=?,include_json=?,exclude_json=?,override_json=?,enabled=?
                   WHERE id=? AND workspace_id=?''',(*args,sid,wid))
                if not cur.rowcount: raise ValueError('Scope not found')
                return sid
            cur=c.execute('''INSERT INTO scopes(label,root,recursive,max_depth,include_json,exclude_json,override_json,enabled,created_at,workspace_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?)''',(*args,now(),wid))
            return cur.lastrowid

    def delete_scope(self,wid,sid):
        if self.active(wid): raise ValueError('Finish or cancel the existing scan first')
        with self.connect() as c:
            c.execute('DELETE FROM scopes WHERE workspace_id=? AND id=?',(wid,sid))

    def create_run(self,wid,budget=0):
        if self.active(wid): raise ValueError('Resume or cancel the existing run before starting another')
        budget=max(0,min(int(budget),1000000))
        with self.connect() as c:
            scopes=c.execute('SELECT * FROM scopes WHERE workspace_id=? AND enabled=1',(wid,)).fetchall()
            if not scopes: raise ValueError('Add at least one enabled path scope first')
            rid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:7]
            c.execute('INSERT INTO runs(id,workspace_id,status,started_at,updated_at,budget) VALUES(?,?,?,?,?,?)', (rid,wid,'PAUSED',now(),now(),budget))
            for s in scopes:
                c.execute('''INSERT INTO run_scopes(run_id,scope_id,label,root,recursive,max_depth,include_json,exclude_json,override_json)
                   VALUES(?,?,?,?,?,?,?,?,?)''',(rid,s['id'],s['label'],s['root'],s['recursive'],s['max_depth'],s['include_json'],s['exclude_json'],s['override_json']))
                c.execute('INSERT INTO dirs(run_id,scope_id,path,relative,depth) VALUES(?,?,?,?,0)',(rid,s['id'],s['root'],'',))
            self.log(c,rid,'INFO',f'Scan created with {len(scopes)} source path(s); read-only')
            return rid

    @staticmethod
    def log(c,rid,level,message):
        c.execute('INSERT INTO events(run_id,recorded_at,level,message) VALUES(?,?,?,?)',(rid,now(),level,message[:1200]))

    def run(self,rid):
        with self.connect() as c:
            r=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not r: raise ValueError('Run not found')
            d=c.execute('''SELECT scope_id,status,COUNT(*) n FROM dirs WHERE run_id=? GROUP BY scope_id,status''',(rid,)).fetchall()
            scopes=[dict(s) for s in c.execute('SELECT scope_id,label,root FROM run_scopes WHERE run_id=?',(rid,))]
            for s in scopes:
                st={x['status']:x['n'] for x in d if x['scope_id']==s['scope_id']}
                s.update(folders_total=sum(st.values()),folders_done=st.get('DONE',0),folders_failed=st.get('ERROR',0),folders_pending=st.get('PENDING',0)+st.get('PROCESSING',0),folders_skipped=st.get('SKIPPED',0))
                s['observed_files']=c.execute('SELECT COUNT(*) FROM observations WHERE run_id=? AND scope_id=?',(rid,s['scope_id'])).fetchone()[0]
            ev=[dict(x) for x in c.execute('SELECT recorded_at,level,message FROM events WHERE run_id=? ORDER BY id DESC LIMIT 100',(rid,))]
            errors=[dict(x) for x in c.execute("SELECT scope_id,relative,path,error FROM dirs WHERE run_id=? AND status='ERROR' ORDER BY id LIMIT 100",(rid,))]
            return dict(run=dict(r),areas=scopes,events=ev,errors=errors)

    def list_files(self,wid,query='',scope_id=None,limit=100,offset=0):
        limit=min(250,max(1,int(limit))); offset=max(0,int(offset)); params=[wid]
        where='workspace_id=?'
        if query:
            where+=' AND (filename LIKE ? OR relative LIKE ? OR extension LIKE ?)'
            params.extend(['%'+query[:160]+'%']*3)
        if scope_id:
            where+=' AND scope_id=?';params.append(int(scope_id))
        with self.connect() as c:
            total=c.execute('SELECT COUNT(*) FROM files WHERE '+where,params).fetchone()[0]
            rows=[dict(x) for x in c.execute('SELECT scope_id,relative,path,filename,extension,file_type,size,mtime_ns,last_seen,scope_decision,observation_status FROM files WHERE '+where+' ORDER BY last_seen DESC,relative LIMIT ? OFFSET ?',(*params,limit,offset))]
            return {'total':total,'files':rows,'offset':offset,'limit':limit}

    def folders(self,rid,scope_id=None,limit=350):
        with self.connect() as c:
            params=[rid]; where='run_id=?'
            if scope_id: where+=' AND scope_id=?';params.append(int(scope_id))
            return [dict(x) for x in c.execute('SELECT scope_id,relative,path,depth,status,file_count,excluded_count,error FROM dirs WHERE '+where+' ORDER BY scope_id,relative LIMIT ?',(*params,min(int(limit),1500)))]

    def request(self,rid,what):
        if what not in ('pause','cancel'):raise ValueError('Unknown request')
        with self.connect() as c:
            r=c.execute('SELECT status FROM runs WHERE id=?',(rid,)).fetchone()
            if not r:raise ValueError('Run not found')
            if what=='pause' and r['status'] in ('RUNNING','PAUSING'):
                c.execute("UPDATE runs SET pause_requested=1,status='PAUSING',updated_at=? WHERE id=?",(now(),rid))
            elif what=='cancel' and r['status'] in ('RUNNING','PAUSING','CANCELLING'):
                c.execute("UPDATE runs SET cancel_requested=1,status='CANCELLING',updated_at=? WHERE id=?",(now(),rid))
            elif what == 'cancel' and r['status']=='PAUSED':
                c.execute("UPDATE runs SET status='CANCELLED',cancel_requested=0,pause_requested=0,finished_at=?,updated_at=? WHERE id=?",(now(),now(),rid))
                c.execute("UPDATE dirs SET status='PENDING' WHERE run_id=? AND status='PROCESSING'",(rid,))
            elif what == 'pause' and r['status'] in ('PAUSED','CANCELLING'): pass
            else: raise ValueError('Run is not active')

    def snapshot(self,rid):
        return self.run(rid)


class Reader:
    def __init__(self,store):
        self.store=store
        self._threads={}
        self._lock=threading.Lock()

    def start(self,rid,budget=0):
        with self._lock:
            thread=self._threads.get(rid)
            if thread and thread.is_alive():raise ValueError('Scan is already running')
            with self.store.connect() as c:
                r=c.execute('SELECT status FROM runs WHERE id=?',(rid,)).fetchone()
                if not r:raise ValueError('Run not found')
                if r['status']!='PAUSED':raise ValueError('Run must be paused to start/resume')
                c.execute("UPDATE runs SET status='RUNNING',pause_requested=0,cancel_requested=0,budget=?,updated_at=? WHERE id=?",(max(0,min(int(budget),1000000)),now(),rid))
                self.store.log(c,rid,'INFO','Scan started/resumed')
            t=threading.Thread(target=self._run,args=(rid,max(0,int(budget))),daemon=True,name=f'mass-reader-{rid}')
            self._threads[rid]=t;t.start()

    def _run(self,rid,budget):
        try:self._scan(rid,budget)
        except Exception as e:
            with self.store.connect() as c:
                c.execute("UPDATE runs SET status='PAUSED',updated_at=? WHERE id=?",(now(),rid))
                c.execute("UPDATE dirs SET status='PENDING' WHERE run_id=? AND status='PROCESSING'",(rid,))
                self.store.log(c,rid,'ERROR','Unexpected scan failure (resumable): '+repr(e))

    def _stop_requested(self,rid):
        with self.store.connect() as c:
            row=c.execute('SELECT pause_requested,cancel_requested FROM runs WHERE id=?',(rid,)).fetchone()
            return bool(row and (row['pause_requested'] or row['cancel_requested']))

    def _scan(self,rid,budget):
        with self.store.connect() as c:
            run=c.execute('SELECT workspace_id FROM runs WHERE id=?',(rid,)).fetchone()
            wid=run['workspace_id']
            scopes={s['scope_id']:dict(s) for s in c.execute('SELECT * FROM run_scopes WHERE run_id=?',(rid,))}
        this_session=0
        while True:
            with self.store.connect() as c:
                flags=c.execute('SELECT pause_requested,cancel_requested FROM runs WHERE id=?',(rid,)).fetchone()
                if flags['pause_requested'] or flags['cancel_requested']:
                    status='CANCELLED' if flags['cancel_requested'] else 'PAUSED'
                    c.execute('UPDATE runs SET status=?,pause_requested=0,cancel_requested=0,updated_at=?,finished_at=CASE WHEN ?="CANCELLED" THEN ? ELSE finished_at END WHERE id=?',(status,now(),status,now(),rid))
                    c.execute("UPDATE dirs SET status='PENDING' WHERE run_id=? AND status='PROCESSING'",(rid,))
                    self.store.log(c,rid,'INFO','Scan '+status.lower()+' by user')
                    return
                if budget and this_session >= budget:
                    c.execute("UPDATE runs SET status='PAUSED',updated_at=? WHERE id=?",(now(),rid))
                    c.execute("UPDATE dirs SET status='PENDING' WHERE run_id=? AND status='PROCESSING'",(rid,))
                    self.store.log(c,rid,'INFO',f'Batch limit reached ({budget} files); resume to continue')
                    return
                dirrow=c.execute("SELECT * FROM dirs WHERE run_id=? AND status IN ('PENDING','PROCESSING') ORDER BY id LIMIT 1",(rid,)).fetchone()
                if not dirrow:
                    failures=c.execute("SELECT COUNT(*) FROM dirs WHERE run_id=? AND status='ERROR'",(rid,)).fetchone()[0]
                    status='COMPLETED_WITH_ERRORS' if failures else 'COMPLETED'
                    c.execute('UPDATE runs SET status=?,finished_at=?,updated_at=? WHERE id=?',(status,now(),now(),rid))
                    # Missing is only a suspicion. No source files are deleted or marked definitively removed.
                    if not failures:
                        for sid in scopes:
                            c.execute("UPDATE files SET observation_status='NOT_OBSERVED_IN_LATEST_RUN' WHERE workspace_id=? AND scope_id=? AND last_run_id<>? AND observation_status='SEEN'",(wid,sid,rid))
                    self.store.log(c,rid,'OK',f'Inventory {status.lower()}; {failures} inaccessible folders')
                    return
                q=dict(dirrow)
                c.execute("UPDATE dirs SET status='PROCESSING' WHERE id=?",(q['id'],))
            scope=scopes[q['scope_id']]
            root=q['path']
            # Explicit file path roots are supported as first-class scopes.
            if q['depth']==0 and os.path.isfile(root) and not os.path.islink(root):
                with self.store.connect() as c:
                    self._observe_file(c,run_id=rid,wid=wid,scope_id=q['scope_id'],path=root,rel=Path(root).name,
                                       includes=json.loads(scope['include_json']),excludes=json.loads(scope['exclude_json']),overrides=json.loads(scope['override_json']))
                    c.execute("UPDATE dirs SET status='DONE',file_count=1 WHERE id=?",(q['id'],))
                this_session+=1
                continue
            if os.path.islink(root):
                with self.store.connect() as c:
                    c.execute("UPDATE dirs SET status='ERROR',error='Symlink/reparse-point root is not followed' WHERE id=?",(q['id'],))
                    self.store.log(c,rid,'WARN',f'Skipped link root: {root}')
                continue
            try:
                entries=[]
                interrupted=False
                with os.scandir(root) as it:
                    for n,ent in enumerate(it):
                        if n%32==0 and self._stop_requested(rid):
                            interrupted=True
                            break
                        entries.append(ent)
                if interrupted:
                    continue  # No cursor advanced: directory safely resumes later.
                entries.sort(key=lambda e:(e.name.casefold(),e.name))
            except OSError as e:
                with self.store.connect() as c:
                    c.execute("UPDATE dirs SET status='ERROR',error=? WHERE id=?",(str(e)[:900],q['id']))
                    c.execute('UPDATE runs SET inaccessible=inaccessible+1 WHERE id=?',(rid,))
                    self.store.log(c,rid,'WARN',f'Cannot access {root}: {e}')
                continue
            cursor=tuple(json.loads(q['cursor'])) if q['cursor'] else None
            includes=json.loads(scope['include_json']);excludes=json.loads(scope['exclude_json']);overrides=json.loads(scope['override_json'])
            for entry in entries:
                if self._stop_requested(rid):break
                key=(entry.name.casefold(),entry.name)
                if cursor and key<=cursor:continue
                rel=(q['relative'].rstrip('/')+'/' if q['relative'] else '')+entry.name
                try:
                    is_link=entry.is_symlink()
                    is_dir=entry.is_dir(follow_symlinks=False) if not is_link else False
                except OSError:is_dir=False;is_link=False
                with self.store.connect() as c:
                    try:
                        if is_dir:
                            d=decision(rel,True,includes,excludes,overrides)
                            tunneled=d=='EXCLUDED' and override_descendant(rel,overrides)
                            descend=bool(scope['recursive']) and (scope['max_depth'] < 0 or q['depth'] < scope['max_depth'])
                            if not descend or (d=='EXCLUDED' and not tunneled):
                                status='SKIPPED'
                            else:
                                status='PENDING'
                            c.execute('''INSERT OR IGNORE INTO dirs(run_id,scope_id,path,relative,depth,status)
                              VALUES(?,?,?,?,?,?)''',(rid,q['scope_id'],entry.path,rel,q['depth']+1,status))
                        else:
                            recorded=self._observe_file(c,rid,wid,q['scope_id'],entry.path,rel,includes,excludes,overrides,symlink=is_link)
                            if recorded: c.execute('UPDATE dirs SET file_count=file_count+1 WHERE id=?',(q['id'],))
                            this_session+=1
                        c.execute('UPDATE dirs SET cursor=? WHERE id=?',(js(key),q['id']))
                    except Exception as e:
                        self.store.log(c,rid,'WARN','Item error '+str(entry.path)+': '+str(e))
                        c.execute('UPDATE runs SET inaccessible=inaccessible+1 WHERE id=?',(rid,))
                        c.execute('UPDATE dirs SET cursor=? WHERE id=?',(js(key),q['id']))
                if budget and this_session>=budget:
                    break
                with self.store.connect() as c:
                    f=c.execute('SELECT pause_requested,cancel_requested FROM runs WHERE id=?',(rid,)).fetchone()
                    if f['pause_requested'] or f['cancel_requested']:break
            else:
                with self.store.connect() as c:
                    c.execute("UPDATE dirs SET status='DONE' WHERE id=?",(q['id'],))
                continue
            # Either budget or user pause; retain queue cursor and pause in outer loop.

    def _observe_file(self,c,run_id,wid,scope_id,path,rel,includes,excludes,overrides,symlink=False):
        sd=decision(rel,False,includes,excludes,overrides)
        p=Path(path);ext=p.suffix.lower();f_type='SYMLINK' if symlink else KNOWN.get(ext,'UNSUPPORTED_OR_UNKNOWN')
        try:
            st=os.stat(path,follow_symlinks=False)
            size=st.st_size if not symlink else None
            mtime=st.st_mtime_ns if not symlink else None
        except OSError:
            size=None;mtime=None
        old=c.execute('SELECT * FROM files WHERE workspace_id=? AND scope_id=? AND path=?',(wid,scope_id,path)).fetchone()
        kind='NEW' if not old else ('CHANGED' if (old['size'],old['mtime_ns'])!=(size,mtime) else 'UNCHANGED')
        # Unique observation prevents resuming a partially scanned directory from inflating counts.
        recorded=c.execute('''INSERT OR IGNORE INTO observations(run_id,scope_id,path,relative,kind,scope_decision,file_type,size,mtime_ns,observed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',(run_id,scope_id,path,rel,kind,sd,f_type,size,mtime,now())).rowcount
        if not recorded:return False
        c.execute('''INSERT INTO files(workspace_id,scope_id,path,relative,filename,extension,file_type,size,mtime_ns,first_seen,last_seen,last_run_id,scope_decision)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(workspace_id,scope_id,path) DO UPDATE SET relative=excluded.relative,filename=excluded.filename,
          extension=excluded.extension,file_type=excluded.file_type,size=excluded.size,mtime_ns=excluded.mtime_ns,
          last_seen=excluded.last_seen,last_run_id=excluded.last_run_id,scope_decision=excluded.scope_decision,observation_status='SEEN' ''',
          (wid,scope_id,path,rel,p.name,ext,f_type,size,mtime,now(),now(),run_id,sd))
        field='included_files' if sd=='INCLUDED' else ('excluded_files' if sd=='EXCLUDED' else 'outside_include_files')
        c.execute(f'UPDATE runs SET processed_files=processed_files+1,{field}={field}+1,{kind.lower()}_files={kind.lower()}_files+1,updated_at=? WHERE id=?',(now(),run_id))
        return True
