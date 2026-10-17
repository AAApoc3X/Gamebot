import unittest,random,json,tempfile,os
from datetime import datetime,timezone
from storage import Store
from engine import Engine,next_due,lottery_probabilities
from configuration import defaults,validate,refund,INSTANT,TIERS
from delivery import parser_command
from purchases import Purchases
class Clock:
 def __init__(self):self.now=datetime(2026,10,17,16,tzinfo=timezone.utc).timestamp()
 def __call__(self):return self.now
class Rules(unittest.TestCase):
 def setUp(self):
  self.s=Store(':memory:');self.clock=Clock();self.e=Engine(self.s,random.Random(7),self.clock);self.c=defaults();self.c.update(enabled=True,delivery_enabled=True,allow_unlinked=True,reward_mode='points',games_channel=10,transactions_channel=20,kaos_bot_id=30);self.c['lottery']['enabled']=True;self.c['lottery']['schedule']['mode']='manual';self.s.save(1,self.c);self.s.money(1,101,10000,'seed','seed')
 def tearDown(self):self.s.close()
 def test_no_overdraft(self):
  with self.assertRaises(ValueError):self.s.transfer(1,101,102,10001,'a')
  self.assertEqual(self.s.balance(1,101),10000);self.assertEqual(self.s.balance(1,102),0)
 def test_transfer_idempotency_and_conservation(self):
  self.s.transfer(1,101,102,10,'a');self.s.transfer(1,101,102,10,'a');self.assertEqual(self.s.balance(1,101)+self.s.balance(1,102),10000);self.assertEqual(self.s.balance(1,102),10)
 def test_daily_button_and_command_share_claim(self):
  self.e.claim(1,101,'button')
  with self.assertRaises(ValueError):self.e.claim(1,101,'command')
  self.clock.now+=86400;self.e.claim(1,101,'command');self.assertEqual(self.s.balance(1,101),10002)
 def test_midnight_claim(self):
  self.clock.now=datetime(2026,10,18,3,59,tzinfo=timezone.utc).timestamp();self.e.claim(1,101,'button');self.clock.now+=120;self.e.claim(1,101,'button')
 def test_24hour_claim(self):
  self.c['daily']['reset']='24h';self.s.save(1,self.c);self.e.claim(1,101,'button');self.clock.now+=86399
  with self.assertRaises(ValueError):self.e.claim(1,101,'command')
  self.clock.now+=1;self.e.claim(1,101,'command')
 def test_link_role_override_and_guild_isolation(self):
  self.c.update(allow_unlinked=False,linked_role=999);self.s.save(1,self.c)
  with self.assertRaises(ValueError):self.e.claim(1,101,'button')
  self.e.claim(1,101,'button',[999]);self.s.verify(1,101,False,1);self.assertFalse(self.s.linked(1,101,[999]));self.s.verify(1,101,True,1);self.assertTrue(self.s.linked(1,101));self.assertFalse(self.s.linked(2,101))
 def test_all_instant_games(self):
  for n,g in enumerate(INSTANT):
   r=self.e.start(1,101,g,'base','points',str(n))
   if r['status']=='active':r=self.e.move(1,101,r['id'],'1')
   self.assertEqual(r['status'],'done');self.assertIn(r['state']['tier'],TIERS)
 def test_duplicate_game_does_not_double_charge_or_reward(self):
  a=self.e.start(1,101,'supply_drop','base','points','one');b=self.e.start(1,101,'supply_drop','base','points','one');self.assertEqual(a,b);self.assertEqual(self.s.balance(1,101),9999);self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM rewards').fetchone()[0],1)
 def test_rps_fixed_tier(self):
  for n,choice in enumerate(('rock','paper','scissors')*5):
   r=self.e.start(1,101,'rps','premium','points',str(n));r=self.e.move(1,101,r['id'],choice)
   if r['state']['result']=='win':self.assertEqual(r['state']['tier'],'premium')
   else:self.assertIsNone(r['state']['tier'])
   with self.assertRaises(ValueError):self.e.move(1,101,r['id'],choice)
 def test_wrong_player_or_second_active_game(self):
  r=self.e.start(1,101,'rps','base','points','one')
  with self.assertRaises(ValueError):self.e.move(1,102,r['id'],'rock')
  with self.assertRaises(ValueError):self.e.start(1,101,'rps','base','points','two')
 def test_interactive_collect(self):
  for n,g in enumerate(('minefield','higher_lower','deal_or_keep')):
   r=self.e.start(1,101,g,'base','points',str(n));r=self.e.move(1,101,r['id'],'collect'if g!='deal_or_keep'else 'keep');self.assertIn(r['state']['tier'],TIERS)
 def test_paid_level_can_raise_prize_floor(self):
  self.c['games']['higher_lower']['odds']['premium']=[0,0,100];self.s.save(1,self.c);r=self.e.start(1,101,'higher_lower','premium','points','p');r=self.e.move(1,101,r['id'],'collect');self.assertEqual(r['state']['tier'],'premium')
 def test_unplayed_rps_timeout_refunds(self):
  self.e.start(1,101,'rps','premium','points','p');self.clock.now+=901;self.e.expire();self.assertEqual(self.s.balance(1,101),10000);self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM rewards').fetchone()[0],0)
 def test_progress_timeout_collects(self):
  self.e.start(1,101,'higher_lower','base','points','p');self.clock.now+=901;self.e.expire();self.assertEqual(self.e.session('p')['status'],'done')
 def test_frozen_game_prize(self):
  self.e.start(1,101,'rps','premium','points','p');self.c['prizes']['premium']['points']['amount']=999;self.s.save(1,self.c)
  class Win:
   def choice(self,x):return 'scissors'
  self.e.rng=Win();self.e.move(1,101,'p','rock');payload=json.loads(self.s.db.execute('SELECT payload FROM rewards').fetchone()[0]);self.assertEqual(payload['quantity'],1000)
 def test_after_reward_choice_once(self):
  self.c.update(reward_mode='both',choice_timing='after')
  for t in TIERS:self.c['prizes'][t]['kits']=[{'weight':1,'rewards':[{'kind':'kit','name':'starter','quantity':1}]}]
  self.s.save(1,self.c);self.e.start(1,101,'supply_drop','base','points','one');r=self.s.db.execute('SELECT id FROM rewards').fetchone()[0];self.e.choose_reward(1,101,r,'kits')
  with self.assertRaises(ValueError):self.e.choose_reward(1,101,r,'points')
  self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM rewards').fetchone()[0],1)
 def test_lottery_quickpick_unique_and_limited(self):
  key=self.e.open_lottery(1);p=self.e.lottery_enter(1,101,key,20,'','points','e');self.assertEqual(len(p),len(set(p)))
  with self.assertRaises(ValueError):self.e.lottery_enter(1,101,key,1,'','points','e2')
 def test_lottery_invalid_picks_no_charge(self):
  key=self.e.open_lottery(1)
  for p in ('1,1,2','0,2,3','1,2,21'):
   with self.assertRaises(ValueError):self.e.lottery_enter(1,101,key,1,p,'points','e')
  self.assertEqual(self.s.balance(1,101),10000)
 def test_lottery_cancel_refunds_bundle_cost(self):
  self.c['lottery']['bundles']={'3':2};self.s.save(1,self.c);key=self.e.open_lottery(1);self.e.lottery_enter(1,101,key,3,'','points','e');self.assertEqual(self.s.balance(1,101),9998);self.e.cancel_draw(key);self.assertEqual(self.s.balance(1,101),10000)
  with self.assertRaises(ValueError):self.e.cancel_draw(key)
 def test_lottery_highest_or_each(self):
  for policy in ('highest','each'):
   self.c['lottery']['payout']=policy;self.s.save(1,self.c);key=self.e.open_lottery(1);self.e.lottery_enter(1,101,key,3,'1,2,3;4,5,6;7,8,9','points',policy);old=self.e.rng
   class Fixed:
    def sample(self,*args):return [1,2,3]
   self.e.rng=Fixed();st=self.e.settle_lottery(key,True);self.e.rng=old;self.assertEqual(st['summary'][0]['matches'],3);self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM rewards WHERE id LIKE ?',('lottery:'+policy+'%',)).fetchone()[0],1)
   if policy=='each':self.assertEqual(self.s.balance(1,101),9996)
   with self.assertRaises(ValueError):self.e.settle_lottery(key,True)
 def test_lottery_snapshot_and_cutoff(self):
  self.c['lottery']['schedule']['mode']='interval';self.c['lottery']['schedule']['minutes']=60;self.s.save(1,self.c);key=self.e.open_lottery(1);self.c['lottery']['cost']=100;self.s.save(1,self.c);self.e.lottery_enter(1,101,key,1,'1,2,3','points','e');self.assertEqual(self.s.balance(1,101),9999);self.clock.now+=55*60
  with self.assertRaises(ValueError):self.e.lottery_enter(1,101,key,1,'4,5,6','points','e2')
 def test_bingo_giveaway_and_duplicate_join(self):
  for typ in ('bingo','giveaway'):
   key=self.e.open_event(1,typ,1)
   for uid in (101,102,103):self.s.money(1,uid,10,'seed',typ+str(uid));self.e.join_event(1,uid,key,'points',typ+str(uid))
   with self.assertRaises(ValueError):self.e.join_event(1,101,key,'points','again')
   self.assertTrue(self.e.settle_event(key,True)['winners'])
  self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM rewards').fetchone()[0],3)
 def test_purchase_deduplication(self):
  self.c['products']={'bundle10':10};self.s.save(1,self.c);self.assertEqual(self.e.purchase(1,101,'bundle10',2,'paid1'),20);self.assertEqual(self.e.purchase(1,101,'bundle10',2,'paid1'),0)
 def test_webhook_live_only_and_payment_replay(self):
  self.c.update(purchase_store_id=77);self.c['products']={'104':10};self.s.save(1,self.c);p=Purchases(self.s,self.e,'x'*64);data={'event':'payment.success','mode':'live','store_id':77,'data':{'id':123,'type':1,'user':{'discord_id':'101'},'basket':[{'id':'104','quantity':'2'}]}}
  self.assertEqual(p.process(data)['credited'],20);data['request_id']='resend';self.assertEqual(p.process(data)['credited'],0);data['mode']='test';self.assertEqual(p.process(data)['status'],'ignored')
 def test_parser_and_input_validation(self):
  self.assertEqual(parser_command(101,1,30,{'kind':'kit','name':'streak5','quantity':1}),'[KAOS][ADD][<@101>][1]=[KIT][streak5][1] <@30>')
  with self.assertRaises(ValueError):parser_command(101,1,30,{'kind':'kit','name':'kit][POINTS][10000','quantity':1})
  c=defaults();c['games']['rps']['odds']['base']=[50,50,1]
  with self.assertRaises(ValueError):validate(c)
 def test_refund_rounding(self):
  self.assertEqual(refund(3,{'mode':'percent','amount':50,'round':'down'}),1);self.assertEqual(refund(3,{'mode':'percent','amount':50,'round':'up'}),2)
 def test_dst_and_weekday_schedule(self):
  ts=datetime(2026,11,1,4,tzinfo=timezone.utc).timestamp();s={'mode':'daily','time':'01:30','minutes':60,'weekdays':[0]};first=next_due(s,'America/New_York',ts);second=next_due(s,'America/New_York',first+1);self.assertGreater(second-first,24*3600);s['mode']='weekly';n=next_due(s,'America/New_York',ts);self.assertEqual(datetime.fromtimestamp(n,timezone.utc).weekday(),0)
 def test_lottery_math(self):
  p=lottery_probabilities(1,20,5);self.assertAlmostEqual(sum(p['one_combination'].values()),1);self.assertAlmostEqual(p['premium_any'],5/1140);self.assertEqual(lottery_probabilities(1,3,1)['premium_any'],1)
 def test_restart_preserves_balance_game_and_draw(self):
  with tempfile.TemporaryDirectory()as tmp:
   path=os.path.join(tmp,'g.sqlite3');s=Store(path);s.save(1,self.c);s.money(1,101,10,'seed','s');e=Engine(s,random.Random(7),self.clock);e.start(1,101,'rps','base','points','one');key=e.open_lottery(1);s.close();s=Store(path);e=Engine(s,random.Random(8),self.clock);self.assertEqual(s.balance(1,101),9);self.assertEqual(e.session('one')['status'],'active');self.assertEqual(e.open_lottery(1),key);s.close()
if __name__=='__main__':unittest.main()
