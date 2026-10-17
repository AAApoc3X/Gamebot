"""Durable ticket and game rules. No network calls occur inside transactions."""
import json,secrets,time,uuid,math,hashlib
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from configuration import TIERS,GAMES,INSTANT,refund
RNG=secrets.SystemRandom()
def ident():return uuid.uuid4().hex
def weighted(values,weights,rng=RNG):return rng.choices(values,weights=weights,k=1)[0]
def next_due(schedule,tz,after):
 if schedule['mode']=='manual':return None
 if schedule['mode']=='interval':return after+schedule['minutes']*60
 local=datetime.fromtimestamp(after,ZoneInfo(tz));h,m=map(int,schedule['time'].split(':'))
 for d in range(9):
  day=local.date()+timedelta(days=d)
  if schedule['mode']in ('weekly','weekdays') and day.weekday()not in schedule['weekdays']:continue
  candidate=datetime(day.year,day.month,day.day,h,m,tzinfo=ZoneInfo(tz)).timestamp()
  if candidate>after:return candidate
 raise ValueError('Could not calculate next draw.')

def lottery_probabilities(low,high,lines):
 n=high-low+1;den=math.comb(n,3)
 one={k:math.comb(3,k)*math.comb(n-3,3-k)/den if n-3>=3-k else 0 for k in range(4)}
 # Premium exact probability for distinct combinations; lower outcomes depend on overlap.
 return {'one_combination':one,'premium_any':min(lines,den)/den}

class Engine:
 def __init__(self,store,rng=None,clock=None):self.s=store;self.rng=rng or RNG;self.clock=clock or time.time
 def claim(self,guild,uid,method,roles=()):
  with self.s.atomic():
   c=self.s.cfg(guild);d=c['daily'];now=self.clock()
   if not c['enabled']:raise ValueError('Games are paused.')
   if d['method'] not in ('both',method):raise ValueError('This daily-claim method is disabled.')
   if not c['allow_unlinked'] and not self.s.linked(guild,uid,roles):raise ValueError('KAOS-linked players only. Complete KAOS /link, then use /link_check to refresh your status.')
   r=self.s.db.execute('SELECT claimed FROM claims WHERE guild=? AND uid=?',(guild,uid)).fetchone()
   if r:
    same=(now-r[0]<86400) if d['reset']=='24h' else datetime.fromtimestamp(now,ZoneInfo(c['timezone'])).date()==datetime.fromtimestamp(r[0],ZoneInfo(c['timezone'])).date()
    if same:raise ValueError('You have already claimed your daily tickets.')
   self.s.money(guild,uid,d['amount'],'Daily claim',f'daily:{guild}:{uid}:{now}')
   self.s.db.execute('INSERT INTO claims VALUES(?,?,?) ON CONFLICT(guild,uid) DO UPDATE SET claimed=excluded.claimed',(guild,uid,now))
   return d['amount']
 def eligibility(self,guild,uid,roles=()):
  c=self.s.cfg(guild)
  if not c['enabled']:raise ValueError('Games are paused.')
  if not c['allow_unlinked'] and not self.s.linked(guild,uid,roles):raise ValueError('KAOS-linked players only. Complete KAOS /link, then use /link_check to refresh your status.')
  return c
 def kind(self,c,choice):
  if c['reward_mode']!='both':return c['reward_mode']
  if c['choice_timing']=='after':return 'choose'
  if choice not in ('kits','points'):raise ValueError('Choose kits or KAOS points before entering.')
  return choice
 def award(self,guild,uid,tier,c,kind,key):
  # Call within the same transaction as result recording; configuration is frozen.
  if kind=='choose':payload=[];status='choice'
  elif kind=='points':payload=[{'kind':'points','name':'','quantity':c['prizes'][tier]['points']['amount']}];status='pending'if c.get('server_id')is not None else 'awaiting_server'
  else:
   options=c['prizes'][tier]['kits']
   if not options:raise ValueError('This prize tier has no kit/item rewards. Ask the owner to configure it.')
   payload=deepcopy(weighted(options,[x['weight']for x in options],self.rng)['rewards']);status='pending'if c.get('server_id')is not None else 'awaiting_server'
  group=c.get('_destination_group')or key
  c=deepcopy(c);c['_destination_group']=group
  # One row per bundle; all children share a destination choice.
  if payload:
   for index,p in enumerate(payload):
    self.s.db.execute('INSERT OR IGNORE INTO rewards(id,guild,uid,tier,config,kind,payload,status,channel,created,destination_group) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
    (f'{key}:{index}',guild,uid,tier,json.dumps(c),kind,json.dumps(p),status,0,self.clock(),group))
  else:self.s.db.execute('INSERT OR IGNORE INTO rewards(id,guild,uid,tier,config,kind,payload,status,channel,created,destination_group) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,guild,uid,tier,json.dumps(c),kind,'[]',status,0,self.clock(),group))
 def choose_reward(self,guild,uid,key,choice):
  with self.s.atomic():
   r=self.s.db.execute('SELECT * FROM rewards WHERE id=? AND guild=? AND uid=? AND status="choice"',(key,guild,uid)).fetchone()
   if not r:raise ValueError('Reward already selected or unavailable.')
   if choice not in ('kits','points'):raise ValueError('Choose kits or points.')
   self.s.db.execute('DELETE FROM rewards WHERE id=?',(key,));self.award(guild,uid,r['tier'],json.loads(r['config']),choice,key)
 def session(self,key,guild=None,uid=None):
  r=self.s.db.execute('SELECT * FROM sessions WHERE id=?',(key,)).fetchone()
  if not r or (guild is not None and guild!=r['guild']) or (uid is not None and uid!=r['uid']):raise ValueError('Game not found for this player.')
  return dict(r)|{'state':json.loads(r['state'])}
 def write_session(self,r):self.s.db.execute('UPDATE sessions SET state=?,status=?,updated=? WHERE id=?',(json.dumps(r['state']),r['status'],self.clock(),r['id']))
 def start(self,guild,uid,game,level,kind,reference,roles=(),choice=None,server_id=None):
  with self.s.atomic():
   old=self.s.db.execute('SELECT id FROM sessions WHERE id=?',(reference,)).fetchone()
   if old:return self.session(reference,guild,uid)
   c=self.s.destinations.snapshot(guild,self.eligibility(guild,uid,roles),uid,server_id)
   if game not in GAMES or level not in TIERS:raise ValueError('Unknown game or level.')
   if not c['games'][game]['enabled']:raise ValueError('This game is disabled.')
   if self.s.db.execute('SELECT 1 FROM sessions WHERE guild=? AND uid=? AND status="active"',(guild,uid)).fetchone():raise ValueError('Finish your active game first using /resume.')
   kind=self.kind(c,kind)
   if kind=='kits' and any(not c['prizes'][t]['kits'] for t in TIERS):raise ValueError('Kit prizes have not been configured for every tier.')
   cost=c['games'][game]['costs'][level]
   self.s.money(guild,uid,-cost,'Game entry',reference+':entry')
   state={'config':c,'cost':cost,'level':level,'kind':kind,'steps':0,'log':[],'result':None,'tier':None}
   if game=='higher_lower':state.update(number=self.rng.randint(1,13))
   elif game=='minefield':state.update(mines=self.rng.sample(range(9),2),revealed=[])
   elif game=='deal_or_keep':state.update(offer=weighted(TIERS,c['games'][game]['odds'][level],self.rng))
   if game in ('higher_lower','minefield'):state['floor']=weighted(TIERS,c['games'][game]['odds'][level],self.rng)
   self.s.db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)',(reference,guild,uid,game,json.dumps(state),'active',self.clock(),self.clock()))
   r=self.session(reference)
   if game in INSTANT and game not in ('pick_a_crate','treasure_dig'):self._instant(r)
   elif game=='rps' and choice:self._move(r,choice)
   return self.session(reference)
 def _finish(self,r,tier,result):
  if r['status']!='active':raise ValueError('This game is already finished.')
  state=r['state'];state.update(tier=tier,result=result);r['status']='done'
  if tier:self.award(r['guild'],r['uid'],tier,state['config'],state['kind'],'game:'+r['id'])
  else:
   rule=state['config']['games'][r['game']]['draw_return' if result=='draw' else 'loss_return'];amount=refund(state['cost'],rule)
   self.s.money(r['guild'],r['uid'],amount,'Game ticket return','return:'+r['id']);state['returned']=amount
  self.write_session(r)
 def _instant(self,r):
  st=r['state'];game=r['game'];odds=st['config']['games'][game]['odds'][st['level']]
  tier=weighted(TIERS,odds,self.rng)
  details={'supply_drop':'Supply drop opened','pick_a_crate':'Crate opened','scratch_card':'Scratch card revealed','dice':'Dice combination rolled','prize_wheel':'Wheel stopped','fishing':'Catch landed','treasure_dig':'Treasure uncovered'}
  st['reveal']=details[game]
  if game=='scratch_card':st['symbols']=[tier.upper()]*3
  if game=='dice':st['dice']={'base':[1,2,3],'elite':[4,4,2],'premium':[6,6,6]}[tier]
  self._finish(r,tier,'win')
 def move(self,guild,uid,key,action):
  with self.s.atomic():
   r=self.session(key,guild,uid)
   if r['status']!='active':raise ValueError('Game already finished; use /history to see the result.')
   self._move(r,action);return self.session(key)
 def _move(self,r,action):
  st=r['state'];game=r['game']
  if game in ('pick_a_crate','treasure_dig'):
   if action not in ('1','2','3'):raise ValueError('Pick 1, 2 or 3.')
   st['selected']=action;self._instant(r);return
  if game=='rps':
   if action not in ('rock','paper','scissors'):raise ValueError('Choose rock, paper or scissors.')
   bot=self.rng.choice(('rock','paper','scissors'));st.update(player=action,bot=bot)
   result='draw' if action==bot else 'win' if (action,bot)in (('rock','scissors'),('paper','rock'),('scissors','paper')) else 'loss'
   self._finish(r,st['level'] if result=='win' else None,result);return
  if action=='collect' and game in ('higher_lower','minefield'):
   self._finish(r,TIERS[max(TIERS.index(st.get('floor','base')),min(2,st['steps']//2))],'collected');return
  if game=='higher_lower':
   if action not in ('higher','lower'):raise ValueError('Choose higher, lower or collect.')
   old=st['number'];n=self.rng.choice([x for x in range(1,14)if x!=old]);st['number']=n;st['log'].append([old,action,n])
   if (n>old)==(action=='higher'):
    st['steps']+=1
    if st['steps']>=4:self._finish(r,'premium','win');return
   else:self._finish(r,'base','incorrect');return
  elif game=='minefield':
   if action not in tuple(map(str,range(9))):raise ValueError('Choose a square or collect.')
   n=int(action)
   if n in st['revealed']:raise ValueError('Square already revealed.')
   st['revealed'].append(n)
   if n in st['mines']:self._finish(r,'base','mine');return
   st['steps']+=1
   if st['steps']>=4:self._finish(r,'premium','win');return
  elif game=='deal_or_keep':
   if action not in ('keep','trade'):raise ValueError('Choose keep or trade.')
   tier=st['offer'] if action=='keep' else weighted(TIERS,st['config']['games'][game]['odds'][st['level']],self.rng)
   self._finish(r,tier,'kept' if action=='keep' else 'traded');return
  else:raise ValueError('Unknown action.')
  self.write_session(r)
 def expire(self):
  with self.s.atomic():
   rows=self.s.db.execute('SELECT id FROM sessions WHERE status="active" AND updated<?',(self.clock()-900,)).fetchall()
   for row in rows:
    r=self.session(row[0]);st=r['state']
    if r['game']in ('higher_lower','minefield'):self._finish(r,TIERS[max(TIERS.index(st.get('floor','base')),min(2,st['steps']//2))],'timeout collected')
    elif r['game']=='deal_or_keep':self._finish(r,st['offer'],'timeout kept')
    else:
     self.s.money(r['guild'],r['uid'],st['cost'],'Unplayed game timeout refund','return:'+r['id']);st.update(tier=None,result='timeout refund',returned=st['cost']);r['status']='done';self.write_session(r)
 def open_lottery(self,guild):
  with self.s.atomic():
   old=self.s.db.execute('SELECT id FROM draws WHERE guild=? AND type="lottery" AND status="open"',(guild,)).fetchone()
   if old:return old[0]
   c=self.s.cfg(guild)
   if not c['enabled'] or not c['lottery']['enabled']:raise ValueError('Enable games and lottery before opening a draw.')
   due=next_due(c['lottery']['schedule'],c['timezone'],self.clock());key=ident()
   c=deepcopy(c);c['_destination_options']=self.s.destinations.options(guild,c['server_id']);c['_destination_timing']=self.s.destinations.timing(guild)
   state={'config':c,'winning':None,'summary':None}
   self.s.db.execute('INSERT INTO draws(id,guild,type,state,status,due,created) VALUES(?,?,?,?,?,?,?)',(key,guild,'lottery',json.dumps(state),'open',due,self.clock()));return key
 def draw(self,key):
  r=self.s.db.execute('SELECT * FROM draws WHERE id=?',(key,)).fetchone()
  if not r:raise ValueError('Draw not found.')
  return dict(r)|{'state':json.loads(r['state'])}
 def lottery_enter(self,guild,uid,key,lines,manual,kind,reference,roles=(),server_id=None):
  with self.s.atomic():
   self.eligibility(guild,uid,roles);r=self.draw(key);c=r['state']['config'];lo=c['lottery']
   if r['guild']!=guild or r['type']!='lottery' or r['status']!='open':raise ValueError('Draw is closed.')
   if r['due'] is not None and self.clock()>=r['due']-lo['cutoff_minutes']*60:raise ValueError('Entries have closed for this draw.')
   kind=self.kind(c,kind)
   if not c['allow_unlinked'] and not self.s.linked(guild,uid,roles):raise ValueError('This draw requires a verified KAOS link.')
   if type(lines)is not int or not 1<=lines<=100:raise ValueError('Enter 1–100 combinations per purchase.')
   if self.s.db.execute('SELECT 1 FROM ledger WHERE reference=?',(reference+':entry',)).fetchone():return []
   old={tuple(json.loads(x[0]))for x in self.s.db.execute('SELECT numbers FROM entries WHERE draw=? AND uid=?',(key,uid))}
   if lo['max_entries'] and len(old)+lines>lo['max_entries']:raise ValueError('Player entry limit exceeded.')
   if len(old)+lines>math.comb(lo['max']-lo['min']+1,3):raise ValueError('Not enough unused combinations left.')
   picks=[]
   if manual and lo['pick_mode']=='quick':raise ValueError('This draw permits Quick Pick only.')
   if not manual and lo['pick_mode']=='manual':raise ValueError('This draw requires manual numbers.')
   if manual:
    chunks=manual.replace('\n',';').split(';')
    if len(chunks)!=lines:raise ValueError('Provide one three-number combination per line, separated by semicolons.')
    for chunk in chunks:
     try:nums=tuple(sorted(map(int,chunk.replace(',',' ').split())))
     except ValueError:raise ValueError('Use three numbers separated by spaces or commas.')
     if len(nums)!=3 or len(set(nums))!=3 or not all(lo['min']<=n<=lo['max']for n in nums):raise ValueError('Choose three different numbers within the draw range.')
     if nums in old or nums in picks:raise ValueError('Duplicate combination for this player.')
     picks.append(nums)
   else:
    # Bounded random attempts then deterministic fill near saturation.
    for attempt in range(lines*50):
     if len(picks)==lines:break
     nums=tuple(sorted(self.rng.sample(range(lo['min'],lo['max']+1),3)))
     if nums not in old and nums not in picks:picks.append(nums)
    if len(picks)<lines:
     import itertools
     for nums in itertools.combinations(range(lo['min'],lo['max']+1),3):
      if nums not in old and nums not in picks:picks.append(nums)
      if len(picks)==lines:break
   total=lo['bundles'].get(str(lines),lo['cost']*lines)
   self.s.money(guild,uid,-total,'Lottery entry',reference+':entry')
   for i,nums in enumerate(picks):
    paid=total//lines+(1 if i<total%lines else 0)
    self.s.db.execute('INSERT INTO entries(id,draw,uid,numbers,cost,kind) VALUES(?,?,?,?,?,?)',(reference+':'+str(i),key,uid,json.dumps(nums),paid,kind))
    self.s.db.execute('UPDATE entries SET destination=? WHERE id=?',(json.dumps(self.entry_destination(guild,uid,c,server_id)),reference+':'+str(i)))
   return picks
 def settle_lottery(self,key,manual=False):
  with self.s.atomic():
   r=self.draw(key)
   if r['status']!='open' or r['type']!='lottery':raise ValueError('Lottery already closed.')
   if not manual and (r['due']is None or self.clock()<r['due']):raise ValueError('Not due yet.')
   st=r['state'];c=st['config'];lo=c['lottery'];win=sorted(self.rng.sample(range(lo['min'],lo['max']+1),3));st['winning']=win
   entries=[dict(x) for x in self.s.db.execute('SELECT * FROM entries WHERE draw=? ORDER BY id',(key,))]
   groups={}
   for ent in entries:
    ent['matches']=len(set(json.loads(ent['numbers']))&set(win));groups.setdefault(ent['uid'],[]).append(ent)
   summary=[]
   for uid,group in groups.items():
    winners=group if lo['payout']=='each' else [max(group,key=lambda x:x['matches'])]
    for ent in winners:
     matches=ent['matches'];ref='lottery:'+ent['id']
     if matches:self.award(r['guild'],uid,lo['reward_tiers'][str(matches)],self.entry_config(c,ent),ent['kind'],ref)
     else:
      cost=ent['cost'] if lo['payout']=='each' else sum(x['cost']for x in group)
      self.s.money(r['guild'],uid,refund(cost,lo['zero_return']),'Lottery zero-match return',ref+':return')
    summary.append({'uid':uid,'matches':max(x['matches']for x in group),'entries':len(group)})
   st['summary']=summary;self.s.db.execute('UPDATE draws SET status="drawn",state=? WHERE id=?',(json.dumps(st),key));return st
 def cancel_draw(self,key):
  with self.s.atomic():
   r=self.draw(key)
   if r['status']!='open':raise ValueError('Only open events can be cancelled.')
   for ent in self.s.db.execute('SELECT * FROM entries WHERE draw=?',(key,)).fetchall():self.s.money(r['guild'],ent['uid'],ent['cost'],'Cancelled event refund','cancel:'+ent['id'])
   self.s.db.execute('UPDATE draws SET status="cancelled" WHERE id=?',(key,))
 def open_event(self,guild,type_,actor):
  with self.s.atomic():
   if type_ not in ('bingo','giveaway'):raise ValueError('Choose bingo or giveaway.')
   c=self.s.cfg(guild);spec=c[type_]
   if not c['enabled']:raise ValueError('Games paused.')
   if self.s.db.execute('SELECT 1 FROM draws WHERE guild=? AND type=? AND status="open"',(guild,type_)).fetchone():raise ValueError('An event of that type is already open.')
   c=deepcopy(c);c['_destination_options']=self.s.destinations.options(guild,c['server_id']);c['_destination_timing']=self.s.destinations.timing(guild)
   key=ident();self.s.db.execute('INSERT INTO draws(id,guild,type,state,status,due,created) VALUES(?,?,?,?,?,?,?)',(key,guild,type_,json.dumps({'config':c}),'open',self.clock()+spec['minutes']*60,self.clock()));self.s.audit(guild,actor,'open_'+type_,key);return key
 def join_event(self,guild,uid,key,kind,reference,roles=(),server_id=None):
  with self.s.atomic():
   self.eligibility(guild,uid,roles);r=self.draw(key);c=r['state']['config']
   if r['guild']!=guild or r['type']not in ('bingo','giveaway') or r['status']!='open' or self.clock()>=r['due']:raise ValueError('Event closed.')
   if self.s.db.execute('SELECT 1 FROM entries WHERE draw=? AND uid=?',(key,uid)).fetchone():raise ValueError('Already entered.')
   if not c['allow_unlinked'] and not self.s.linked(guild,uid,roles):raise ValueError('KAOS link required for this event.')
   cost=c['bingo']['cost']if r['type']=='bingo' else 0
   nums=sorted(self.rng.sample(range(1,c['bingo']['numbers']+1),c['bingo']['size']**2))if r['type']=='bingo' else []
   if r['type']=='bingo':self.rng.shuffle(nums)
   kind=self.kind(c,kind);self.s.money(guild,uid,-cost,'Event entry',reference+':entry');self.s.db.execute('INSERT INTO entries(id,draw,uid,numbers,cost,kind) VALUES(?,?,?,?,?,?)',(reference,key,uid,json.dumps(nums),cost,kind));self.s.db.execute('UPDATE entries SET destination=? WHERE id=?',(json.dumps(self.entry_destination(guild,uid,c,server_id))if r['type']=='bingo'else '',reference));return nums
 def settle_event(self,key,manual=False):
  with self.s.atomic():
   r=self.draw(key)
   if r['status']!='open' or r['type']not in ('bingo','giveaway'):raise ValueError('Event closed.')
   if not manual and self.clock()<r['due']:raise ValueError('Not due yet.')
   st=r['state'];c=st['config'];entries=[dict(x)for x in self.s.db.execute('SELECT * FROM entries WHERE draw=?',(key,))]
   if r['type']=='giveaway':
    winners=self.rng.sample(entries,min(len(entries),c['giveaway']['winners']))
    for ent in winners:self.s.money(r['guild'],ent['uid'],c['giveaway']['amount'],'Ticket giveaway','giveaway:'+key+':'+str(ent['uid']))
    st['winners']=[x['uid']for x in winners];st['amount']=c['giveaway']['amount']
   else:
    b=c['bingo'];order=self.rng.sample(range(1,b['numbers']+1),b['numbers']);rank={n:i for i,n in enumerate(order)};scores={}
    size=b['size']
    for ent in entries:
     nums=json.loads(ent['numbers']);lines=[nums[i*size:(i+1)*size]for i in range(size)]+[nums[i::size]for i in range(size)]+[[nums[i*size+i]for i in range(size)],[nums[i*size+size-1-i]for i in range(size)]]
     scores[ent['uid']]=min(max(rank[n]for n in line)for line in lines)
    earliest=min(scores.values(),default=-1);st['winners']=[u for u,v in scores.items()if v==earliest];st['called']=order[:earliest+1]
    for ent in entries:
     tier=b['winner_tier']if ent['uid']in st['winners'] else b['participation_tier'];self.award(r['guild'],ent['uid'],tier,self.entry_config(c,ent),ent['kind'],'bingo:'+ent['id'])
   self.s.db.execute('UPDATE draws SET status="drawn",state=? WHERE id=?',(json.dumps(st),key));return st
 def entry_destination(self,guild,uid,c,server_id):
  opts=c.get('_destination_options',[{'slot':c['server_id'],'label':f"Game server {c['server_id']}"}])
  if not opts:raise ValueError('No game servers were available for this event. Ask the owner to cancel/refund it and open a configured event.')
  timing=c.get('_destination_timing','before')
  if timing=='after':return {'slot':None,'options':opts,'timing':timing}
  slot=server_id if server_id is not None else self.s.destinations.preference(guild,uid)
  if slot is None and len(opts)==1:slot=opts[0]['slot']
  if slot not in [x['slot']for x in opts]:raise ValueError('Select a game server before entering this event.')
  return {'slot':slot,'options':opts,'timing':timing}
 def entry_config(self,c,entry):
  c=deepcopy(c)
  if entry.get('destination'):
   d=json.loads(entry['destination']);c.update(server_id=d['slot'],_destination_options=d['options'],_destination_timing=d['timing'])
  return c
 def select_server(self,guild,uid,reward_id,server_id):
  with self.s.atomic():
   r=self.s.db.execute('SELECT * FROM rewards WHERE id=? AND guild=? AND uid=?',(reward_id,guild,uid)).fetchone()
   if not r:raise ValueError('Reward not found for this player.')
   c=json.loads(r['config']);opts=c.get('_destination_options',[])
   if c.get('server_id')is not None:raise ValueError('This reward already has a fixed destination.')
   if server_id not in [x['slot']for x in opts]:raise ValueError('Server was not available under this reward’s rules.')
   group=r['destination_group']or r['id']
   rows=self.s.db.execute('SELECT * FROM rewards WHERE guild=? AND uid=? AND destination_group=?',(guild,uid,group)).fetchall()
   if not rows:rows=[r]
   for row in rows:
    if row['status']not in ('choice','awaiting_server'):raise ValueError('A reward already started delivery; destination cannot change.')
   for row in rows:
    frozen=json.loads(row['config']);frozen['server_id']=server_id
    self.s.db.execute('UPDATE rewards SET config=?,status=? WHERE id=?',(json.dumps(frozen),'choice'if row['status']=='choice'else 'pending',row['id']))
 def purchase(self,guild,uid,code,quantity,payment_id):
  with self.s.atomic():
   c=self.s.cfg(guild)
   if code not in c['products']:raise ValueError('Unknown ticket product code.')
   if type(quantity)is not int or not 1<=quantity<=1000:raise ValueError('Invalid product quantity.')
   if not payment_id or len(payment_id)>150:raise ValueError('A stable payment reference is required.')
   ref=f'purchase:{guild}:{payment_id}:{code}'
   if self.s.db.execute('SELECT 1 FROM purchases WHERE reference=?',(ref,)).fetchone():return 0
   amount=c['products'][code]*quantity
   self.s.money(guild,uid,amount,'Tip4Serv purchase',ref);self.s.db.execute('INSERT INTO purchases VALUES(?,?,?,?,?)',(ref,guild,uid,amount,self.clock()));return amount
