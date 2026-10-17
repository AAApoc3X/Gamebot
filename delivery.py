"""KAOS API reward worker. Never posts parser commands to Discord."""
import json,time
from kaos_api import APIError,reward_request
class Delivery:
 def __init__(self,bot,store,api):
  self.bot=bot;self.s=store;self.api=api
  # Only API sends are safe to replay automatically, using their original idempotency key.
  self.s.db.execute('UPDATE rewards SET status="pending",detail="Resuming API send with original idempotency key" WHERE transport="api" AND status="sending"')
 async def tick(self):
  now=time.time()
  rows=self.s.db.execute('SELECT * FROM rewards WHERE transport="api" AND status IN ("pending","waiting_link") AND next_attempt<=? ORDER BY checked,created LIMIT 50',(now,)).fetchall()
  for r in rows:
   if not self.s.cfg(r['guild'])['delivery_enabled']:continue
   self.s.db.execute('UPDATE rewards SET checked=? WHERE id=?',(now,r['id']))
   try:
    if not await self.api.link(r['guild'],r['uid']):
     self.s.db.execute('UPDATE rewards SET status="waiting_link",next_attempt=?,detail="Waiting for player to complete KAOS /link" WHERE id=?',(now+60,r['id']));continue
    path,body=reward_request(r)
    self.s.db.execute('UPDATE rewards SET status="sending",attempts=attempts+1,detail="Sending KAOS API reward" WHERE id=?',(r['id'],))
    await self.api.request(r['guild'],'POST',path,body=body)
   except (APIError,ValueError)as exc:
    retry=isinstance(exc,APIError)and exc.retryable
    # Backoff is durable; keep the exact frozen reward and idempotency key.
    delay=max(exc.delay, min(3600,2**min(r['attempts']+1,10)))if retry else 0
    self.s.db.execute('UPDATE rewards SET status=?,next_attempt=?,detail=? WHERE id=?',('pending'if retry else 'failed',now+delay,str(exc)[:300],r['id']))
   else:self.s.db.execute('UPDATE rewards SET status="accepted",detail="KAOS API accepted reward; kits/items deposited to bank",next_attempt=0 WHERE id=?',(r['id'],))
   return
 async def reconcile(self,guild,key):
  """Read-only migration aid for an old parser send; never submits parser commands."""
  r=self.s.db.execute('SELECT * FROM rewards WHERE id=? AND guild=? AND transport="legacy"',(key,guild.id)).fetchone()
  if not r:raise ValueError('This is not a legacy parser reward.')
  import discord
  channel=guild.get_channel(r['channel'])or await guild.fetch_channel(r['channel']);marker='Games reward ID: '+key
  async for message in channel.history(limit=1000):
   if message.author.id==self.bot.user.id and message.content.splitlines()[:1]==[marker]:
    self.s.db.execute('UPDATE rewards SET status="sent",message=?,detail="Legacy parser post found; never replay through API automatically" WHERE id=?',(message.id,key));return True
  return False
