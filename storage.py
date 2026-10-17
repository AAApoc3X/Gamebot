import sqlite3,json,time,threading
from contextlib import contextmanager
from pathlib import Path
from configuration import defaults,validate,normalize
class Store:
 def __init__(self,path):
  if str(path)!=':memory:':Path(path).parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(str(path),isolation_level=None);self.db.row_factory=sqlite3.Row
  self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=5000')
  self.lock=threading.RLock();self.depth=0
  self.db.executescript('''
  CREATE TABLE IF NOT EXISTS communities(guild INTEGER PRIMARY KEY,config TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS wallets(guild INTEGER,uid INTEGER,balance INTEGER NOT NULL CHECK(balance>=0 AND balance<=1000000000000),PRIMARY KEY(guild,uid));
  CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,guild INTEGER,uid INTEGER,delta INTEGER,reason TEXT,reference TEXT UNIQUE,created REAL);
  CREATE TABLE IF NOT EXISTS claims(guild INTEGER,uid INTEGER,claimed REAL,PRIMARY KEY(guild,uid));
  CREATE TABLE IF NOT EXISTS api_keys(guild INTEGER PRIMARY KEY,token TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS api_links(guild INTEGER,uid INTEGER,status INTEGER,checked REAL,PRIMARY KEY(guild,uid));
  CREATE TABLE IF NOT EXISTS links(guild INTEGER,uid INTEGER,verified INTEGER,actor INTEGER,PRIMARY KEY(guild,uid));
  CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,guild INTEGER,uid INTEGER,game TEXT,state TEXT,status TEXT,created REAL,updated REAL);
  CREATE UNIQUE INDEX IF NOT EXISTS one_active_game ON sessions(guild,uid) WHERE status='active';
  CREATE TABLE IF NOT EXISTS rewards(id TEXT PRIMARY KEY,guild INTEGER,uid INTEGER,tier TEXT,config TEXT,kind TEXT,payload TEXT,status TEXT,channel INTEGER,message INTEGER,detail TEXT DEFAULT '',created REAL,checked REAL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS draws(id TEXT PRIMARY KEY,guild INTEGER,type TEXT,state TEXT,status TEXT,due REAL,created REAL,announced INTEGER DEFAULT 0,reminded INTEGER DEFAULT 0);
  CREATE UNIQUE INDEX IF NOT EXISTS one_open_draw ON draws(guild,type) WHERE status='open';
  CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,draw TEXT REFERENCES draws(id),uid INTEGER,numbers TEXT,cost INTEGER,kind TEXT,UNIQUE(draw,uid,numbers));
  CREATE TABLE IF NOT EXISTS purchases(reference TEXT PRIMARY KEY,guild INTEGER,uid INTEGER,amount INTEGER,created REAL);
  CREATE TABLE IF NOT EXISTS panels(guild INTEGER,type TEXT,channel INTEGER,message INTEGER,PRIMARY KEY(guild,type));
  CREATE TABLE IF NOT EXISTS checkpoints(guild INTEGER PRIMARY KEY,message INTEGER);
  CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,guild INTEGER,actor INTEGER,action TEXT,detail TEXT,created REAL);
  ''')
  columns={r[1]for r in self.db.execute('PRAGMA table_info(rewards)')}
  with self.atomic():
   if 'transport'not in columns:
    self.db.execute("ALTER TABLE rewards ADD COLUMN transport TEXT NOT NULL DEFAULT 'api'")
    self.db.execute("UPDATE rewards SET transport='legacy'")
    self.db.execute("UPDATE rewards SET status='migration_hold',detail='Legacy parser outcome needs owner review before API delivery' WHERE status IN ('sending','uncertain','failed')")
    self.db.execute("UPDATE rewards SET transport='api',detail='Unsent reward migrated to KAOS API' WHERE status IN ('pending','waiting_link','choice')")
   if 'attempts'not in columns:self.db.execute('ALTER TABLE rewards ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')
   if 'next_attempt'not in columns:self.db.execute('ALTER TABLE rewards ADD COLUMN next_attempt REAL NOT NULL DEFAULT 0')
   for r in self.db.execute('SELECT guild,config FROM communities').fetchall():
    c=json.loads(r['config'])
    if any(k in c for k in ('transactions_channel','kaos_bot_id','linked_role')):
     c=normalize(c);c['delivery_enabled']=False
     self.db.execute('UPDATE communities SET config=? WHERE guild=?',(json.dumps(c),r['guild']))
 @contextmanager
 def atomic(self):
  with self.lock:
   outer=self.depth==0
   if outer:self.db.execute('BEGIN IMMEDIATE')
   self.depth+=1
   try:
    yield
    if outer:self.db.execute('COMMIT')
   except BaseException:
    if outer:self.db.execute('ROLLBACK')
    raise
   finally:self.depth-=1
 def cfg(self,guild):
  r=self.db.execute('SELECT config FROM communities WHERE guild=?',(guild,)).fetchone()
  return normalize(json.loads(r[0])) if r else defaults()
 def save(self,guild,c,actor=0):
  validate(c)
  with self.atomic():
   self.db.execute('INSERT INTO communities VALUES(?,?) ON CONFLICT(guild) DO UPDATE SET config=excluded.config',(guild,json.dumps(c)))
   self.audit(guild,actor,'configure','Community settings updated')
 def audit(self,guild,actor,action,detail):self.db.execute('INSERT INTO audit(guild,actor,action,detail,created) VALUES(?,?,?,?,?)',(guild,actor,action,detail,time.time()))
 def balance(self,guild,uid):
  r=self.db.execute('SELECT balance FROM wallets WHERE guild=? AND uid=?',(guild,uid)).fetchone();return r[0] if r else 0
 def money(self,guild,uid,amount,reason,reference):
  if type(amount)is not int or abs(amount)>1000000000000:raise ValueError('Invalid ticket amount.')
  with self.atomic():
   if self.db.execute('SELECT 1 FROM ledger WHERE reference=?',(reference,)).fetchone():return False
   current=self.balance(guild,uid)
   if not 0<=current+amount<=1000000000000:raise ValueError('Insufficient tickets or balance limit exceeded.')
   self.db.execute('INSERT INTO wallets VALUES(?,?,?) ON CONFLICT(guild,uid) DO UPDATE SET balance=excluded.balance',(guild,uid,current+amount))
   self.db.execute('INSERT INTO ledger(guild,uid,delta,reason,reference,created) VALUES(?,?,?,?,?,?)',(guild,uid,amount,reason,reference,time.time()))
   return True
 def linked(self,guild,uid,roles=()):
  r=self.db.execute('SELECT status,checked FROM api_links WHERE guild=? AND uid=?',(guild,uid)).fetchone()
  return bool(r and r['status']==1 and time.time()-r['checked']<900)
 def cache_api_link(self,guild,uid,status):
  self.db.execute('INSERT INTO api_links VALUES(?,?,?,?) ON CONFLICT(guild,uid) DO UPDATE SET status=excluded.status,checked=excluded.checked',(guild,uid,None if status is None else int(status),time.time()))
 def transfer(self,guild,source,target,amount,reference):
  if source==target or type(amount)is not int or not 1<=amount<=1000000:raise ValueError('Choose another player and a positive amount up to 1,000,000.')
  with self.atomic():
   if not self.cfg(guild)['transfers_enabled']:raise ValueError('Ticket transfers are disabled.')
   if self.money(guild,source,-amount,'Player transfer',reference+':debit'):self.money(guild,target,amount,'Player transfer',reference+':credit')
 def close(self):self.db.close()
