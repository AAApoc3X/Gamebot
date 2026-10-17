from copy import deepcopy
from types import SimpleNamespace
import unittest,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,Mock
import discord
from configuration import defaults
from settings_ui import Draft,SettingsView,ValueModal,EntryModal,section_path
from bot import APIKeyModal,GamesBot,attach_commands

class DraftTests(unittest.TestCase):
 def test_validation_and_conflict(self):
  c=defaults();d=Draft(c);d.set(('lottery','min'),50)
  with self.assertRaises(ValueError):d.validated(c)
  d.set(('lottery','max'),100);self.assertEqual(d.validated(c)['lottery']['min'],50);self.assertEqual(c,defaults())
  changed=deepcopy(c);changed['currency']='Tokens'
  with self.assertRaisesRegex(ValueError,'another command'):d.validated(changed)
 def test_sections(self):
  self.assertEqual(section_path('lottery'),('lottery',));self.assertEqual(section_path('game:rps'),('games','rps'))
  with self.assertRaises(ValueError):section_path('missing')
 def test_bundle_and_product_settings(self):
  c=defaults();d=Draft(c);d.set(('products',),{'104':10});d.set(('lottery','bundles'),{'3':2})
  d.set(('prizes','base','kits'),[{'weight':5,'rewards':[{'kind':'kit','name':'starter','quantity':1},{'kind':'item','name':'wood','quantity':5}]}])
  self.assertEqual(len(d.validated(c)['prizes']['base']['kits'][0]['rewards']),2)

class GuidedTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.c=defaults();self.store=SimpleNamespace(cfg=lambda guild:deepcopy(self.c),save=Mock())
  self.i=SimpleNamespace(user=SimpleNamespace(id=1),guild_id=10,client=SimpleNamespace(store=self.store,kaos=SimpleNamespace(check=AsyncMock())),response=SimpleNamespace(edit_message=AsyncMock(),send_modal=AsyncMock(),is_done=lambda:False,defer=AsyncMock()),data={})
  self.guard=Mock();self.reply=AsyncMock()
 def view(self,path=()):return SettingsView(self.i,self.guard,self.reply,path)
 async def test_every_container_renders(self):
  def walk(v,path=()):
   if isinstance(v,(dict,list)):
    yield path
    for k,x in (v.items()if isinstance(v,dict)else enumerate(v)):yield from walk(x,path+(k,))
  for path in walk(self.c):
   if path and (path[-1]=='weekdays'or path[-1]in ('base','elite','premium')and 'odds'in path):continue
   v=self.view(path);self.assertLessEqual(len(v.children),25);self.assertNotIn('JSON',v.content());self.assertLess(len(v.content()),2000)
   for child in v.children:
    if isinstance(child,discord.ui.Select):self.assertLessEqual(len(child.options),25)
 async def test_native_controls(self):
  for path,key in [(('lottery',),'payout'),(('lottery','schedule'),'weekdays'),((),'games_channel'),((),'staff_role'),(('daily',),'method')]:
   v=self.view(path);self.i.data={'values':[key]};await v.pick(self.i)
   control=self.i.response.edit_message.call_args.kwargs['view'].children[0]
   self.assertIsInstance(control,(discord.ui.Select,discord.ui.ChannelSelect,discord.ui.RoleSelect))
 async def test_odds_modal(self):
  v=self.view(('games','rps','odds'));m=ValueModal(v,('games','rps','odds','base'));self.assertEqual(len(m.children),3)
  for f,x in zip(m.fields,['10','10','10']):f._value=x
  await m.on_submit(self.i);self.reply.assert_awaited();self.assertEqual(v.draft.value,self.c)
  for f,x in zip(m.fields,['70','20','10']):f._value=x
  await m.on_submit(self.i);self.assertEqual(v.draft.value['games']['rps']['odds']['base'],[70,20,10])
 async def test_owner_checked_on_buttons_and_modal(self):
  v=self.view();self.i.user.id=2;self.assertFalse(await v.interaction_check(self.i));self.store.save.assert_not_called()
  self.i.user.id=1;self.guard.side_effect=ValueError('Only owner');await ValueModal(v,('currency',)).on_submit(self.i);self.store.save.assert_not_called()
 async def test_review_and_save(self):
  v=self.view();v.draft.set(('currency',),'Tokens');await v.review_changes(self.i)
  review=self.i.response.edit_message.call_args.kwargs['view'];self.assertIn('Confirm Save',[x.label for x in review.children]);self.store.save.assert_not_called()
  await review.save(self.i);self.store.save.assert_called_once();self.assertEqual(self.store.save.call_args.args[1]['currency'],'Tokens')
  self.c['daily']['amount']=20
  with self.assertRaises(ValueError):await review.save(self.i)
 async def test_command_schema_and_api_modal(self):
  with tempfile.TemporaryDirectory()as t:
   bot=attach_commands(GamesBot(Path(t)/'games.sqlite3'));names=[c.qualified_name for c in bot.tree.walk_commands()]
   self.assertNotIn('gamesadmin import_config',names);self.assertIn('gamesadmin configure',names)
   for c in bot.tree.get_commands():c.to_dict(bot.tree)
   await bot.close()
  self.assertEqual(APIKeyModal().key.max_length,4000)
 async def test_product_form(self):
  v=self.view(('products',));m=EntryModal(v);m.code._value='104';m.amount._value='10';await m.on_submit(self.i)
  self.assertEqual(v.draft.value['products'],{'104':10});self.store.save.assert_not_called()
  await m.on_submit(self.i);self.assertIn('already exists',self.reply.call_args.args[1])
 async def test_api_check_blocks_delivery_enable(self):
  self.c['games_channel']=123;self.c['reward_mode']='points';v=self.view();v.draft.set(('delivery_enabled',),True)
  self.i.client.kaos.check.side_effect=ValueError('Invalid API key')
  with self.assertRaises(ValueError):await v.save(self.i)
  self.store.save.assert_not_called()
 async def test_cancel(self):
  v=self.view();v.draft.set(('currency',),'Tokens');await v.cancel(self.i);self.store.save.assert_not_called()
 async def test_collection_pagination_and_review_details(self):
  self.c['prizes']['base']['kits']=[{'weight':1,'rewards':[{'kind':'kit','name':f'kit{n}','quantity':1}]}for n in range(50)]
  v=self.view(('prizes','base','kits'));self.assertEqual(len(v.children[0].options),20)
  self.assertIn('Next page',[x.label for x in v.children if isinstance(x,discord.ui.Button)])
  v.draft.value['prizes']['base']['kits'].append({'weight':2,'rewards':[{'kind':'item','name':'wood','quantity':100}]})
  changes='\n'.join(v.draft.changes());self.assertIn('wood',changes);self.assertIn('100',changes)
 async def test_placeholder_reward_cannot_save(self):
  v=self.view(('prizes','base','kits'));await v.add(self.i)
  with self.assertRaisesRegex(ValueError,'exact kit name'):v.draft.validated(self.c)
 async def test_invalid_numeric_input_does_not_change_draft(self):
  v=self.view(('lottery',));m=ValueModal(v,('lottery','cost'));m.fields[0]._value='not a number';await m.on_submit(self.i)
  self.assertEqual(v.draft.value,self.c);self.store.save.assert_not_called()
