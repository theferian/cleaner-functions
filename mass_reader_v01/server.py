"""Local-only Mass Reader REST server + bilingual dashboard. Stdlib only."""
from __future__ import annotations
import argparse
import csv
import io
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import webbrowser
import threading
from .core import Store, Reader, now

ROOT=Path(__file__).resolve().parents[1]
STATIC=Path(__file__).resolve().parent/'static'


def build_server(store,reader,host='127.0.0.1',port=8765):
    class Handler(BaseHTTPRequestHandler):
        server_version='MassReader/0.1'
        def _send(self, body, code=200, content_type='application/json; charset=utf-8'):
            if isinstance(body,(dict,list)):
                data=json.dumps(body,ensure_ascii=False).encode('utf-8')
            elif isinstance(body,str):data=body.encode('utf-8')
            else:data=body
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(data)
        def _check_origin(self):
            origin=self.headers.get('Origin','')
            if not origin:return True
            return bool(re.fullmatch(r'http://(?:localhost|127\.0\.0\.1):\d+',origin))
        def _body(self):
            if not self._check_origin():raise ValueError('Invalid browser origin')
            if not self.headers.get('Content-Type','').startswith('application/json'):
                raise ValueError('Use application/json')
            n=int(self.headers.get('Content-Length','0'))
            if n<0 or n>100_000:raise ValueError('Invalid JSON request size')
            return json.loads(self.rfile.read(n)) if n else {}
        def do_GET(self):
            try:
                u=urlsplit(self.path);parts=[v for v in u.path.split('/') if v]
                q=parse_qs(u.query)
                if u.path in ('/','/index.html'):
                    return self._send((STATIC/'index.html').read_bytes(),content_type='text/html; charset=utf-8')
                if u.path=='/app.js':
                    return self._send((STATIC/'app.js').read_bytes(),content_type='text/javascript; charset=utf-8')
                if u.path=='/app.css':
                    return self._send((STATIC/'app.css').read_bytes(),content_type='text/css; charset=utf-8')
                if u.path=='/api/health':return self._send({'ok':True,'time':now(),'db':str(store.path)})
                if parts==['api','workspaces']:return self._send(store.all_workspaces())
                if len(parts)==3 and parts[:2]==['api','workspaces']:
                    return self._send(store.workspace(int(parts[2])))
                if len(parts)==4 and parts[:2]==['api','workspaces'] and parts[3]=='files':
                    return self._send(store.list_files(int(parts[2]),q.get('q',[''])[0],q.get('scope',[None])[0],q.get('limit',['100'])[0],q.get('offset',['0'])[0]))
                if len(parts)==3 and parts[:2]==['api','runs']:
                    return self._send(store.run(parts[2]))
                if len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='folders':
                    return self._send(store.folders(parts[2],q.get('scope',[None])[0]))
                if len(parts)==4 and parts[:2]==['api','runs'] and parts[3] in ('progress.csv','folders.csv'):
                    rid=parts[2]
                    out=io.StringIO(); writer=csv.writer(out)
                    if parts[3]=='progress.csv':
                        data=store.run(rid)
                        writer.writerow(['run_id','run_status','scope_id','scope_label','root','folders_total','folders_done','folders_skipped','folders_failed','folders_pending','files_observed'])
                        for s in data['areas']:
                            writer.writerow([rid,data['run']['status'],s['scope_id'],s['label'],s['root'],s['folders_total'],s['folders_done'],s['folders_skipped'],s['folders_failed'],s['folders_pending'],s['observed_files']])
                    else:
                        writer.writerow(['run_id','scope_id','folder_path','relative','depth','status','file_count','error'])
                        with store.connect() as c:
                            for row in c.execute('SELECT scope_id,path,relative,depth,status,file_count,error FROM dirs WHERE run_id=? ORDER BY scope_id,relative',(rid,)):
                                writer.writerow([rid,*row])
                    return self._send(('\ufeff'+out.getvalue()).encode('utf-8'),content_type='text/csv; charset=utf-8')
                return self._send({'error':'Unknown route'},404)
            except (ValueError,TypeError) as e:return self._send({'error':str(e)},400)
            except Exception as e:return self._send({'error':repr(e)},500)
        def do_POST(self):
            try:
                parts=[v for v in urlsplit(self.path).path.split('/') if v];body=self._body()
                if parts==['api','workspaces']:
                    return self._send({'id':store.create_workspace(body.get('name',''),body.get('description',''))},201)
                if len(parts)==4 and parts[:2]==['api','workspaces'] and parts[3]=='scopes':
                    return self._send({'id':store.save_scope(int(parts[2]),body)},201)
                if len(parts)==5 and parts[:2]==['api','workspaces'] and parts[3]=='scopes':
                    return self._send({'id':store.save_scope(int(parts[2]),body,int(parts[4]))})
                if len(parts)==4 and parts[:2]==['api','workspaces'] and parts[3]=='runs':
                    wid=int(parts[2]);rid=store.create_run(wid,int(body.get('budget',0)))
                    reader.start(rid,int(body.get('budget',0)))
                    return self._send({'id':rid},201)
                if len(parts)==4 and parts[:2]==['api','runs']:
                    rid=parts[2];action=parts[3]
                    if action=='resume':reader.start(rid,int(body.get('budget',0)))
                    elif action in ('pause','cancel'):store.request(rid,action)
                    else:raise ValueError('Unknown run action')
                    return self._send({'ok':True,'id':rid})
                return self._send({'error':'Unknown route'},404)
            except (ValueError,TypeError,KeyError) as e:return self._send({'error':str(e)},400)
            except Exception as e:return self._send({'error':repr(e)},500)
        def do_DELETE(self):
            try:
                if not self._check_origin():raise ValueError('Invalid origin')
                p=[v for v in urlsplit(self.path).path.split('/') if v]
                if len(p)==5 and p[:2]==['api','workspaces'] and p[3]=='scopes':
                    store.delete_scope(int(p[2]),int(p[4]));return self._send({'ok':True})
                return self._send({'error':'Unknown route'},404)
            except (ValueError,TypeError) as e:return self._send({'error':str(e)},400)
        def log_message(self,fmt,*args):
            if args and str(args[1] if len(args)>1 else '') not in ('200',):
                print('[HTTP]',fmt%args)
    return ThreadingHTTPServer((host,port),Handler)


def main(argv=None):
    p=argparse.ArgumentParser(description='Mass Reader V01 — read-only folder mapping and progress dashboard')
    p.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1','localhost'])
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--db',default=str(ROOT/'working'/'mass_reader'/'state.sqlite3'))
    p.add_argument('--no-browser',action='store_true')
    p.add_argument('--seed-weekly-reports',action='store_true',help='Create a workspace containing the two previously approved search-root paths (no scanning)')
    args=p.parse_args(argv)
    store=Store(args.db);reader=Reader(store)
    if args.seed_weekly_reports:
        name='EPC Weekly Reports — source inventory'
        found=[w for w in store.all_workspaces() if w['name']==name]
        if not found:
            wid=store.create_workspace(name,'Weekly Report search roots. No automatic file-family approval or content extraction.')
            for label,root in [('Weekly reports','W:\\پیگیری پروژه ها\\گزارش هفتگی پروژه ها'),('Planning department','Y:\\Planning Department')]:
                store.save_scope(wid,dict(label=label,root=root,recursive=True,include=['*'],exclude=['~$*','**/.git/**','**/__pycache__/**']))
            print('[SEED] Weekly Reports workspace created with two roots; no scan started')
        else:print('[SEED] Existing Weekly Reports workspace retained; no duplicate created')
    srv=build_server(store,reader,args.host,args.port)
    url=f'http://127.0.0.1:{srv.server_address[1]}/'
    print('[MASS READER] Local dashboard:',url)
    print('[DATABASE]',store.path)
    print('[SAFETY] Scan-only; original files are not opened or modified; no outside-network web server')
    print('[STOP] Ctrl+C. Paused/interrupted runs can be resumed after relaunch.')
    if not args.no_browser:threading.Timer(0.6, lambda:webbrowser.open(url)).start()
    try:srv.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt: print('\n[STOP] Server stopped; scan progress remains in SQLite')
    finally:srv.server_close()

if __name__=='__main__':main()
