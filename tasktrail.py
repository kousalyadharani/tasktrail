#!/usr/bin/env python3
"""Small, local-first email-to-task tracker with persistent run checkpoints."""
from __future__ import annotations
import argparse, email, html, json, re, sqlite3, threading, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB = Path(__file__).with_name("tasktrail.sqlite3")
STEPS = ("receive", "parse", "extract", "due_dates", "deduplicate", "save")
DATE = re.compile(r"\b(?:due\s*(?:on|by)?\s*)?(\d{4}-\d{2}-\d{2})\b", re.I)

def connect(db=None):
    db = DB if db is None else db
    con=sqlite3.connect(db, timeout=10); con.row_factory=sqlite3.Row
    con.executescript("""CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,email TEXT NOT NULL,step INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'queued',error TEXT,created TEXT NOT NULL,payload TEXT);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,title TEXT NOT NULL,due_date TEXT,done INTEGER NOT NULL DEFAULT 0,UNIQUE(run_id,title));
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,step TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL);""")
    if "payload" not in {r[1] for r in con.execute("PRAGMA table_info(runs)")}:
        con.execute("ALTER TABLE runs ADD COLUMN payload TEXT")
    return con

def event(con, run_id, step, kind, detail):
    con.execute("INSERT INTO events(run_id,step,kind,detail,created) VALUES(?,?,?,?,?)", (run_id,step,kind,detail,datetime.now(timezone.utc).isoformat())); con.commit()

def extract_tasks(body):
    """Extract simple action-like lines; richer language parsing needs a configured model."""
    out=[]
    for line in body.splitlines():
        s=re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if len(s)>=4 and re.search(r"\b(?:todo|task|please|send|review|call|submit|prepare|follow up|complete|schedule|deliver|finish|update|check)\b",s,re.I): out.append(s)
    return list(dict.fromkeys(out))

def run_pipeline(run_id, db=None, fail_step=None):
    db = DB if db is None else db
    con=connect(db)
    try:
        row=con.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise KeyError(run_id)
        raw=row["email"]
        while row["step"] < len(STEPS):
            step=STEPS[row["step"]]
            payload=json.loads(row["payload"]) if row["payload"] else raw
            for attempt in range(1,4):
                try:
                    event(con,run_id,step,"start",f"attempt {attempt}")
                    if fail_step==step and attempt<3: raise RuntimeError("simulated transient failure")
                    if step=="receive": payload=raw
                    elif step=="parse":
                        msg=email.message_from_string(raw); payload=msg.get_payload(decode=True)
                        if payload is None: payload=msg.get_payload()
                        if isinstance(payload,bytes): payload=payload.decode(msg.get_content_charset() or "utf-8","replace")
                        if not isinstance(payload,str): payload=str(payload)
                    elif step=="extract": payload=extract_tasks(payload)
                    elif step=="due_dates": payload=[(t, (DATE.search(t).group(1) if DATE.search(t) else None)) for t in payload]
                    elif step=="deduplicate": payload=list(dict.fromkeys(tuple(item) for item in payload))
                    elif step=="save":
                        con.execute("BEGIN IMMEDIATE")
                        for title,due in payload: con.execute("INSERT OR IGNORE INTO tasks(run_id,title,due_date) VALUES(?,?,?)",(run_id,title,due))
                        con.execute("UPDATE runs SET step=?,status='done',error=NULL WHERE id=?",(len(STEPS),run_id)); con.commit()
                    if step!="save":
                        con.execute("UPDATE runs SET step=?,status='running',error=NULL,payload=? WHERE id=?",(row["step"]+1,json.dumps(payload),run_id)); con.commit()
                    event(con,run_id,step,"finish","checkpoint saved")
                    row=con.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone(); break
                except Exception as exc:
                    event(con,run_id,step,"retry",str(exc)); time.sleep(.01*attempt)
                    if attempt==3:
                        con.execute("UPDATE runs SET status='failed',error=? WHERE id=?",(str(exc),run_id)); con.commit(); event(con,run_id,step,"failed",str(exc)); raise
    finally: con.close()

def submit(raw, db=None):
    db = DB if db is None else db
    import hashlib
    rid=hashlib.sha256(raw.encode()).hexdigest()[:20]
    con=connect(db)
    con.execute("INSERT OR IGNORE INTO runs(id,email,status,created) VALUES(?,?,?,?)",(rid,raw,"queued",datetime.now(timezone.utc).isoformat())); con.commit(); con.close()
    return rid

def resume_pending(db=None):
    """Restart checkpointed work after a server process restart."""
    db = DB if db is None else db
    con=connect(db)
    pending=[r[0] for r in con.execute("SELECT id FROM runs WHERE status IN ('queued','running')")]
    con.close()
    for rid in pending: threading.Thread(target=run_pipeline,args=(rid,db),daemon=True).start()
    return len(pending)

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        data=json.dumps(value).encode(); self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/":
            page="""<!doctype html><meta charset=utf-8><title>TaskTrail</title><h1>TaskTrail</h1><p>Paste an email; tasks are checkpointed in local SQLite.</p><textarea id=e rows=10 cols=72 placeholder="Email text"></textarea><br><button onclick="go()">Process email</button><pre id=o></pre><script>async function go(){let r=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.querySelector('#e').value})});let x=await r.json();document.querySelector('#o').textContent=JSON.stringify(x,null,2);}</script>"""
            b=page.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        con=connect()
        if path=="/api/runs": rows=[dict(x) for x in con.execute("SELECT id,status,step,error,created FROM runs ORDER BY created DESC")]; con.close(); return self.send_json(rows)
        parts=path.strip('/').split('/')
        if len(parts)==4 and parts[:2]==["api","runs"] and parts[3]=="events":
            rid=parts[2]
            try: last_id=int(self.headers.get("Last-Event-ID","0"))
            except ValueError: last_id=0
            self.send_response(200); self.send_header("Content-Type","text/event-stream; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Connection","keep-alive"); self.end_headers()
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                con=connect()
                rows=con.execute("SELECT id,step,kind,detail,created FROM events WHERE run_id=? AND id>? ORDER BY id",(rid,last_id)).fetchall()
                run=con.execute("SELECT status FROM runs WHERE id=?",(rid,)).fetchone(); con.close()
                for row in rows:
                    item=dict(row); last_id=item["id"]
                    payload=json.dumps(item,ensure_ascii=False)
                    self.wfile.write(f"id: {last_id}\nevent: {item['kind']}\ndata: {payload}\n\n".encode()); self.wfile.flush()
                if run is None or (run["status"] in {"done","failed"} and not rows): break
                time.sleep(.25)
            return
        if len(parts)==3 and parts[0]=="api" and parts[1]=="runs":
            rid=parts[2]; run=con.execute("SELECT id,status,step,error,created FROM runs WHERE id=?",(rid,)).fetchone(); tasks=[dict(x) for x in con.execute("SELECT title,due_date,done FROM tasks WHERE run_id=?",(rid,))]; con.close(); return self.send_json({"run":dict(run) if run else None,"tasks":tasks},404 if not run else 200)
        con.close(); self.send_json({"error":"not found"},404)
    def do_POST(self):
        if self.path!="/api/runs": return self.send_json({"error":"not found"},404)
        try: data=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0")))); raw=data["email"]
        except Exception: return self.send_json({"error":"send JSON with an email string"},400)
        if not isinstance(raw,str) or not raw.strip(): return self.send_json({"error":"email must be non-empty text"},400)
        rid=submit(raw); threading.Thread(target=run_pipeline,args=(rid,),daemon=True).start(); return self.send_json({"run_id":rid,"status":"queued"},202)
    def log_message(self,*_): pass

def main():
    global DB
    ap=argparse.ArgumentParser(); ap.add_argument("--host",default="127.0.0.1"); ap.add_argument("--port",type=int,default=8000); ap.add_argument("--db",type=Path,default=DB); args=ap.parse_args()
    DB=args.db; connect().close(); resume_pending(DB); print(f"TaskTrail listening on http://{args.host}:{args.port}"); ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=="__main__": main()
