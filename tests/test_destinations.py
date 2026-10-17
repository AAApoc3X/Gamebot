import json,random,unittest
from storage import Store
from engine import Engine
from configuration import defaults,TIERS
from kaos_api import reward_request
class DestinationTests(unittest.TestCase):
 def setUp(self):
  self.s=Store(':memory:');self.e=Engine(self.s,random.Random(2));self.c=defaults();self.c.update(enabled=True,delivery_enabled=True,allow_unlinked=True,reward_mode='points',games_channel=10);self.c['lottery']['enabled']=True;self.c['lottery']['schedule']['mode']='manual';self.s.save(1,self.c);self.s.money(1,101,1000,'seed','seed');self.d=self.s.destinations;self.d.set(1,1,'AAApocalypse 3x');self.d.set(1,2,'Doomsday 6x Solo Duo')
 def tearDown(self):self.s.close()
 def test_labels_and_guild_isolation(self):
  self.assertEqual(len(self.d.options(1)),2);self.assertEqual(self.d.options(2),[{'slot':1,'label':'Game server 1'}]);self.d.save_preference(1,101,2);self.assertIsNone(self.d.preference(2,101))
 def test_before_requires_selection_and_does_not_charge(self):
  with self.assertRaises(ValueError):self.e.start(1,101,'supply_drop','base','points','a')
  self.assertEqual(self.s.balance(1,101),1000)
 def test_preference_and_immutable_destination(self):
  self.d.save_preference(1,101,2);self.e.start(1,101,'supply_drop','base','points','a');r=self.s.db.execute('SELECT * FROM rewards').fetchone();self.assertEqual(json.loads(r['config'])['server_id'],2);path,body=reward_request(r);self.assertIn('/1/2/',path)
  self.d.save_preference(1,101,1);self.d.remove(1,2);r2=self.s.db.execute('SELECT * FROM rewards').fetchone();self.assertEqual(reward_request(r2),(path,body))
  with self.assertRaises(ValueError):self.e.select_server(1,101,r['id'],1)
 def test_after_holds_until_owner_of_reward_selects(self):
  self.d.set_timing(1,'after');self.e.start(1,101,'supply_drop','base','points','a');r=self.s.db.execute('SELECT * FROM rewards').fetchone();self.assertEqual(r['status'],'awaiting_server')
  with self.assertRaises(ValueError):self.e.select_server(1,102,r['id'],2)
  with self.assertRaises(ValueError):self.e.select_server(2,101,r['id'],2)
  self.e.select_server(1,101,r['id'],2);r=self.s.db.execute('SELECT * FROM rewards').fetchone();self.assertEqual(r['status'],'pending');self.assertIn('/1/2/',reward_request(r)[0])
  with self.assertRaises(ValueError):self.e.select_server(1,101,r['id'],1)
 def test_bundle_children_share_server_with_both_choice_orders(self):
  self.d.set_timing(1,'after');self.c.update(reward_mode='both',choice_timing='after')
  for t in TIERS:self.c['prizes'][t]['kits']=[{'weight':1,'rewards':[{'kind':'kit','name':'starter','quantity':1},{'kind':'item','name':'stone.hatchet','quantity':1}]}]
  self.s.save(1,self.c)
  self.e.start(1,101,'supply_drop','base','kits','a');r=self.s.db.execute('SELECT * FROM rewards').fetchone();self.e.choose_reward(1,101,r['id'],'kits');rows=self.s.db.execute('SELECT * FROM rewards').fetchall();self.assertEqual(len(rows),2);self.e.select_server(1,101,rows[0]['id'],2)
  self.assertTrue(all(json.loads(r['config'])['server_id']==2 for r in self.s.db.execute('SELECT * FROM rewards')))
  self.e.start(1,101,'supply_drop','base','kits','b');r=self.s.db.execute('SELECT * FROM rewards WHERE status="choice"').fetchone();self.e.select_server(1,101,r['id'],1);self.e.choose_reward(1,101,r['id'],'points');self.assertEqual(json.loads(self.s.db.execute('SELECT config FROM rewards WHERE id LIKE "game:b%"').fetchone()[0])['server_id'],1)
 def test_lottery_freezes_options_and_entry_destination(self):
  key=self.e.open_lottery(1);self.e.lottery_enter(1,101,key,1,'1,2,3','points','entry',server_id=2);self.d.remove(1,2)
  class Fixed:
   def sample(self,*args):return [1,2,3]
  self.e.rng=Fixed();self.e.settle_lottery(key,True);r=self.s.db.execute('SELECT * FROM rewards').fetchone();self.assertIn('/1/2/',reward_request(r)[0])
 def test_after_lottery_and_bingo_hold(self):
  self.d.set_timing(1,'after');key=self.e.open_lottery(1);self.e.lottery_enter(1,101,key,1,'1,2,3','points','entry')
  class Fixed:
   def sample(self,*args):return [1,2,3]
  old=self.e.rng;self.e.rng=Fixed();self.e.settle_lottery(key,True);self.e.rng=old;self.assertEqual(self.s.db.execute('SELECT status FROM rewards').fetchone()[0],'awaiting_server');key=self.e.open_event(1,'bingo',101);self.e.join_event(1,101,key,'points','bingo');self.e.settle_event(key,True);self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM rewards WHERE status="awaiting_server"').fetchone()[0],2)
 def test_ticket_giveaway_does_not_require_destination(self):
  key=self.e.open_event(1,'giveaway',101);self.e.join_event(1,101,key,'points','giveaway');self.assertEqual(len(self.s.db.execute('SELECT * FROM entries').fetchall()),1)
 def test_catalog_changes_do_not_reroute_paid_after_rewards(self):
  self.d.set_timing(1,'after');self.e.start(1,101,'supply_drop','base','points','a');r=self.s.db.execute('SELECT * FROM rewards').fetchone();self.d.remove(1,2);self.e.select_server(1,101,r['id'],2);self.assertEqual(json.loads(self.s.db.execute('SELECT config FROM rewards').fetchone()[0])['server_id'],2)
 def test_empty_catalog_and_invalid_removal(self):
  with self.assertRaises(ValueError):self.d.remove(1,None)
  self.d.remove(1,1);self.d.remove(1,2)
  with self.assertRaises(ValueError):self.e.start(1,101,'supply_drop','base','points','a')
if __name__=='__main__':unittest.main()
