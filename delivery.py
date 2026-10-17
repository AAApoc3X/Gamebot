"""KAOS log parser transport. 'Sent' is not an acknowledgement of game delivery."""
import json,re,time,logging
import discord
from configuration import safe_name
log=logging.getLogger(__name__)

def parser_command(uid,server_id,kaos_id,reward):
 if any(type(x)is not int or x<=0 for x in (uid,server_id,kaos_id)):raise ValueError('Invalid Discord IDs or KAOS server ID.')
 kind=reward['kind'];quantity=reward['quantity']
 if type(quantity)is not int or not 1<=quantity<=1000000000:raise ValueError('Invalid reward quantity.')
 if kind=='points':tail=f'[POINTS][{quantity}]'
 elif kind in ('kit','item'):tail=f'[{kind.upper()}][{safe_name(reward["name"])}][{quantity}]'
 else:raise ValueError('Unsupported parser reward type.')
 return f'[KAOS][ADD][<@{uid}>][{server_id}]={tail} <@{kaos_id}>'

class Delivery:
 def __init__(self,bot,store):
  self.bot=bot;self.s=store;self.last=0
  # A crash during send has an unknown outcome. Never blindly replay it.
  self.s.db.execute('UPDATE rewards SET status="uncertain",detail="Restart during send; inspect Transactions channel before retry" WHERE status="sending"')
 async def tick(self):
  if time.monotonic()-self.last<1.2:return
  rows=self.s.db.execute('SELECT * FROM rewards WHERE status IN ("pending","waiting_link") ORDER BY checked,created LIMIT 100').fetchall()
  for row in rows:
   self.s.db.execute('UPDATE rewards SET checked=? WHERE id=?',(time.time(),row['id']))
   current=self.s.cfg(row['guild']);frozen=json.loads(row['config'])
   if not current['delivery_enabled']:continue
   guild=self.bot.get_guild(row['guild'])
   if not guild:continue
   try:member=guild.get_member(row['uid'])or await guild.fetch_member(row['uid'])
   except discord.NotFound:
    self.s.db.execute('UPDATE rewards SET status="waiting_link",detail="Player must join server and link KAOS" WHERE id=?',(row['id'],));continue
   if not self.s.linked(row['guild'],row['uid'],[x.id for x in member.roles]):
    self.s.db.execute('UPDATE rewards SET status="waiting_link",detail="Waiting for verified KAOS link" WHERE id=?',(row['id'],));continue
   try:
    channel=guild.get_channel(row['channel'])or await guild.fetch_channel(row['channel'])
    if not isinstance(channel,discord.TextChannel):raise ValueError('Transactions channel must be a server text channel.')
    p=channel.permissions_for(guild.me)
    if not (p.view_channel and p.send_messages and p.read_message_history):raise ValueError('Bot needs View Channel, Send Messages and Read Message History in Transactions channel.')
    cmd=parser_command(row['uid'],frozen['server_id'],frozen['kaos_bot_id'],json.loads(row['payload']))
   except (ValueError,discord.NotFound,discord.Forbidden):
    self.s.db.execute('UPDATE rewards SET status="failed",detail="Check Transactions channel, permissions and reward configuration" WHERE id=?',(row['id'],));continue
   # Durable intent before external mutation. SDK reconnect/retry ambiguity is handled conservatively.
   self.s.db.execute('UPDATE rewards SET status="sending",detail="Sending parser command" WHERE id=?',(row['id'],));self.last=time.monotonic()
   try:
    msg=await channel.send(f'Games reward ID: {row["id"]}\n{cmd}',allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=frozen['kaos_bot_id']),discord.Object(id=row['uid'])],roles=False,everyone=False))
   except discord.Forbidden:
    self.s.db.execute('UPDATE rewards SET status="failed",detail="Discord denied sending" WHERE id=?',(row['id'],))
   except Exception:
    self.s.db.execute('UPDATE rewards SET status="uncertain",detail="Send outcome unknown; inspect Transactions channel before retry" WHERE id=?',(row['id'],));log.exception('Parser send outcome unknown')
   else:self.s.db.execute('UPDATE rewards SET status="sent",message=?,detail="Posted to KAOS; in-game delivery not confirmed" WHERE id=?',(msg.id,row['id']))
   return
 async def reconcile(self,guild,key):
  r=self.s.db.execute('SELECT * FROM rewards WHERE id=? AND guild=?',(key,guild.id)).fetchone()
  if not r:raise ValueError('Unknown reward ID.')
  channel=guild.get_channel(r['channel'])or await guild.fetch_channel(r['channel'])
  # Only exact receipt line on this bot's own message is evidence of a send.
  marker='Games reward ID: '+key
  async for message in channel.history(limit=1000):
   if message.author.id==self.bot.user.id and message.content.splitlines()[:1]==[marker]:
    self.s.db.execute('UPDATE rewards SET status="sent",message=?,detail="Found original parser post; KAOS delivery not confirmed" WHERE id=?',(message.id,key));return True
  return False
