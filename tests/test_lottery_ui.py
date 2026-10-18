import json,random,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,AsyncMock
import discord
from storage import Store
from engine import Engine
from configuration import defaults
from bot import GamesBot,attach_commands,available_games,Lobby
from lottery_ui import LotteryEntry,NumberModal,validate_numbers,quick_picks,old_picks

class LotteryUITests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.s=Store(':memory:');self.e=Engine(self.s,random.Random(4));self.c=defaults();self.c.update(enabled=True,allow_unlinked=True,reward_mode='points',games_channel=10);self.c['lottery']['enabled']=True;self.c['lottery']['schedule']['mode']='manual';self.s.save(1,self.c);self.s.money(1,101,100,'seed','seed')
  self.guard=Mock();self.reply=AsyncMock();self.link=AsyncMock()
  self.i=SimpleNamespace(user=SimpleNamespace(id=101,roles=[]),guild_id=1,client=SimpleNamespace(store=self.s,engine=self.e),response=SimpleNamespace(edit_message=AsyncMock(),send_modal=AsyncMock(),is_done=lambda:False),edit_original_response=AsyncMock(),data={})
 def tearDown(self):self.s.close()
 def view(self):return LotteryEntry(self.i,self.e.draw(self.e.open_lottery(1)),self.guard,self.reply,self.link)
 async def test_quick_pick_preview_and_exactly_once_purchase(self):
  v=self.view();v.count=3;await v.quick(self.i);reviewed=list(v.picks);self.assertEqual(self.s.balance(1,101),100)
  await v.preview(self.i);self.assertIn('Your numbers',v.text());await v.confirm(self.i)
  self.assertEqual(set(reviewed),old_picks(self.s,v.draw_id,101));self.assertEqual(self.s.balance(1,101),97)
  await v.confirm(self.i);self.assertEqual(self.s.balance(1,101),97)
  self.assertFalse(await v.interaction_check(self.i))
 async def test_manual_boxes_and_no_duplicate_numbers(self):
  v=self.view();await v.manual(self.i);m=self.i.response.send_modal.call_args.args[0];self.assertEqual(len(m.children),3)
  for f,x in zip(m.fields,['1','1','2']):f._value=x
  await m.on_submit(self.i);self.assertFalse(v.picks)
  for f,x in zip(m.fields,['1','2','3']):f._value=x
  await m.on_submit(self.i);self.assertEqual(v.picks,[(1,2,3)])
  await v.preview(self.i);await v.confirm(self.i);self.assertEqual(old_picks(self.s,v.draw_id,101),{(1,2,3)})
 async def test_stale_modal_cannot_alter_new_quick_pick(self):
  v=self.view();await v.manual(self.i);m=self.i.response.send_modal.call_args.args[0]
  for f,x in zip(m.fields,['1','2','3']):f._value=x
  await v.quick(self.i);before=list(v.picks);await m.on_submit(self.i);self.assertEqual(v.picks,before)
 async def test_cancel_does_not_charge(self):
  v=self.view();await v.quick(self.i);await v.cancel(self.i);self.assertEqual(self.s.balance(1,101),100);self.assertFalse(old_picks(self.s,v.draw_id,101))
 async def test_server_and_reward_selection_required_before_review(self):
  self.s.destinations.set(1,1,'First');self.s.destinations.set(1,2,'Second');self.c.update(reward_mode='both')
  for p in self.c['prizes'].values():p['kits']=[{'weight':1,'rewards':[{'kind':'kit','name':'starter','quantity':1}]}]
  self.s.save(1,self.c);v=self.view();await v.quick(self.i)
  with self.assertRaisesRegex(ValueError,'server'):v.ready()
  v.slot=2
  with self.assertRaisesRegex(ValueError,'kits/items'):v.ready()
  v.kind='points';await v.preview(self.i);await v.confirm(self.i)
  target=json.loads(self.s.db.execute('SELECT destination FROM entries').fetchone()[0]);self.assertEqual(target['slot'],2)
 async def test_after_choices_do_not_block_purchase(self):
  self.s.destinations.set(1,1,'First');self.s.destinations.set_timing(1,'after');self.c.update(reward_mode='both',choice_timing='after')
  for p in self.c['prizes'].values():p['kits']=[{'weight':1,'rewards':[{'kind':'kit','name':'starter','quantity':1}]}]
  self.s.save(1,self.c);v=self.view();await v.quick(self.i);await v.preview(self.i);await v.confirm(self.i)
  r=self.s.db.execute('SELECT kind,destination FROM entries').fetchone();self.assertEqual(r['kind'],'choose');self.assertIsNone(json.loads(r['destination'])['slot'])
 async def test_quick_only_draw_keeps_reviewed_numbers(self):
  self.c['lottery']['pick_mode']='quick';self.s.save(1,self.c);v=self.view()
  self.assertNotIn('Pick My Numbers',[c.label for c in v.children if isinstance(c,discord.ui.Button)])
  await v.quick(self.i);picks=list(v.picks);await v.preview(self.i);await v.confirm(self.i);self.assertEqual(set(picks),old_picks(self.s,v.draw_id,101))
 async def test_manual_only_blocks_prepared_quick_bypass(self):
  self.c['lottery']['pick_mode']='manual';self.s.save(1,self.c);v=self.view()
  self.assertNotIn('Quick Pick',[c.label for c in v.children if isinstance(c,discord.ui.Button)])
  with self.assertRaises(ValueError):self.e.lottery_enter(1,101,v.draw_id,1,'','points','x',prepared=[(1,2,3)])
  self.assertEqual(self.s.balance(1,101),100)
 async def test_duplicate_reviewed_quick_pick_fails_without_second_charge(self):
  v=self.view();await v.quick(self.i);p=v.picks[0];self.e.lottery_enter(1,101,v.draw_id,1,','.join(map(str,p)),'points','other');await v.preview(self.i)
  with self.assertRaises(ValueError):await v.confirm(self.i)
  self.assertEqual(self.s.balance(1,101),99)
 async def test_owner_settings_changes_keep_reviewed_bundle_price(self):
  self.c['lottery']['bundles']={'3':2};self.s.save(1,self.c);v=self.view();v.count=3;await v.quick(self.i)
  self.c['lottery']['cost']=30;self.s.save(1,self.c);await v.preview(self.i);await v.confirm(self.i);self.assertEqual(self.s.balance(1,101),98)
 async def test_other_player_cannot_use_menu_or_modal(self):
  v=self.view();self.i.user.id=102;self.assertFalse(await v.interaction_check(self.i));m=NumberModal(v);await m.on_submit(self.i);self.assertFalse(v.picks)
 async def test_full_number_range_and_ui_component_limits(self):
  v=self.view();v.limit=100;v.count_page=3;v.build()
  self.assertEqual(len(v.children[0].options),25);self.assertLessEqual(len(v.to_components()),5)
  v.count=100;await v.quick(self.i);self.assertEqual(len(v.picks),100);self.assertEqual(len(set(v.picks)),100);self.assertLessEqual(len(v.text()),2000)
  v.review=True;v.build();self.assertEqual(len(v.files()),1)
 async def test_number_validation(self):
  for values in [('1,2','3','4'),('0','1','2'),('1','1','2'),('a','2','3')]:
   with self.assertRaises(ValueError):validate_numbers(values,self.c['lottery'],set())
  self.assertEqual(validate_numbers(['3','2','1'],self.c['lottery'],set()),(1,2,3))
 async def test_command_schema_and_disabled_game_menu(self):
  with tempfile.TemporaryDirectory()as t:
   b=attach_commands(GamesBot(Path(t)/'s.sqlite3'));names=[c.qualified_name for c in b.tree.walk_commands()]
   self.assertIn('ticketsbalance',names);self.assertNotIn('balance',names)
   self.assertEqual(len(b.tree.get_command('lottery').get_command('enter').parameters),0)
   self.assertNotIn('server_id',[p.name for p in b.tree.get_command('gamesadmin').get_command('setup').parameters])
   for command in b.tree.get_commands():command.to_dict(b.tree)
   await b.close()
  self.c['games']['dice']['enabled']=False
  self.assertNotIn('dice',available_games(self.c));self.assertIn('lottery',available_games(self.c))
  menu=Lobby(101,self.c);self.assertNotIn('dice',[o.value for item in menu.children if isinstance(item,discord.ui.Select)for o in item.options])
