"""Owner-only guided configuration. Drafts stay in memory until reviewed and saved."""
from copy import deepcopy
import discord
import io
from configuration import defaults, validate, GAMES, TIERS

LABELS={
 'general':'Community settings','games':'Games','prizes':'Prize tiers','lottery':'Rust World Lottery',
 'daily':'Daily tickets','bingo':'Bingo','giveaway':'Ticket giveaways','products':'Tip4Serv products',
 'currency':'Ticket currency name','timezone':'Time zone','enabled':'Enabled','delivery_enabled':'Reward delivery enabled',
 'allow_unlinked':'Allow players without a KAOS link','staff_role':'Staff role','games_channel':'Games channel',
 'daily_channel':'Daily claim channel','results_channel':'Results channel','admin_channel':'Admin channel',
 'purchase_store_id':'Tip4Serv store ID','server_id':'Default KAOS server ID','choice_timing':'When to choose kits or points',
 'reward_mode':'Available reward types','transfers_enabled':'Allow ticket transfers','amount':'Amount',
 'reset':'Daily reset rule','method':'Daily claim method','costs':'Entry ticket costs','odds':'Prize chances',
 'loss_return':'Tickets returned after a loss','draw_return':'Tickets returned after a tie','points':'KAOS points',
 'kits':'Kit and item prize alternatives','weight':'Relative selection weight','rewards':'Rewards in this bundle',
 'kind':'Reward type','name':'Exact kit name or item identifier','quantity':'Quantity','min':'Lowest lottery number',
 'max':'Highest lottery number','cost':'Ticket cost','max_entries':'Combinations per player (0 = unlimited)',
 'payout':'Lottery payout rule','pick_mode':'Number selection method','bundles':'Discount combination bundles',
 'reward_tiers':'Prize tier for each match count','zero_return':'Tickets returned for zero matches',
 'schedule':'Draw schedule','mode':'Method','minutes':'Minutes','time':'Local draw time (HH:MM)',
 'weekdays':'Draw days','cutoff_minutes':'Close entries minutes before draw','reminder_minutes':'Reminder minutes (0 = off)',
 'announce_winners':'Announce winning players','round':'Percentage rounding','numbers':'Bingo number pool',
 'size':'Bingo card width','participation_tier':'Non-winning prize tier','winner_tier':'Winning prize tier',
 'winners':'Number of winners','1':'One matching number','2':'Two matching numbers','3':'Three matching numbers',
 'base':'Base','elite':'Elite','premium':'Premium','rps':'Rock Paper Scissors'}
WORDS={'entry':'Before entry','after':'After winning','kits':'Kits / items','points':'KAOS points','both':'Both options',
 'highest':'Best combination per player','each':'Every combination','manual':'Owner / manual','quick':'Quick Pick',
 'interval':'Every set number of minutes','daily':'Daily','weekly':'Weekly (one day)','weekdays':'Selected weekdays',
 'full':'Full ticket refund','none':'No ticket return','fixed':'Fixed ticket amount','percent':'Percentage of tickets spent',
 'up':'Round up','down':'Round down','midnight':'At midnight','24h':'24 hours after each claim',
 'button':'Button only','command':'Slash command only','kit':'Kit','item':'Item'}
DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
EXCLUDED={'enabled','delivery_enabled','games_channel','daily_channel','results_channel','admin_channel','staff_role'}

def label(key):return LABELS.get(str(key),str(key).replace('_',' ').title())
def pretty(value):
 if type(value)is bool:return 'On' if value else 'Off'
 if isinstance(value,dict):
  if 'kind'in value and 'name'in value:return f"{value['quantity']} × {value['name']} ({value['kind']})"
  if 'weight'in value:return f"Weight {value['weight']}; {len(value['rewards'])} reward(s)"
  return f'{len(value)} settings / entries'
 if isinstance(value,list):return f'{len(value)} entries'
 return WORDS.get(str(value),str(value))
def get(c,path):
 for key in path:c=c[key]
 return c

def options(path):
 k=path[-1]
 if k=='reward_mode':return ['kits','points','both']
 if k=='choice_timing':return ['entry','after']
 if k=='reset':return ['midnight','24h']
 if k=='method':return ['button','command','both']
 if k=='payout':return ['highest','each']
 if k=='pick_mode':return ['both','manual','quick']
 if k=='round':return ['down','up']
 if k=='kind':return ['kit','item']
 if k in ('participation_tier','winner_tier') or 'reward_tiers'in path:return list(TIERS)
 if k=='mode':return ['manual','interval','daily','weekly','weekdays'] if 'schedule'in path else ['full','none','fixed','percent']
 return None

class Draft:
 def __init__(self,config):self.original=deepcopy(config);self.value=deepcopy(config)
 def set(self,path,value):get(self.value,path[:-1])[path[-1]]=value
 def changes(self):
  out=[];missing=object()
  def walk(a,b,path):
   if a==b:return
   if isinstance(a,dict)or isinstance(b,dict):
    aa=a if isinstance(a,dict)else {};bb=b if isinstance(b,dict)else {}
    for k in dict.fromkeys(list(aa)+list(bb)):walk(aa.get(k,missing),bb.get(k,missing),path+[k])
   elif isinstance(a,list)or isinstance(b,list):
    aa=a if isinstance(a,list)else [];bb=b if isinstance(b,list)else []
    for n in range(max(len(aa),len(bb))):walk(aa[n]if n<len(aa)else missing,bb[n]if n<len(bb)else missing,path+[n])
   else:out.append(' → '.join(label(x)if not isinstance(x,int)else f'Entry {x+1}' for x in path)+': '+('Not set'if a is missing else pretty(a))+' → '+('Removed'if b is missing else pretty(b)))
  walk(self.original,self.value,[]);return out
 def validated(self,current):
  if current!=self.original:raise ValueError('Settings changed in another command. Close this panel and reopen it before saving.')
  for tier in self.value['prizes'].values():
   for alternative in tier['kits']:
    if any(r['name']=='CHANGE_ME'for r in alternative['rewards']):raise ValueError('Set the exact kit name or item identifier for every new reward before saving.')
  validate(self.value);return deepcopy(self.value)

def section_path(section):
 if section=='general':return ()
 if section.startswith('game:')and section[5:]in GAMES:return ('games',section[5:])
 if section.startswith('prize:')and section[6:]in TIERS:return ('prizes',section[6:])
 if section in ('daily','lottery','bingo','giveaway','products'):return (section,)
 raise ValueError('Choose a section from the command suggestions.')

class SettingsView(discord.ui.View):
 def __init__(self,i,guard,reply,path=(),draft=None,page=0,review=False):
  super().__init__(timeout=900);self.uid=i.user.id;self.guild=i.guild_id;self.guard=guard;self.reply=reply
  self.draft=draft or Draft(i.client.store.cfg(i.guild_id));self.path=tuple(path);self.page=page;self.review=review
  if review:
   self.button('Confirm Save',self.save,discord.ButtonStyle.success);self.button('Back to editing',self.back_review)
  else:self.build()
  self.button('Cancel',self.cancel,discord.ButtonStyle.danger)
 async def interaction_check(self,i):
  if i.user.id!=self.uid or i.guild_id!=self.guild:
   await self.reply(i,'This settings panel belongs to another owner.');return False
  try:self.guard(i,owner=True)
  except ValueError as e:await self.reply(i,str(e));return False
  return True
 async def on_error(self,i,e,item):
  import logging
  if not isinstance(e,(ValueError,KeyError,TypeError)):logging.getLogger('games').exception('Guided settings failed',exc_info=e)
  await self.reply(i,str(e) if isinstance(e,(ValueError,KeyError,TypeError)) else 'Could not update settings. No draft changes were saved.')
 def button(self,text,callback,style=discord.ButtonStyle.secondary):
  b=discord.ui.Button(label=text,style=style);b.callback=callback;self.add_item(b)
 def build(self):
  value=get(self.draft.value,self.path)
  if not self.path:keys=[k for k in value if k not in EXCLUDED]+list(EXCLUDED&set(value))
  else:keys=list(value)if isinstance(value,dict)else list(range(len(value)))
  chunk=keys[self.page*20:self.page*20+20]
  if chunk:
   entries=[]
   for k in chunk:
    title=f'Alternative {k+1}'if isinstance(k,int)and self.path[-1:] == ('kits',)else f'Reward {k+1}'if isinstance(k,int)else label(k)
    if self.path[-1:] == ('products',):title='Product '+str(k)
    if self.path[-1:] == ('bundles',):title=str(k)+' combinations'
    entries.append(discord.SelectOption(label=title[:100],value=str(k),description=pretty(value[k])[:100]))
   select=discord.ui.Select(placeholder='Choose a setting to view or change',options=entries);select.callback=self.pick;self.add_item(select)
  if self.path:self.button('Back',self.back)
  if self.page:self.button('Previous page',self.previous)
  if (self.page+1)*20<len(keys):self.button('Next page',self.next)
  if self.path and self.path[-1]in ('products','bundles','kits','rewards'):self.button('Add entry',self.add)
  if self.path and (self.path[-1]in ('products','bundles') or isinstance(value,list))and len(value):self.button('Remove entry',self.remove)
  if self.draft.changes():self.button('Review changes',self.review_changes,discord.ButtonStyle.primary)
 def content(self):
  title=' → '.join(label(k)if not isinstance(k,int)else f'Entry {k+1}'for k in self.path)or 'Community settings'
  if self.review:
   changes=self.draft.changes();return '**Review settings before saving**\n'+ '\n'.join(changes)[-1600:]+f'\n{len(changes)} changed settings. Read the attached full review. Existing paid games and draws keep their original rules.'
  text=f'**{title}**\nChoose a setting below. Changes remain a draft until **Review changes → Confirm Save**.\n'
  if self.path[-1:] == ('schedule',):text+='Times use your community time zone. For weekly draws, select exactly one day.\n'
  if self.path[-1:] == ('odds',):text+='Each level has Base, Elite and Premium chances totaling 100%. Higher entry levels must have equal or better odds.\n'
  if self.path[-1:] == ('kits',):text+='Alternatives are chosen by relative weight. Each alternative can contain multiple kit/item rewards.\n'
  if not get(self.draft.value,self.path):text+='No entries yet. Use Add entry.\n'
  if not self.path:text+='Channel and role settings use Discord selectors. Enabling delivery checks your KAOS connection.\n'
  return text+f'Unsaved changes: {len(self.draft.changes())}.'
 async def show(self,i,path=None,page=0,review=False):
  v=SettingsView(i,self.guard,self.reply,self.path if path is None else path,self.draft,page,review)
  files=[discord.File(io.BytesIO(('SETTINGS REVIEW — read only\n\n'+'\n'.join(self.draft.changes())).encode()),filename='settings-review.txt')]if review else []
  await i.response.edit_message(content=v.content(),view=v,attachments=files);self.stop()
 async def back(self,i):await self.show(i,self.path[:-1])
 async def previous(self,i):await self.show(i,page=self.page-1)
 async def next(self,i):await self.show(i,page=self.page+1)
 async def back_review(self,i):await self.show(i)
 async def cancel(self,i):await i.response.edit_message(content='Settings draft cancelled. Nothing saved.',view=None);self.stop()
 async def review_changes(self,i):
  self.draft.validated(i.client.store.cfg(i.guild_id));await self.show(i,review=True)
 async def save(self,i):
  c=self.draft.validated(i.client.store.cfg(i.guild_id))
  if c['delivery_enabled']and not self.draft.original['delivery_enabled']:
   await i.response.defer();await i.client.kaos.check(i.guild_id)
  c=self.draft.validated(i.client.store.cfg(i.guild_id));i.client.store.save(i.guild_id,c,i.user.id)
  text='Settings saved. Existing paid games and draws retain their original rules. Repost Games/Daily panels if their displayed text changed.'
  if i.response.is_done():await i.edit_original_response(content=text,view=None)
  else:await i.response.edit_message(content=text,view=None)
  self.stop()
 async def pick(self,i):
  value=get(self.draft.value,self.path);raw=i.data['values'][0];key=int(raw)if isinstance(value,list)else raw;path=self.path+(key,);v=get(self.draft.value,path)
  if isinstance(v,dict)or isinstance(v,list)and key not in TIERS and key!='weekdays':await self.show(i,path);return
  if key=='weekdays':
   s=discord.ui.Select(placeholder='Select draw days',min_values=1,max_values=7,options=[discord.SelectOption(label=d,value=str(n),default=n in v)for n,d in enumerate(DAYS)])
   await self.choice(i,path,s,lambda vs:[int(x)for x in vs]);return
  if type(v)is bool or options(path):
   opts=[True,False]if type(v)is bool else options(path)
   s=discord.ui.Select(placeholder=label(key)[:100],options=[discord.SelectOption(label=pretty(x),value=str(n),default=x==v)for n,x in enumerate(opts)])
   await self.choice(i,path,s,lambda vs:opts[int(vs[0])]);return
  if key.endswith('_channel')or key=='staff_role':
   s=discord.ui.RoleSelect(placeholder='Choose a staff role',min_values=0,max_values=1)if key=='staff_role'else discord.ui.ChannelSelect(placeholder=label(key),channel_types=[discord.ChannelType.text],min_values=0,max_values=1)
   await self.choice(i,path,s,lambda vs:int(vs[0])if vs else 0);return
  await i.response.send_modal(ValueModal(self,path))
 async def choice(self,i,path,select,convert):
  view=SettingsView(i,self.guard,self.reply,self.path,self.draft);view.clear_items();view.add_item(select)
  async def apply(j):
   self.draft.set(path,convert(j.data.get('values',[])));await view.show(j)
  select.callback=apply;view.button('Back without changing',view.back_review);view.button('Cancel',view.cancel,discord.ButtonStyle.danger)
  await i.response.edit_message(content='**'+label(path[-1])+'**\nChoose an option. This updates your draft only.',view=view);self.stop()
 async def add(self,i):
  v=get(self.draft.value,self.path);kind=self.path[-1]
  if kind in ('products','bundles'):await i.response.send_modal(EntryModal(self));return
  if len(v)>=(50 if kind=='kits'else 10):raise ValueError('Maximum entries reached. Remove an entry first.')
  v.append({'weight':1,'rewards':[{'kind':'kit','name':'CHANGE_ME','quantity':1}]}if kind=='kits'else {'kind':'kit','name':'CHANGE_ME','quantity':1})
  await self.show(i,self.path+(len(v)-1,))
 async def remove(self,i):
  v=get(self.draft.value,self.path);keys=list(v)if isinstance(v,dict)else list(range(len(v)))
  # Page removal menus so every entry remains reachable.
  keys=keys[self.page*20:self.page*20+20]
  s=discord.ui.Select(placeholder='Select entry to remove from draft',options=[discord.SelectOption(label=(str(k)if isinstance(v,dict)else f'Entry {k+1}')[:100],value=str(n))for n,k in enumerate(keys)])
  view=SettingsView(i,self.guard,self.reply,self.path,self.draft);view.clear_items();view.add_item(s)
  async def remove_one(j):
   key=keys[int(j.data['values'][0])]
   if isinstance(v,list):v.pop(key)
   else:del v[key]
   await view.show(j)
  s.callback=remove_one;view.button('Back',view.back_review)
  await i.response.edit_message(content='Choose an entry to remove. Removal is saved only after review and confirmation.',view=view);self.stop()

class ValueModal(discord.ui.Modal):
 def __init__(self,view,path):
  field_label='Tickets per product unit'if path[:-1]==('products',)else 'Total ticket price for this bundle'if path[:-1]==('lottery','bundles')else label(path[-1])
  super().__init__(title=field_label[:45]);self.view=view;self.path=path;v=get(view.draft.value,path)
  if isinstance(v,list):
   self.fields=[discord.ui.TextInput(label=t.title()+' prize chance (%)',default=str(v[n]),max_length=3)for n,t in enumerate(TIERS)]
  else:self.fields=[discord.ui.TextInput(label=field_label[:45],default=str(v),max_length=100 if isinstance(v,str)else 20)]
  for f in self.fields:self.add_item(f)
 async def on_submit(self,i):
  if not await self.view.interaction_check(i):return
  try:
   old=get(self.view.draft.value,self.path);values=[str(f).strip()for f in self.fields]
   value=[int(x)for x in values]if isinstance(old,list)else int(values[0])if type(old)is int else values[0]
   if isinstance(value,list)and (sum(value)!=100 or any(x<0 for x in value)):raise ValueError('The three chances must be nonnegative and total 100%.')
   self.view.draft.set(self.path,value);await self.view.show(i)
  except ValueError as e:await self.view.reply(i,'Invalid setting: '+str(e)+'. Reopen the field and try again.')

class EntryModal(discord.ui.Modal):
 def __init__(self,view):
  super().__init__(title='Add '+('product'if view.path[-1]=='products'else 'combination bundle'));self.view=view
  self.code=discord.ui.TextInput(label='Tip4Serv product code'if view.path[-1]=='products'else 'Number of combinations (1–100)',max_length=50)
  self.amount=discord.ui.TextInput(label='Tickets per product unit'if view.path[-1]=='products'else 'Total ticket price for this bundle',max_length=9)
  self.add_item(self.code);self.add_item(self.amount)
 async def on_submit(self,i):
  if not await self.view.interaction_check(i):return
  try:
   import re
   key=str(self.code).strip();amount=int(str(self.amount));is_product=self.view.path[-1]=='products'
   if is_product and not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',key):raise ValueError('Product code: letters, digits, underscores or hyphens only.')
   if not is_product:
    if not key.isdigit()or not 1<=int(key)<=100:raise ValueError('Combination count must be 1–100.')
    key=str(int(key))
   if not 1<=amount<=(1000000 if is_product else 100000000):raise ValueError('Ticket amount is outside the allowed range.')
   entries=get(self.view.draft.value,self.view.path)
   if key in entries:raise ValueError('That entry already exists. Select it to edit its amount.')
   entries[key]=amount;await self.view.show(i)
  except ValueError as e:await self.view.reply(i,str(e))

async def open_settings(i,guard,reply,section='general'):
 guard(i,owner=True);view=SettingsView(i,guard,reply,section_path(section));await reply(i,view.content(),view=view)
