"""Private lottery purchase wizard. No tickets are spent until confirmation."""
import io,itertools,json,math,uuid
from copy import deepcopy
import discord

def old_picks(store,draw,uid):return {tuple(json.loads(r[0]))for r in store.db.execute('SELECT numbers FROM entries WHERE draw=? AND uid=?',(draw,uid))}
def quick_picks(engine,lo,count,used):
 total=math.comb(lo['max']-lo['min']+1,3)
 if count>total-len(used):raise ValueError('Not enough unused combinations remain.')
 picks=[]
 for _ in range(count*50):
  nums=tuple(sorted(engine.rng.sample(range(lo['min'],lo['max']+1),3)))
  if nums not in used and nums not in picks:picks.append(nums)
  if len(picks)==count:return picks
 for nums in itertools.combinations(range(lo['min'],lo['max']+1),3):
  if nums not in used and nums not in picks:picks.append(nums)
  if len(picks)==count:return picks
 return picks

def validate_numbers(values,lo,used):
 try:nums=tuple(sorted(int(str(x).strip())for x in values))
 except ValueError:raise ValueError('Enter one whole number in each box.')
 if len(nums)!=3 or len(set(nums))!=3:raise ValueError('Choose three different numbers.')
 if not all(lo['min']<=n<=lo['max']for n in nums):raise ValueError(f"Each number must be between {lo['min']} and {lo['max']}.")
 if nums in used:raise ValueError('You already selected that combination. Choose different numbers.')
 return nums

class LotteryEntry(discord.ui.View):
 def __init__(self,i,draw,guard,reply,ensure_link):
  super().__init__(timeout=900);self.uid=i.user.id;self.guild=i.guild_id;self.draw_id=draw['id'];self.c=deepcopy(draw['state']['config']);self.lo=self.c['lottery'];self.guard=guard;self.reply=reply;self.ensure_link=ensure_link;self.client=i.client
  self.epoch=0;self.count=1;self.count_page=0;self.picks=[];self.method=None;self.review=False;self.busy=False;self.completed=False;self.reference='lotteryentry:'+uuid.uuid4().hex
  self.kind=self.c['reward_mode']if self.c['reward_mode']!='both'else None
  self.servers=self.c.get('_destination_options',[{'slot':self.c['server_id'],'label':f"Game server {self.c['server_id']}"}]);self.before=self.c.get('_destination_timing','before')=='before'
  if not self.servers:raise ValueError('No available reward servers for this draw. Ask the owner to review the server list.')
  pref=i.client.store.destinations.preference(self.guild,self.uid);self.slot=pref if pref in [x['slot']for x in self.servers]else self.servers[0]['slot']if len(self.servers)==1 else None
  self.limit=min(100,(self.lo['max_entries']or 100)-len(old_picks(i.client.store,self.draw_id,self.uid)),math.comb(self.lo['max']-self.lo['min']+1,3)-len(old_picks(i.client.store,self.draw_id,self.uid)))
  if self.limit<1:raise ValueError('You have reached the combination limit for this draw.')
  self.build()
 async def interaction_check(self,i):
  if i.user.id!=self.uid or i.guild_id!=self.guild:await self.reply(i,'This lottery menu belongs to another player.');return False
  if self.busy or self.completed:await self.reply(i,'This entry is processing or complete. Check /lottery entries.');return False
  try:self.guard(i,player=True)
  except ValueError as e:await self.reply(i,str(e));return False
  return True
 async def on_error(self,i,e,item):
  import logging
  if not isinstance(e,ValueError):logging.getLogger('games').exception('Lottery menu failed',exc_info=e)
  await self.reply(i,str(e)if isinstance(e,ValueError)else 'Entry could not finish. Check /lottery entries and /ticketsbalance before trying again.')
 def button(self,label,callback,style=discord.ButtonStyle.secondary,row=None):
  b=discord.ui.Button(label=label,style=style,row=row);b.callback=callback;self.add_item(b)
 def build(self):
  self.clear_items()
  if self.review:
   self.button('Confirm Entry',self.confirm,discord.ButtonStyle.success);self.button('Back to choices',self.back)
  else:
   start=self.count_page*25+1
   s=discord.ui.Select(placeholder=f'Combinations to buy — currently {self.count}',options=[discord.SelectOption(label=f'{n} combination'+('s'if n!=1 else '')+f" — {self.lo['bundles'].get(str(n),n*self.lo['cost'])} tickets",value=str(n),default=n==self.count)for n in range(start,min(start+25,self.limit+1))],row=0)
   async def number(i):self.count=int(i.data['values'][0]);self.epoch+=1;self.picks=[];self.method=None;await self.refresh(i)
   s.callback=number;self.add_item(s)
   if self.before:
    if not self.servers:raise ValueError('No available reward servers. Ask the owner to add a game server.')
    s=discord.ui.Select(placeholder='Reward server'+(f' — S{self.slot}'if self.slot else ' — choose one'),options=[discord.SelectOption(label=f"S{x['slot']} — {x['label']}"[:100],value=str(x['slot']),default=x['slot']==self.slot)for x in self.servers],row=1)
    async def server(i):self.slot=int(i.data['values'][0]);await self.refresh(i)
    s.callback=server;self.add_item(s)
   if self.c['reward_mode']=='both'and self.c['choice_timing']=='entry':
    s=discord.ui.Select(placeholder='Choose kits/items or KAOS points',options=[discord.SelectOption(label=l,value=k,default=self.kind==k)for l,k in [('Kits or items','kits'),('KAOS points','points')]],row=2)
    async def kind(i):self.kind=i.data['values'][0];await self.refresh(i)
    s.callback=kind;self.add_item(s)
   if self.lo['pick_mode']in ('both','manual'):self.button('Pick My Numbers'+(f' — combination {len(self.picks)+1}'if self.method=='manual'and len(self.picks)<self.count else ''),self.manual,row=3)
   if self.lo['pick_mode']in ('both','quick'):self.button('Quick Pick',self.quick,row=3)
   self.button('Review Entry',self.preview,discord.ButtonStyle.primary,row=3)
   if self.count_page:self.button('Fewer combinations',self.previous,row=4)
   if (self.count_page+1)*25<self.limit:self.button('More combinations',self.next,row=4)
  self.button('Cancel',self.cancel,discord.ButtonStyle.danger,row=None if self.review else 4)
 def text(self):
  lines=['**Rust World Lottery — '+('Review purchase'if self.review else 'Choose your entry')+'**',f"Draw: {self.draw_id}",f"Choose 3 different numbers from {self.lo['min']} to {self.lo['max']} per combination.",f"{self.count} combination(s) · Total cost: {self.lo['bundles'].get(str(self.count),self.count*self.lo['cost'])} {self.client.store.cfg(self.guild)['currency']}"]
  lines+=['Your numbers:']+[f"{n+1}. {' · '.join(map(str,p))}"for n,p in enumerate(self.picks[:10])]
  if not self.picks:lines+=['Choose Pick My Numbers or Quick Pick. Nothing has been purchased.']
  if len(self.picks)>10:lines+=['All combinations are listed in the attached read-only review.']
  lines+=[f"Numbers ready: {len(self.picks)}/{self.count}", 'Reward server: '+(f"S{self.slot} — "+next(x['label']for x in self.servers if x['slot']==self.slot)if self.before and self.slot else 'Choose a server before confirming'if self.before else 'Choose after winning'), 'Reward type: '+('Choose after winning'if self.c['reward_mode']=='both'and self.c['choice_timing']=='after'else 'Kits / items'if self.kind=='kits'else 'KAOS points'if self.kind=='points'else 'Choose a reward type'), '1 / 2 / 3 matches: '+' / '.join(self.lo['reward_tiers'][str(n)].title()for n in [1,2,3]), 'Payout: '+('Best combination per player'if self.lo['payout']=='highest'else 'Each combination')]
  rule=self.lo['zero_return'];lines+=['Zero matches: '+({'full':'Full ticket refund','none':'No ticket return','fixed':f"{rule['amount']} tickets returned",'percent':f"{rule['amount']}% ticket return ({rule['round']} rounding)"}[rule['mode']])]
  return '\n'.join(lines)[:1950]
 def files(self):
  if not self.review and len(self.picks)<=10:return []
  rows=[self.text(),'\nALL SELECTED COMBINATIONS']+[f"{n+1}. {' · '.join(map(str,p))}"for n,p in enumerate(self.picks)]
  rows+=['\nPRIZES BY TIER']
  for tier,p in self.c['prizes'].items():
   rows+=[tier.title()+f": {p['points']['amount']} KAOS points, or one weighted kit/item alternative:"]
   for n,opt in enumerate(p['kits']):rows+=[f"  Alternative {n+1}, weight {opt['weight']}: "+'; '.join(f"{r['quantity']} × {r['name']} ({r['kind']})"for r in opt['rewards'])]
  return [discord.File(io.BytesIO('\n'.join(rows).encode()),filename='lottery-entry-review.txt')]
 async def refresh(self,i):
  self.build();await i.response.edit_message(content=self.text(),view=self,attachments=self.files())
 async def previous(self,i):self.count_page-=1;await self.refresh(i)
 async def next(self,i):self.count_page+=1;await self.refresh(i)
 async def manual(self,i):
  if self.method!='manual'or len(self.picks)==self.count:self.picks=[];self.epoch+=1
  self.method='manual';await i.response.send_modal(NumberModal(self))
 async def quick(self,i):
  self.epoch+=1;self.method='quick';self.picks=quick_picks(self.client.engine,self.lo,self.count,old_picks(self.client.store,self.draw_id,self.uid));await self.refresh(i)
 def ready(self):
  if len(self.picks)!=self.count:raise ValueError('Fill every combination before reviewing the entry.')
  if self.before and self.slot is None:raise ValueError('Choose the reward server.')
  if self.c['reward_mode']=='both'and self.c['choice_timing']=='entry'and self.kind is None:raise ValueError('Choose kits/items or KAOS points.')
 async def preview(self,i):self.ready();self.review=True;await self.refresh(i)
 async def back(self,i):self.review=False;await self.refresh(i)
 async def cancel(self,i):self.stop();await i.response.edit_message(content='Lottery entry cancelled. No tickets spent.',view=None,attachments=[])
 async def confirm(self,i):
  if not self.review:raise ValueError('Review the entry before confirming.')
  self.ready();self.busy=True
  try:
   await self.ensure_link(i,required=not self.client.store.cfg(self.guild)['allow_unlinked']or not self.c['allow_unlinked'])
   picks=self.client.engine.lottery_enter(self.guild,self.uid,self.draw_id,self.count,';'.join(','.join(map(str,x))for x in self.picks)if self.method=='manual'else '',self.kind or 'points',self.reference,[r.id for r in getattr(i.user,'roles',[])],server_id=self.slot,prepared=self.picks if self.method=='quick'else None)
   self.completed=True;self.stop();text=f'Lottery entry confirmed: {len(picks)or self.count} combinations. Tickets charged once. See /lottery entries or /ticketsbalance.'
   if i.response.is_done():await i.edit_original_response(content=text,view=None,attachments=self.files())
   else:await i.response.edit_message(content=text,view=None,attachments=self.files())
  finally:self.busy=False

class NumberModal(discord.ui.Modal):
 def __init__(self,view):
  super().__init__(title=f'Combination {len(view.picks)+1} of {view.count}');self.view=view;self.epoch=view.epoch;self.index=len(view.picks)
  self.fields=[discord.ui.TextInput(label=f"Number {n} ({view.lo['min']}–{view.lo['max']})",max_length=3)for n in [1,2,3]]
  for field in self.fields:self.add_item(field)
 async def on_submit(self,i):
  if not await self.view.interaction_check(i):return
  try:
   if self.epoch!=self.view.epoch or self.index!=len(self.view.picks)or self.view.method!='manual'or len(self.view.picks)>=self.view.count:raise ValueError('This entry changed. Reopen Pick My Numbers.')
   nums=validate_numbers([str(f)for f in self.fields],self.view.lo,old_picks(i.client.store,self.view.draw_id,self.view.uid)|set(self.view.picks));self.view.picks.append(nums);await self.view.refresh(i)
  except ValueError as e:await self.view.reply(i,str(e))

async def open_lottery(i,guard,reply,ensure_link):
 guard(i,player=True)
 if not i.client.store.cfg(i.guild_id)['enabled']:raise ValueError('New game entries are paused.')
 row=i.client.store.db.execute('SELECT id FROM draws WHERE guild=? AND type="lottery" AND status="open"',(i.guild_id,)).fetchone()
 if not row:raise ValueError('No open lottery draw. Ask the owner to open one.')
 draw=i.client.engine.draw(row[0])
 if draw['due']is not None and i.client.engine.clock()>=draw['due']-draw['state']['config']['lottery']['cutoff_minutes']*60:raise ValueError('Entries are closed for this draw.')
 view=LotteryEntry(i,draw,guard,reply,ensure_link);await reply(i,view.text(),view=view)
