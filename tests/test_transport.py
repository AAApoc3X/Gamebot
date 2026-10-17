import asyncio,json,unittest
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
import discord
from storage import Store
from engine import Engine
from configuration import defaults
from delivery import Delivery
from purchases import Purchases
from bot import GamesBot,attach_commands,SessionView,Lobby,Panel,guard
class Transport(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.s=Store(':memory:');c=defaults();c.update(enabled=True,delivery_enabled=True,allow_unlinked=True,reward_mode='points',games_channel=10,transactions_channel=20,kaos_bot_id=30);self.s.save(1,c);self.e=Engine(self.s);self.s.money(1,101,100,'seed','seed');self.e.start(1,101,'supply_drop','base','points','a');self.c=c
 async def asyncTearDown(self):self.s.close()
 def fake(self,send):
  member=SimpleNamespace(roles=[]);guild=SimpleNamespace(me=object(),get_member=lambda uid:member,get_channel=lambda cid:send)
  return SimpleNamespace(get_guild=lambda gid:guild,user=SimpleNamespace(id=77))
 async def test_unlinked_reward_waits_and_linked_sends(self):
  class Channel:
   def permissions_for(self,x):return SimpleNamespace(view_channel=True,send_messages=True,read_message_history=True)
   async def send(self,*a,**k):self.text=a[0];return SimpleNamespace(id=99)
  ch=Channel();d=Delivery(self.fake(ch),self.s)
  with patch('delivery.discord.TextChannel',Channel):
   await d.tick();self.assertEqual(self.s.db.execute('SELECT status FROM rewards').fetchone()[0],'waiting_link');self.s.verify(1,101,True,1);d.last=0;await d.tick()
  self.assertEqual(self.s.db.execute('SELECT status FROM rewards').fetchone()[0],'sent');self.assertIn('[POINTS]',ch.text);self.assertTrue(ch.text.endswith('<@30>'))
 async def test_send_timeout_not_replayed(self):
  class Channel:
   calls=0
   def permissions_for(self,x):return SimpleNamespace(view_channel=True,send_messages=True,read_message_history=True)
   async def send(self,*a,**k):self.calls+=1;raise TimeoutError()
  ch=Channel();self.s.verify(1,101,True,1);d=Delivery(self.fake(ch),self.s)
  with patch('delivery.discord.TextChannel',Channel),self.assertLogs('delivery',level='ERROR'):
   await d.tick()
  d.last=0;await d.tick();self.assertEqual(ch.calls,1);self.assertEqual(self.s.db.execute('SELECT status FROM rewards').fetchone()[0],'uncertain')
 async def test_restart_sending_becomes_uncertain(self):
  self.s.db.execute('UPDATE rewards SET status="sending"');Delivery(self.fake(None),self.s);self.assertEqual(self.s.db.execute('SELECT status FROM rewards').fetchone()[0],'uncertain')
 async def test_delivery_pause(self):
  self.c['delivery_enabled']=False;self.s.save(1,self.c);d=Delivery(self.fake(None),self.s);await d.tick();self.assertEqual(self.s.db.execute('SELECT status FROM rewards').fetchone()[0],'pending')
 async def test_webhook_url_requires_secret(self):
  self.c['products']={'10':5};self.c['purchase_store_id']=77;self.s.save(1,self.c);secret='x'*64;p=Purchases(self.s,self.e,secret);client=TestClient(TestServer(p.app()));await client.start_server()
  try:
   payload={'event':'payment.success','mode':'live','store_id':77,'data':{'id':'paid1','type':1,'user':{'discord_id':'101'},'basket':[{'id':'10','quantity':'2'}]}}
   r=await client.post('/tip4serv/wrong',json=payload);self.assertEqual(r.status,404)
   r=await client.post('/tip4serv/'+secret,json=payload);self.assertEqual(r.status,200);self.assertEqual((await r.json())['credited'],10)
   r=await client.post('/tip4serv/'+secret,json=payload);self.assertEqual((await r.json())['credited'],0)
   r=await client.post('/tip4serv/'+secret,data='broken');self.assertEqual(r.status,400)
  finally:await client.close()
 async def test_discord_command_schema_and_views(self):
  b=attach_commands(GamesBot(':memory:'))
  try:
   for c in b.tree.get_commands():
    if hasattr(c,'commands'):
     self.assertLessEqual(len(c.commands),25)
     for cc in c.commands:self.assertLessEqual(len(cc.description),100);cc.to_dict(b.tree)
    else:c.to_dict(b.tree)
   self.assertTrue(Panel('daily').is_persistent());self.assertTrue(Panel('games').is_persistent());self.assertEqual(len(Lobby(101).children),4)
   for game in ('rps','minefield','higher_lower','deal_or_keep','pick_a_crate','treasure_dig'):
    b.store.save(1,self.c);b.store.money(1,101,100,'seed',game);r=b.engine.start(1,101,game,'base','points',game);self.assertGreater(len(SessionView(b,r).children),0);b.store.db.execute('UPDATE sessions SET status="done" WHERE id=?',(game,))
  finally:b.store.close()
 async def test_access_guards(self):
  # Real Member type is patched only to provide a minimal Discord-independent fixture.
  b=SimpleNamespace(store=self.s)
  class Member:
   id=102;roles=[];guild_permissions=SimpleNamespace(manage_guild=False)
  i=SimpleNamespace(guild=SimpleNamespace(owner_id=101),guild_id=1,channel_id=10,user=Member(),client=b)
  with patch('bot.discord.Member',Member):
   guard(i,player=True)
   with self.assertRaises(ValueError):guard(i)
   i.user.guild_permissions=SimpleNamespace(manage_guild=True);guard(i)
   with self.assertRaises(ValueError):guard(i,owner=True)
   i.channel_id=40
   with self.assertRaises(ValueError):guard(i,player=True)
   i.user.id=101;guard(i,owner=True)
if __name__=='__main__':unittest.main()
