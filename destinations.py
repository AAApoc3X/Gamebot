"""Community-owned KAOS server labels and player preferences; no cross-guild routing."""
import json
class Destinations:
 def __init__(self,db):
  self.db=db;db.executescript('''
  CREATE TABLE IF NOT EXISTS server_catalog(guild INTEGER,slot INTEGER,label TEXT,active INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(guild,slot));
  CREATE TABLE IF NOT EXISTS destination_settings(guild INTEGER PRIMARY KEY,timing TEXT NOT NULL DEFAULT 'before');
  CREATE TABLE IF NOT EXISTS server_preferences(guild INTEGER,player TEXT,slot INTEGER,PRIMARY KEY(guild,player));
  ''')
 def configured(self,guild):return self.db.execute('SELECT 1 FROM destination_settings WHERE guild=?',(guild,)).fetchone()is not None
 def timing(self,guild):
  r=self.db.execute('SELECT timing FROM destination_settings WHERE guild=?',(guild,)).fetchone();return r[0]if r else 'before'
 def options(self,guild,fallback=1):
  if not self.configured(guild):return [{'slot':fallback,'label':f'Game server {fallback}'}]
  return [dict(slot=r[0],label=r[1])for r in self.db.execute('SELECT slot,label FROM server_catalog WHERE guild=? AND active=1 ORDER BY slot',(guild,))]
 def set(self,guild,slot,label):
  if type(slot)is not int or not 1<=slot<=100:raise ValueError('Use the actual KAOS slot 1–100.')
  if not isinstance(label,str)or not 1<=len(label.strip())<=75 or not label.isprintable():raise ValueError('Server name needs 1–75 printable characters.')
  if slot not in [x['slot']for x in self.options(guild)] and len(self.options(guild))>=25:raise ValueError('Maximum 25 active servers per community.')
  with self.db:
   self.db.execute('INSERT OR IGNORE INTO destination_settings(guild) VALUES(?)',(guild,))
   self.db.execute('INSERT INTO server_catalog VALUES(?,?,?,1) ON CONFLICT(guild,slot) DO UPDATE SET label=excluded.label,active=1',(guild,slot,label.strip()))
 def remove(self,guild,slot):
  if type(slot)is not int or not 1<=slot<=100:raise ValueError('Select the actual KAOS server ID to remove.')
  with self.db:
   self.db.execute('INSERT OR IGNORE INTO destination_settings(guild) VALUES(?)',(guild,));self.db.execute('UPDATE server_catalog SET active=0 WHERE guild=? AND slot=?',(guild,slot))
 def set_timing(self,guild,timing):
  if timing not in ('before','after'):raise ValueError('Select before or after.')
  with self.db:self.db.execute('INSERT INTO destination_settings VALUES(?,?) ON CONFLICT(guild) DO UPDATE SET timing=excluded.timing',(guild,timing))
 def preference(self,guild,player):
  r=self.db.execute('SELECT slot FROM server_preferences WHERE guild=? AND player=?',(guild,str(player).casefold())).fetchone();return r[0]if r else None
 def resolve(self,guild,slot=None,fallback=1,player=None):
  options=self.options(guild,fallback)
  if not options:raise ValueError('Owner must add at least one available game server.')
  if slot is None and player is not None:slot=self.preference(guild,player)
  if slot is None and len(options)==1:slot=options[0]['slot']
  if slot not in [x['slot']for x in options]:raise ValueError('Select an available game server from the dropdown.')
  return slot
 def save_preference(self,guild,player,slot,fallback=1):
  slot=self.resolve(guild,slot,fallback)
  with self.db:self.db.execute('INSERT INTO server_preferences VALUES(?,?,?) ON CONFLICT(guild,player) DO UPDATE SET slot=excluded.slot',(guild,str(player).casefold(),slot))
 def snapshot(self,guild,c,uid,slot=None):
  from copy import deepcopy
  c=deepcopy(c);c['_destination_options']=self.options(guild,c['server_id']);c['_destination_timing']=self.timing(guild)
  if not c['_destination_options']:raise ValueError('No game servers are available. Contact the owner.')
  c['server_id']=None if c['_destination_timing']=='after'else self.resolve(guild,slot,c['server_id'],uid)
  return c
