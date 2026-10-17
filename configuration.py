"""Validated community settings. All prices/odds are owner controlled."""
from copy import deepcopy
import math,re
from zoneinfo import ZoneInfo
TIERS=('base','elite','premium')
INSTANT=('supply_drop','pick_a_crate','scratch_card','dice','prize_wheel','fishing','treasure_dig')
INTERACTIVE=('higher_lower','minefield','deal_or_keep','rps')
GAMES=INSTANT+INTERACTIVE

def defaults():
 return {'currency':'Tickets','timezone':'America/New_York','enabled':False,'delivery_enabled':False,
 'allow_unlinked':False,'linked_role':0,'staff_role':0,'games_channel':0,'daily_channel':0,
 'results_channel':0,'admin_channel':0,'transactions_channel':0,'purchase_store_id':0,
 'kaos_bot_id':0,'server_id':1,'choice_timing':'entry','reward_mode':'both','transfers_enabled':True,
 'daily':{'amount':1,'reset':'midnight','method':'both'},
 'games':{g:{'enabled':True,'costs':{'base':1,'elite':3,'premium':5},
 'odds':{'base':[80,18,2],'elite':[60,33,7],'premium':[40,45,15]},
 'loss_return':{'mode':'fixed','amount':0,'round':'down'},
 'draw_return':{'mode':'percent','amount':100,'round':'down'}} for g in GAMES},
 'prizes':{t:{'points':{'amount':v},'kits':[]} for t,v in zip(TIERS,(100,300,1000))},
 'lottery':{'enabled':False,'min':1,'max':20,'cost':1,'max_entries':20,'payout':'highest',
 'pick_mode':'both','bundles':{},'reward_tiers':{'1':'base','2':'elite','3':'premium'},'zero_return':{'mode':'percent','amount':100,'round':'down'},
 'schedule':{'mode':'daily','minutes':60,'time':'20:00','weekdays':[0,1,2,3,4,5,6]},
 'cutoff_minutes':5,'reminder_minutes':15,'announce_winners':True},
 'bingo':{'cost':1,'minutes':30,'numbers':30,'size':3,'participation_tier':'base','winner_tier':'premium'},
 'giveaway':{'amount':5,'winners':1,'minutes':60},'products':{}}

def integer(v,low,high,label):
 if type(v) is not int or not low<=v<=high:raise ValueError(f'{label}: whole number {low}–{high} required.')

def safe_name(v):
 if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}',v):raise ValueError('Kit/item name: 1–100 letters, numbers, spaces, dots, underscores or hyphens.')
 return v

def refund(cost,rule):
 if rule['mode']=='full':return cost
 if rule['mode']=='none':return 0
 if rule['mode']=='fixed':return rule['amount']
 v=cost*rule['amount']/100
 return math.ceil(v) if rule['round']=='up' else math.floor(v)

def validate_return(r):
 if set(r)!={'mode','amount','round'} or r['mode'] not in ('full','none','fixed','percent') or r['round'] not in ('up','down'):raise ValueError('Return uses mode full/none/fixed/percent, amount, and round up/down.')
 integer(r['amount'],0,1000000,'Ticket return')
 if r['mode']=='percent' and r['amount']>100:raise ValueError('Percentage return cannot exceed 100%.')

def shape(value,template,path='settings'):
 if type(value) is not type(template):raise ValueError(f'{path}: expected {type(template).__name__}.')
 if isinstance(template,dict):
  if set(value)!=set(template):raise ValueError(f'{path}: expected keys {", ".join(template)}.')
  for k in value:
   if k not in ('products','bundles'):shape(value[k],template[k],path+'.'+k)

def validate(c):
 shape(c,defaults())
 if not 1<=len(c['currency'])<=30 or not c['currency'].isprintable():raise ValueError('Currency name must contain 1–30 printable characters.')
 ZoneInfo(c['timezone'])
 for k in ('games_channel','daily_channel','results_channel','admin_channel','transactions_channel','kaos_bot_id','linked_role','staff_role','purchase_store_id'):integer(c[k],0,2**64-1,k)
 integer(c['server_id'],1,100,'KAOS server ID')
 if c['reward_mode'] not in ('kits','points','both') or c['choice_timing'] not in ('entry','after'):raise ValueError('reward_mode kits/points/both; choice_timing entry/after.')
 da=c['daily'];integer(da['amount'],1,1000000,'Daily amount')
 if da['reset'] not in ('midnight','24h') or da['method'] not in ('button','command','both'):raise ValueError('Daily reset midnight/24h; method button/command/both.')
 for name,g in c['games'].items():
  for t in TIERS:
   integer(g['costs'][t],1,1000000,'Entry cost')
   odds=g['odds'][t]
   if len(odds)!=3 or any(type(x) is not int or x<0 for x in odds) or sum(odds)!=100:raise ValueError('Each tier odds list must contain three integer percentages totaling 100.')
  # Higher spend must not reduce the chance of reaching either higher threshold.
  if not g['costs']['base']<g['costs']['elite']<g['costs']['premium']:raise ValueError('Game costs must increase Base < Elite < Premium.')
  a,b,p=[g['odds'][x] for x in TIERS]
  if not (a[2]<=b[2]<=p[2] and sum(a[1:])<=sum(b[1:])<=sum(p[1:])):raise ValueError('Higher entry levels must not lower Elite-or-better or Premium odds.')
  validate_return(g['loss_return']);validate_return(g['draw_return'])
 for tier,p in c['prizes'].items():
  integer(p['points']['amount'],1,1000000000,'Points amount')
  if len(p['kits'])>50:raise ValueError('Maximum 50 prize alternatives per tier.')
  for opt in p['kits']:
   if set(opt)!={'weight','rewards'}:raise ValueError('Prize alternative needs weight and rewards.')
   integer(opt['weight'],1,1000000,'Prize weight')
   if not 1<=len(opt['rewards'])<=10:raise ValueError('Each alternative needs 1–10 rewards.')
   for r in opt['rewards']:
    if set(r)!={'kind','name','quantity'} or r['kind'] not in ('kit','item'):raise ValueError('Reward requires kind kit/item, name and quantity.')
    safe_name(r['name']);integer(r['quantity'],1,1000000,'Quantity')
 lo=c['lottery'];integer(lo['min'],0,999,'Minimum number');integer(lo['max'],lo['min']+2,999,'Maximum number')
 integer(lo['cost'],1,1000000,'Combination cost');integer(lo['max_entries'],0,10000,'Entry limit (0 unlimited)')
 if lo['payout'] not in ('highest','each'):raise ValueError('Lottery payout highest/each.')
 if set(lo['reward_tiers'])!={'1','2','3'} or any(x not in TIERS for x in lo['reward_tiers'].values()):raise ValueError('Map matches 1, 2 and 3 to base/elite/premium.')
 if lo['pick_mode']not in ('both','manual','quick'):raise ValueError('Lottery pick_mode both/manual/quick.')
 for count,cost in lo['bundles'].items():
  if not count.isdigit()or not 1<=int(count)<=100:raise ValueError('Bundle keys are combination counts 1–100.')
  integer(cost,1,100000000,'Bundle cost')
 validate_return(lo['zero_return']);s=lo['schedule']
 if s['mode'] not in ('manual','interval','daily','weekly','weekdays'):raise ValueError('Schedule mode manual/interval/daily/weekly/weekdays.')
 integer(s['minutes'],1,525600,'Draw interval minutes')
 if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',s['time']):raise ValueError('Draw time HH:MM required.')
 if not s['weekdays'] or any(type(x)is not int or x not in range(7) for x in s['weekdays']):raise ValueError('Weekdays 0 Monday through 6 Sunday required.')
 if s['mode']=='weekly' and len(s['weekdays'])!=1:raise ValueError('Weekly schedule needs exactly one weekday.')
 for k in ('cutoff_minutes','reminder_minutes'):integer(lo[k],0,525600,k)
 if s['mode']=='interval' and lo['cutoff_minutes']>=s['minutes']:raise ValueError('Cutoff must be shorter than the interval.')
 b=c['bingo'];integer(b['cost'],1,1000000,'Bingo cost');integer(b['minutes'],1,10080,'Bingo minutes');integer(b['size'],2,5,'Bingo card size');integer(b['numbers'],b['size']**2,99,'Bingo number pool')
 if b['participation_tier']not in TIERS or b['winner_tier']not in TIERS:raise ValueError('Bingo prize tiers invalid.')
 g=c['giveaway'];integer(g['amount'],1,1000000,'Giveaway amount');integer(g['winners'],1,100,'Winners');integer(g['minutes'],1,10080,'Giveaway minutes')
 for k,v in c['products'].items():
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',k):raise ValueError('Product code must use letters, digits, underscore or hyphen.')
  integer(v,1,1000000,'Tickets per product')
 if c['enabled'] or c['delivery_enabled']:
  if not all(c[k] for k in ('games_channel','transactions_channel','kaos_bot_id')):raise ValueError('Set games channel, Transactions channel and KAOS bot ID first.')
  if c['games_channel']==c['transactions_channel']:raise ValueError('Games and Transactions channels must differ.')
  if c['reward_mode'] in ('kits','both') and any(not c['prizes'][t]['kits'] for t in TIERS):raise ValueError('Add kit/item alternatives to all three tiers, or select points-only rewards.')
 return c

def patch(c,section,value):
 n=deepcopy(c)
 if section=='general':
  allowed=set(n)-{'games','prizes','lottery','daily','bingo','giveaway','products'}
  if not isinstance(value,dict) or not set(value)<=allowed:raise ValueError('Unknown general setting.')
  n.update(value)
 elif section.startswith('game:'):
  name=section.split(':',1)[1]
  if name not in GAMES:raise ValueError('Unknown game.')
  n['games'][name]=value
 elif section.startswith('prize:'):
  tier=section.split(':',1)[1]
  if tier not in TIERS:raise ValueError('Unknown tier.')
  n['prizes'][tier]=value
 elif section in ('daily','lottery','bingo','giveaway','products'):n[section]=value
 else:raise ValueError('Unknown configuration section.')
 return validate(n)
