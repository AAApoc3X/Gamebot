import asyncio,json,os,sqlite3,tempfile,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from cryptography.fernet import Fernet
from storage import Store
from engine import Engine
from configuration import defaults,normalize
from delivery import Delivery
from kaos_api import KaosAPI,APIError,KeyVault,parse_link,reward_request
from purchases import Purchases
from bot import GamesBot,attach_commands,SessionView,Lobby,Panel,guard

class Response:
 def __init__(self,status=200,data=None,headers=None):self.status=status;self.data=data;self.headers=headers or {}
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def json(self):
  if isinstance(self.data,Exception):raise self.data
  return self.data
class Session:
 def __init__(self,responses):self.responses=list(responses);self.calls=[]
 def request(self,method,url,**kw):
  self.calls.append((method,url,kw));v=self.responses.pop(0)
  if isinstance(v,Exception):raise v
  return v

class Transport(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.env=patch.dict(os.environ,{'KAOS_API_KEY_1':'test-key-one','KAOS_API_KEY_2':'test-key-two'},clear=True);self.env.start()
  self.s=Store(':memory:');c=defaults();c.update(enabled=True,delivery_enabled=True,allow_unlinked=True,reward_mode='points',games_channel=10);self.s.save(1,c);self.e=Engine(self.s);self.s.money(1,101,100,'seed','seed');self.e.start(1,101,'supply_drop','base','points','a');self.c=c
 async def asyncTearDown(self):self.s.close();self.env.stop()
 def worker(self,responses):
  session=Session(responses);api=KaosAPI(self.s,session);d=Delivery(SimpleNamespace(),self.s,api);return d,session,api
 def reward(self):return self.s.db.execute('SELECT * FROM rewards').fetchone()
 async def test_unlinked_waits_then_api_accepts(self):
  d,session,api=self.worker([Response(data={'linked':False})]);await d.tick();self.assertEqual(self.reward()['status'],'waiting_link')
  self.s.db.execute('UPDATE api_links SET checked=0');self.s.db.execute('UPDATE rewards SET next_attempt=0');session.responses.extend([Response(data={'data':{'uid':'101'}}),Response()]);await d.tick();self.assertEqual(self.reward()['status'],'accepted');call=session.calls[-1];self.assertEqual(call[0],'POST');self.assertTrue(call[1].endswith('/v1/1/1/economy/credit'));self.assertEqual(call[2]['json']['uid'],'101');self.assertIn('idempotency_key',call[2]['json'])
 async def test_timeout_retry_uses_identical_body_and_key(self):
  self.s.cache_api_link(1,101,True);d,session,api=self.worker([TimeoutError(),Response()]);await d.tick();self.assertEqual(self.reward()['status'],'pending');self.assertGreater(self.reward()['next_attempt'],time.time());self.s.db.execute('UPDATE rewards SET next_attempt=0');await d.tick();self.assertEqual(self.reward()['status'],'accepted');self.assertEqual(session.calls[0][2]['json'],session.calls[1][2]['json']);self.assertEqual(self.reward()['attempts'],2)
 async def test_api_sending_resumes_but_accepted_never_replays(self):
  self.s.cache_api_link(1,101,True);self.s.db.execute('UPDATE rewards SET status="sending"');d,session,api=self.worker([Response()]);self.assertEqual(self.reward()['status'],'pending');await d.tick();await d.tick();self.assertEqual(len(session.calls),1)
 async def test_api_4xx_fails_without_automatic_retry(self):
  self.s.cache_api_link(1,101,True);d,session,api=self.worker([Response(403)]);await d.tick();self.assertEqual(self.reward()['status'],'failed');await d.tick();self.assertEqual(len(session.calls),1);self.assertNotIn('test-key',self.reward()['detail'])
 async def test_429_and_5xx_backoff(self):
  for response in (Response(429,headers={'Retry-After':'123'}),Response(503)):
   self.s.db.execute('UPDATE rewards SET status="pending",next_attempt=0');self.s.cache_api_link(1,101,True);d,session,api=self.worker([response]);await d.tick();self.assertEqual(self.reward()['status'],'pending');self.assertGreater(self.reward()['next_attempt'],time.time()+20)
 async def test_paused_delivery_does_not_request(self):
  self.c['delivery_enabled']=False;self.s.save(1,self.c);d,session,api=self.worker([]);await d.tick();self.assertFalse(session.calls)
 async def test_uid_lookup_rejects_mismatch_and_stale_positive(self):
  self.s.cache_api_link(1,101,True);api=KaosAPI(self.s,Session([Response(data={'uid':'102'})]))
  with self.assertRaises(APIError):await api.link(1,101,force=True)
  self.assertFalse(self.s.linked(1,101))
 async def test_lookup_404_and_envelopes(self):
  self.assertTrue(parse_link({'result':{'linked':True}},101));self.assertFalse(parse_link({'found':False},101));self.assertIsNone(parse_link({'ok':True},101))
  api=KaosAPI(self.s,Session([Response(404)]));self.assertFalse(await api.link(1,101))
 async def test_route_and_keys_are_community_scoped(self):
  s=Session([Response(),Response()]);api=KaosAPI(self.s,s);await api.request(1,'POST','/v1/1/1/economy/credit',body={});await api.request(2,'POST','/v1/2/1/economy/credit',body={});self.assertEqual(s.calls[0][2]['headers']['Authorization'],'Bearer test-key-one');self.assertEqual(s.calls[1][2]['headers']['Authorization'],'Bearer test-key-two')
  with self.assertRaises(ValueError):await api.request(1,'GET','/v1/2/whoami')
 async def test_generic_key_requires_explicit_guild_binding(self):
  with patch.dict(os.environ,{'KAOS_API_KEY':'generic'},clear=True):self.assertIsNone(KeyVault(self.s).get(1))
  with patch.dict(os.environ,{'KAOS_API_KEY':'generic','KAOS_API_GUILD_ID':'1'},clear=True):self.assertEqual(KeyVault(self.s).get(1),'generic');self.assertIsNone(KeyVault(self.s).get(2))
 async def test_key_encryption_and_export_separation(self):
  os.environ.pop('KAOS_API_KEY_1');os.environ['KAOS_KEY_ENCRYPTION_KEY']=Fernet.generate_key().decode();vault=KeyVault(self.s);vault.save(1,'private-kaos-test-token',101);encrypted=self.s.db.execute('SELECT token FROM api_keys').fetchone()[0];self.assertNotIn('private-kaos',encrypted);self.assertEqual(vault.get(1),'private-kaos-test-token');self.assertNotIn('private-kaos',json.dumps(self.s.cfg(1)));self.assertIsNone(vault.get(3))
  with patch.dict(os.environ,{'KAOS_KEY_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
   with self.assertRaises(ValueError):vault.get(1)
 async def test_whoami_rejects_other_guild_and_limits(self):
  api=KaosAPI(self.s,Session([Response(data={'sid':'2'})]))
  with self.assertRaises(APIError):await api.check(1)
  api=KaosAPI(self.s,Session([Response(data={'sid':'1'})for _ in range(5)]))
  for _ in range(5):await api.check(1)
  with self.assertRaises(APIError):await api.check(1)
 async def test_all_reward_routes_and_stable_ids(self):
  r=dict(self.reward());r['config']=json.dumps({'server_id':4})
  for kind,path in [('kit','bank/kit'),('item','bank/item'),('points','economy/credit')]:
   r['payload']=json.dumps({'kind':kind,'name':'starter','quantity':2});a,b=reward_request(r);self.assertTrue(a.endswith('/4/'+path));self.assertEqual(b['uid'],'101');self.assertEqual(reward_request(r),(a,b))
 async def test_webhook_authentication_still_works(self):
  self.c['products']={'10':5};self.c['purchase_store_id']=77;self.s.save(1,self.c);secret='x'*64;p=Purchases(self.s,self.e,secret);client=TestClient(TestServer(p.app()));await client.start_server()
  try:
   payload={'event':'payment.success','mode':'live','store_id':77,'data':{'id':'paid1','type':1,'user':{'discord_id':'101'},'basket':[{'id':'10','quantity':'2'}]}}
   r=await client.post('/tip4serv/wrong',json=payload);self.assertEqual(r.status,404);r=await client.post('/tip4serv/'+secret,json=payload);self.assertEqual((await r.json())['credited'],10);r=await client.post('/tip4serv/'+secret,json=payload);self.assertEqual((await r.json())['credited'],0)
  finally:await client.close()
 async def test_discord_command_payloads_and_views(self):
  b=attach_commands(GamesBot(':memory:'))
  try:
   for c in b.tree.get_commands():
    if hasattr(c,'commands'):
     self.assertLessEqual(len(c.commands),25)
     for cc in c.commands:self.assertLessEqual(len(cc.description),100);cc.to_dict(b.tree)
    else:c.to_dict(b.tree)
   fields=[p.name for p in b.tree.get_command('gamesadmin').get_command('setup').parameters];self.assertNotIn('transactions_channel',fields);self.assertNotIn('kaos_bot',fields);self.assertTrue(Panel('daily').is_persistent());self.assertEqual(len(Lobby(101).children),4)
   for game in ('rps','minefield','higher_lower','deal_or_keep','pick_a_crate','treasure_dig'):
    b.store.save(1,self.c);b.store.money(1,101,100,'seed',game);r=b.engine.start(1,101,game,'base','points',game);self.assertGreater(len(SessionView(b,r).children),0);b.store.db.execute('UPDATE sessions SET status="done" WHERE id=?',(game,))
  finally:await b.kaos.close();b.store.close()
 async def test_access_guards(self):
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

class Migration(unittest.TestCase):
 def test_original_database_migration_is_idempotent(self):
  # Build the exact original schema using the already-delivered source ZIP.
  with tempfile.TemporaryDirectory()as tmp:
   path=Path(tmp)/'g.sqlite3';old=sqlite3.connect(path);old.executescript((Path(__file__).parent/'fixtures'/'legacy_schema.sql').read_text());c=defaults();c.update(enabled=True,delivery_enabled=True,reward_mode='points',games_channel=10,transactions_channel=20,kaos_bot_id=30,linked_role=99)
   old.execute('INSERT INTO communities VALUES(?,?)',(1,json.dumps(c)));old.execute('INSERT INTO wallets VALUES(1,101,50)')
   for index,status in enumerate(('sent','sending','uncertain','failed','pending','waiting_link','choice')):
    old.execute('INSERT INTO rewards(id,guild,uid,tier,config,kind,payload,status,channel,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(str(index),1,101,'base',json.dumps(c),'points',json.dumps({'kind':'points','name':'','quantity':100}),status,20,time.time()))
   old.commit();old.close();new=Store(path);self.assertEqual(new.balance(1,101),50);self.assertFalse(new.cfg(1)['delivery_enabled']);self.assertNotIn('transactions_channel',new.cfg(1))
   rows={r['id']:dict(r)for r in new.db.execute('SELECT * FROM rewards')};self.assertEqual(rows['0']['status'],'sent');self.assertEqual(rows['0']['transport'],'legacy')
   for key in ('1','2','3'):self.assertEqual(rows[key]['status'],'migration_hold')
   for key in ('4','5','6'):self.assertEqual(rows[key]['transport'],'api')
   c=new.cfg(1);c['delivery_enabled']=True;new.save(1,c);new.close();again=Store(path);self.assertTrue(again.cfg(1)['delivery_enabled']);self.assertEqual(again.balance(1,101),50);again.close()
if __name__=='__main__':unittest.main()
