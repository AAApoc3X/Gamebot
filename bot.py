"""Rust Games Bot Discord interface. Start with python bot.py."""
import asyncio,csv,io,json,logging,os,re,time,uuid
from pathlib import Path
from typing import Literal,Optional
import discord
from discord import app_commands
from discord.ext import commands,tasks
from aiohttp import web
from storage import Store
from engine import Engine,ident,lottery_probabilities
from configuration import defaults,patch,validate,TIERS,GAMES,INSTANT,refund
from delivery import Delivery
from purchases import Purchases
ROOT=Path(__file__).resolve().parent
log=logging.getLogger('games')
GameName=Literal['supply_drop','pick_a_crate','scratch_card','dice','prize_wheel','fishing','treasure_dig','higher_lower','minefield','deal_or_keep','rps']
Level=Literal['base','elite','premium']
Kind=Literal['kits','points']
GAME_LABELS={'supply_drop':'Supply Drop','pick_a_crate':'Pick a Crate','scratch_card':'Scratch Card','dice':'Dice Challenge','prize_wheel':'Prize Wheel','fishing':'Fishing','treasure_dig':'Treasure Dig','higher_lower':'Higher or Lower','minefield':'Minefield','deal_or_keep':'Deal or Keep','rps':'Rock Paper Scissors'}
RULES={
 'higher_lower':'Four correct predictions reach Premium; two reach Elite. An incorrect guess awards Base. Collect at any time. Ties are not drawn. Higher entry levels can start with a higher prize floor.',
 'minefield':'Nine squares hide two mines. Two safe squares reach Elite; four reach Premium. Hitting a mine awards Base. Collect at any time. Higher entry levels can start with a higher prize floor.',
 'deal_or_keep':'Keep the revealed kit tier or trade once for a new tier drawn using the entry odds.',
 'rps':'Choose Rock, Paper or Scissors. The bot selects each with equal probability. A win awards your selected entry tier; a loss/draw uses the stated ticket return.',
 'pick_a_crate':'Choose one of three crates. All have the same displayed prize odds; no crate is secretly better.',
 'treasure_dig':'Choose one of three dig locations. All use the same displayed prize odds.'}

async def reply(i,text,**kw):
 if i.response.is_done():return await i.followup.send(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kw)
 return await i.response.send_message(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kw)
def file_json(name,data):return discord.File(io.BytesIO(json.dumps(data,indent=2).encode()),filename=name)
def roles(i):return [r.id for r in getattr(i.user,'roles',[])]
def guard(i,owner=False,player=False,daily=False):
 if not i.guild or not isinstance(i.user,discord.Member):raise ValueError('Use this command in your Discord server.')
 c=i.client.store.cfg(i.guild_id)
 if owner and i.user.id!=i.guild.owner_id:raise ValueError('Only the actual Discord server owner can use this command.')
 staff=i.user.id==i.guild.owner_id or i.user.guild_permissions.manage_guild or (c['staff_role']and c['staff_role']in roles(i))
 if not player and not owner and not staff:raise ValueError('Owner, Manage Server or the configured staff role required.')
 channel=c['daily_channel']if daily else c['games_channel']if player else c['admin_channel']
 if channel and channel!=i.channel_id and i.user.id!=i.guild.owner_id:raise ValueError('Use the configured '+('Daily claim'if daily else 'Games'if player else 'Admin')+' channel.')
 return c

class SafeView(discord.ui.View):
 def __init__(self,uid=None,timeout=300):super().__init__(timeout=timeout);self.uid=uid;self.busy=False
 async def interaction_check(self,i):
  if self.uid and i.user.id!=self.uid:await reply(i,'This control belongs to another player.');return False
  return True
 async def on_error(self,i,error,item):
  if isinstance(error,ValueError):await reply(i,str(error))
  else:log.error('View error',exc_info=(type(error),error,error.__traceback__));await reply(i,'The action could not finish. Check /history or /resume before trying again.')

class Confirm(SafeView):
 def __init__(self,uid,callback):super().__init__(uid);self.callback=callback
 @discord.ui.button(label='Confirm',style=discord.ButtonStyle.success)
 async def confirm(self,i,b):
  if self.busy:await reply(i,'Already processing.');return
  self.busy=True
  try:await self.callback(i)
  except Exception:self.busy=False;raise
  self.stop()
 @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
 async def cancel(self,i,b):
  if self.busy:await reply(i,'Already processing; check the result before taking another action.');return
  self.busy=True;self.stop();await i.response.edit_message(content='Cancelled. No new action taken.',view=None)

class SessionView(SafeView):
 def __init__(self,bot,r):
  super().__init__(r['uid'],timeout=900);self.bot=bot;self.key=r['id'];st=r['state'];game=r['game']
  if r['status']!='active':return
  actions={'rps':[('Rock','rock'),('Paper','paper'),('Scissors','scissors')],
  'higher_lower':[('Higher','higher'),('Lower','lower'),('Collect prize','collect')],
  'deal_or_keep':[('Keep '+st.get('offer','base').title(),'keep'),('Trade','trade')],
  'pick_a_crate':[(f'Crate {n}',str(n))for n in range(1,4)],'treasure_dig':[(f'Dig {n}',str(n))for n in range(1,4)]}
  if game=='minefield':actions[game]=[(str(n+1),str(n))for n in range(9)if n not in st['revealed']]+[('Collect prize','collect')]
  for label,action in actions.get(game,[]):
   btn=discord.ui.Button(label=label,style=discord.ButtonStyle.primary,custom_id=f'play:{self.key}:{action}')
   async def click(i,action=action):
    guard(i,player=True)
    # Result and rewards commit before animation; retries cannot change the roll.
    r=self.bot.engine.move(i.guild_id,i.user.id,self.key,action)
    if game=='rps':
     await i.response.edit_message(content='Your choice is locked. **3...**',view=None,attachments=[])
     await asyncio.sleep(1);await i.edit_original_response(content='**2...**');await asyncio.sleep(1);await i.edit_original_response(content='**1...**');await asyncio.sleep(1)
     await i.edit_original_response(content=f'You chose **{action.title()}**.');await asyncio.sleep(.6)
     st=r['state'];winner=st['player'] if st['result']=='win'else st['bot']
     asset=ROOT/'assets'/('draw.gif'if st['result']=='draw'else winner+'.gif')
     await i.edit_original_response(content=render_session(r),attachments=[discord.File(asset)]if asset.exists()else [],view=None)
    else:await i.response.edit_message(content=render_session(r),view=SessionView(self.bot,r),attachments=[])
   btn.callback=click;self.add_item(btn)

def render_session(r):
 st=r['state'];text=f'**{GAME_LABELS[r["game"]]} · {st["level"].title()} entry**\nGame ID: `{r["id"]}`\n'
 if r['status']=='active':
  if r['game']in ('higher_lower','minefield'):
   earned=TIERS[max(TIERS.index(st.get('floor','base')),min(2,st['steps']//2))];text+=f'Current collectible prize: **{earned.title()}**\n'
  if r['game']=='higher_lower':text+=f'Current number: **{st["number"]}** · Correct: {st["steps"]}\n'
  elif r['game']=='minefield':text+=f'Safe squares revealed: {st["steps"]}\n'
  elif r['game']=='deal_or_keep':text+=f'Current offer: **{st["offer"].title()}**\n'
  return text+'Choose below. Use `/resume` after a disconnect. Inactive games settle after 15 minutes.'
 if r['game']=='rps':text+=f'You: **{st.get("player","—")}** · Bot: **{st.get("bot","—")}**\n'
 if st.get('dice'):text+='Dice: '+', '.join(map(str,st['dice']))+'\n'
 if st.get('symbols'):text+=' | '.join(st['symbols'])+'\n'
 text+=f'**{st["result"].title()}**'
 if st['tier']:text+=f' · **{st["tier"].title()} prize**. '+('Choose kits or KAOS points using `/prizes`.'if st['kind']=='choose'else 'Reward recorded. See `/prizes` for delivery status.')
 else:text+=f' · Returned {st.get("returned",0)} {st["config"]["currency"]}.'
 return text

async def review_game(i,game,level,kind):
 c=guard(i,player=True);i.client.engine.eligibility(i.guild_id,i.user.id,roles(i));g=c['games'][game];cost=g['costs'][level]
 odds=g['odds'][level];desc=RULES.get(game,'Reveal a guaranteed Base, Elite or Premium prize using the displayed tier odds.')
 text=f'**{GAME_LABELS[game]} · {level.title()}**\nCost: **{cost} {c["currency"]}**\n{desc}\n'
 if game=='rps':text+=f'Win: {level.title()} prize. Loss return: {refund(cost,g["loss_return"])}. Draw return: {refund(cost,g["draw_return"])} {c["currency"]}.\n'
 else:text+=f'Initial tier odds: Base {odds[0]}%, Elite {odds[1]}%, Premium {odds[2]}%.\n'
 text+='Reward: '+('choose after winning'if c['choice_timing']=='after'and c['reward_mode']=='both'else kind if c['reward_mode']=='both'else c['reward_mode'])+'.\nConfirm to spend tickets. Current settings apply when you confirm.'
 # Snapshot hash prevents a configuration change between displayed cost and confirmation.
 frozen=json.dumps(c,sort_keys=True)
 async def accept(j):
  guard(j,player=True)
  if json.dumps(j.client.store.cfg(j.guild_id),sort_keys=True)!=frozen:raise ValueError('Settings changed. Open the game again to review the new cost and odds.')
  r=j.client.engine.start(j.guild_id,j.user.id,game,level,kind,'game:'+str(j.id),roles(j))
  await j.response.edit_message(content=render_session(r),view=SessionView(j.client,r))
 await reply(i,text,view=Confirm(i.user.id,accept),file=file_json('prize-rules.json',{'prizes':c['prizes'],'game':g,'reward_mode':c['reward_mode'],'choice_timing':c['choice_timing']}))

class Lobby(SafeView):
 def __init__(self,uid):
  super().__init__(uid);self.game='supply_drop';self.level='base';self.kind='kits'
  for field,opts,placeholder in [('game',[(GAME_LABELS[x],x)for x in GAMES],'Game (default Supply Drop)'),('level',[(x.title(),x)for x in TIERS],'Entry level (default Base)'),('kind',[('Kits or items','kits'),('KAOS points','points')],'Reward (default Kits/items)')]:
   sel=discord.ui.Select(placeholder=placeholder,options=[discord.SelectOption(label=l,value=v)for l,v in opts])
   async def choose(i,field=field,sel=sel):setattr(self,field,sel.values[0]);await i.response.defer()
   sel.callback=choose;self.add_item(sel)
 @discord.ui.button(label='Review entry',style=discord.ButtonStyle.success)
 async def enter(self,i,b):await review_game(i,self.game,self.level,self.kind)

class Panel(SafeView):
 def __init__(self,type_):
  super().__init__(timeout=None);self.type=type_
  buttons=[('Claim Daily Tickets','daily')]if type_=='daily'else [('Choose a game','lobby'),('My balance','balance'),('My prizes','prizes'),('Lottery','lottery'),('Bingo and giveaways','events')]
  for label,action in buttons:
   btn=discord.ui.Button(label=label,style=discord.ButtonStyle.primary,custom_id='gamespanel:'+action)
   async def click(i,action=action):
    if action=='daily':
     c=guard(i,player=True,daily=True);amount=i.client.engine.claim(i.guild_id,i.user.id,'button',roles(i));await reply(i,f'Claimed **{amount} {c["currency"]}**.')
    elif action=='lobby':guard(i,player=True);await reply(i,'Choose a game, entry level and reward type, then review the cost.',view=Lobby(i.user.id))
    elif action=='balance':guard(i,player=True);await reply(i,f'Balance: **{i.client.store.balance(i.guild_id,i.user.id)} {i.client.store.cfg(i.guild_id)["currency"]}**.')
    elif action=='prizes':await show_prizes(i)
    elif action=='lottery':await show_lottery(i)
    else:await show_events(i)
   btn.callback=click;self.add_item(btn)

async def show_prizes(i):
 guard(i,player=True);rows=i.client.store.db.execute('SELECT * FROM rewards WHERE guild=? AND uid=? ORDER BY created DESC LIMIT 30',(i.guild_id,i.user.id)).fetchall()
 if not rows:await reply(i,'No rewards yet.');return
 text='**Your recent rewards**\n'+'\n'.join(f'`{r["id"]}` · {r["tier"].title()} · {r["status"]}'+(' · '+str(json.loads(r['payload']).get('quantity',''))+' '+(json.loads(r['payload']).get('name')or 'KAOS points')if r['status']!='choice'else '') for r in rows)
 view=SafeView(i.user.id)
 for row in [r for r in rows if r['status']=='choice'][:5]:
  for kind in ('kits','points'):
   btn=discord.ui.Button(label=f'{row["tier"].title()} {kind} ({row["id"][-6:]})')
   async def choose(j,key=row['id'],kind=kind):
    guard(j,player=True);j.client.engine.choose_reward(j.guild_id,j.user.id,key,kind);await reply(j,'Reward choice saved. Use /prizes to see the updated status.')
   btn.callback=choose;view.add_item(btn)
 await reply(i,text[:1900],view=view)

async def show_lottery(i):
 guard(i,player=True);r=i.client.store.db.execute('SELECT id FROM draws WHERE guild=? AND type="lottery" AND status="open"',(i.guild_id,)).fetchone()
 if not r:await reply(i,'No open lottery draw. Ask the owner to enable/open one.');return
 draw=i.client.engine.draw(r[0]);lo=draw['state']['config']['lottery'];due=f'<t:{int(draw["due"])}:F>'if draw['due']else 'Owner will draw manually'
 probs=lottery_probabilities(lo['min'],lo['max'],1)
 text=f'**Rust World Lottery**\nDraw ID: `{r[0]}`\nDraw: {due}\nChoose 3 different numbers from {lo["min"]}–{lo["max"]}; matches count in any order.\nCost per combination: {lo["cost"]} tickets. Payout: {lo["payout"]}.\n1/2/3 matches: '+', '.join(lo['reward_tiers'][str(k)].title()for k in (1,2,3))+f'. Zero matches: {json.dumps(lo["zero_return"])}.\nSingle-combination match chances: '+', '.join(f'{k}: {v:.4%}'for k,v in probs['one_combination'].items())+'.\nUse `/lottery enter` with a combination count and optional numbers. More unique combinations improve the chance of a higher match.'
 await reply(i,text)

async def show_events(i):
 guard(i,player=True);rs=i.client.store.db.execute('SELECT id,type,due FROM draws WHERE guild=? AND status="open" AND type IN ("bingo","giveaway")',(i.guild_id,)).fetchall();v=SafeView(i.user.id)
 if not rs:await reply(i,'No bingo or ticket giveaway is open.');return
 for r in rs:
  for kind in ('kits','points')if r['type']=='bingo'else ('points',):
   btn=discord.ui.Button(label=f'Join {r["type"]}'+(f' · {kind}'if r['type']=='bingo'else ''))
   async def join(j,key=r['id'],kind=kind):
    c=guard(j,player=True);d=j.client.engine.draw(key);spec=d['state']['config']['bingo'];cost=spec['cost']if d['type']=='bingo'else 0
    async def confirm(k):
     guard(k,player=True);nums=k.client.engine.join_event(k.guild_id,k.user.id,key,kind,'event:'+str(k.id),roles(k));await k.response.edit_message(content='Entered. '+('Your bingo card: '+', '.join(map(str,nums))if nums else 'Good luck!'),view=None)
    await reply(j,f'Join {d["type"]} for **{cost} {c["currency"]}**? '+('Winner tier '+spec['winner_tier']+'; all other entrants receive '+spec['participation_tier']+'. Reward: '+kind+'. Card completes on a row, column or diagonal.'if cost else 'Free entry; ticket winners are selected randomly at closing.'),view=Confirm(j.user.id,confirm))
   btn.callback=join;v.add_item(btn)
 await reply(i,'**Open events**\n'+'\n'.join(f'{r["type"].title()} · closes <t:{int(r["due"])}:R> · `{r["id"]}`'for r in rs),view=v)

class ConfigModal(discord.ui.Modal):
 def __init__(self,section,value):
  super().__init__(title='Edit '+section[:35]);self.section=section
  self.text=discord.ui.TextInput(label='Settings JSON',style=discord.TextStyle.paragraph,default=json.dumps(value,indent=2)[:4000],max_length=4000);self.add_item(self.text)
 async def on_submit(self,i):
  try:
   guard(i,owner=True);value=json.loads(str(self.text));c=patch(i.client.store.cfg(i.guild_id),self.section,value);i.client.store.save(i.guild_id,c,i.user.id)
   await reply(i,'Settings saved. Existing games and draws retain their entry rules. New settings apply to new games/draws.')
  except (ValueError,KeyError,TypeError)as exc:await reply(i,'Not saved: '+str(exc))

class GamesBot(commands.Bot):
 def __init__(self,path=None):
  intents=discord.Intents.default();intents.message_content=False
  super().__init__(command_prefix=commands.when_mentioned,intents=intents,allowed_mentions=discord.AllowedMentions.none())
  self.store=Store(path or Path(os.getenv('DATA_DIR',str(ROOT/'data')))/'games.sqlite3');self.engine=Engine(self.store);self.delivery=Delivery(self,self.store);self.http_runner=None
 async def setup_hook(self):
  self.add_view(Panel('games'));self.add_view(Panel('daily'))
  guild_id=os.getenv('DISCORD_GUILD_ID')
  if guild_id:self.tree.copy_global_to(guild=discord.Object(id=int(guild_id)));await self.tree.sync(guild=discord.Object(id=int(guild_id)))
  else:await self.tree.sync()
  secret=os.getenv('TIP4SERV_WEBHOOK_SECRET')
  if secret:
   app=Purchases(self.store,self.engine,secret).app();self.http_runner=web.AppRunner(app,access_log=None);await self.http_runner.setup();await web.TCPSite(self.http_runner,'0.0.0.0',int(os.getenv('PORT','8080'))).start()
  self.worker.start()
 async def close(self):
  self.worker.cancel()
  if self.http_runner:await self.http_runner.cleanup()
  await super().close();self.store.close()
 async def on_ready(self):log.info('Games bot ready as %s',self.user)
 @tasks.loop(seconds=3)
 async def worker(self):
  try:
   self.engine.expire()
   for row in self.store.db.execute('SELECT guild FROM communities').fetchall():
    guild=row[0];c=self.store.cfg(guild)
    # Always settle paid open events, even when new entries are paused.
    for d in self.store.db.execute('SELECT id,type,due,state,reminded FROM draws WHERE guild=? AND status="open"',(guild,)).fetchall():
     if d['due']and d['due']<=time.time():
      if d['type']=='lottery':self.engine.settle_lottery(d['id'])
      else:self.engine.settle_event(d['id'])
     elif d['type']=='lottery' and d['due']and not d['reminded']:
      frozen=json.loads(d['state'])['config'];minutes=frozen['lottery']['reminder_minutes']
      if minutes and d['due']-time.time()<=minutes*60:
       channel=self.get_channel(frozen['results_channel'])
       if channel:
        await channel.send(f'Rust World Lottery draw `{d["id"]}` is in {max(1,int((d["due"]-time.time())/60))} minutes. Entry cutoff: {frozen["lottery"]["cutoff_minutes"]} minutes before draw.',allowed_mentions=discord.AllowedMentions.none());self.store.db.execute('UPDATE draws SET reminded=1 WHERE id=?',(d['id'],))
    if c['enabled']and c['lottery']['enabled']:self.engine.open_lottery(guild)
   for d in self.store.db.execute('SELECT * FROM draws WHERE status IN ("drawn","cancelled") AND announced=0').fetchall():
    st=json.loads(d['state']);c=st['config'];channel=self.get_channel(c['results_channel'])
    if channel:
     text=f'**{d["type"].title()} {d["status"]}** · `{d["id"]}`\n'
     if d['type']=='lottery' and st.get('winning'):
      text+='Winning numbers: **'+', '.join(map(str,st['winning']))+'**\n'
      if c['lottery']['announce_winners']:text+='\n'.join(f'<@{x["uid"]}>: {x["matches"]} matches'for x in st.get('summary',[])[:20])
     elif st.get('winners')is not None:text+='Winners: '+', '.join(f'<@{u}>'for u in st['winners'])+'\n'+('Called numbers: '+', '.join(map(str,st['called']))if 'called'in st else f'Tickets per winner: {st.get("amount",0)}')
     await channel.send(text[:1900],allowed_mentions=discord.AllowedMentions.none());self.store.db.execute('UPDATE draws SET announced=1 WHERE id=?',(d['id'],))
   await self.delivery.tick()
  except Exception:log.exception('Background task failed; will continue next cycle')
 @worker.before_loop
 async def before_worker(self):await self.wait_until_ready()

def attach_commands(bot):
 admin=app_commands.Group(name='gamesadmin',description='Owner setup, game settings, rewards and ticket administration',guild_only=True)
 lottery=app_commands.Group(name='lottery',description='Rust World Lottery entries and results',guild_only=True)
 @bot.tree.command(name='games',description='Open the games menu')
 async def games(i:discord.Interaction):guard(i,player=True);await reply(i,'Choose a game, entry level and reward type.',view=Lobby(i.user.id))
 @bot.tree.command(name='play',description='Review a game, ticket cost and prize rules before spending')
 @app_commands.describe(game='Game to play',level='Base, Elite or Premium entry level',reward='Kits/items or KAOS points; owner settings determine when you choose')
 async def play(i:discord.Interaction,game:GameName,level:Level='base',reward:Kind='kits'):await review_game(i,game,level,reward)
 @bot.tree.command(name='daily',description='Claim your daily tickets in the Daily claim channel')
 async def daily(i:discord.Interaction):
  c=guard(i,player=True,daily=True);n=bot.engine.claim(i.guild_id,i.user.id,'command',roles(i));await reply(i,f'Claimed **{n} {c["currency"]}**.')
 @bot.tree.command(name='balance',description='See your ticket balance')
 async def balance(i:discord.Interaction):c=guard(i,player=True);await reply(i,f'Balance: **{bot.store.balance(i.guild_id,i.user.id)} {c["currency"]}**.')
 @bot.tree.command(name='give',description='Give tickets to another player with confirmation')
 async def give(i:discord.Interaction,player:discord.Member,amount:app_commands.Range[int,1,1000000]):
  c=guard(i,player=True)
  if player.bot:raise ValueError('Choose a human player.')
  async def accept(j):
   guard(j,player=True);bot.store.transfer(j.guild_id,j.user.id,player.id,amount,'transfer:'+str(j.id));await j.response.edit_message(content=f'Transferred {amount} {c["currency"]} to {player.display_name}.',view=None,allowed_mentions=discord.AllowedMentions.none())
  await reply(i,f'Give **{amount} {c["currency"]}** to **{player.display_name}**?',view=Confirm(i.user.id,accept))
 @bot.tree.command(name='resume',description='Resume your unfinished game after a disconnect')
 async def resume(i:discord.Interaction):
  guard(i,player=True);r=bot.store.db.execute('SELECT id FROM sessions WHERE guild=? AND uid=? AND status="active"',(i.guild_id,i.user.id)).fetchone()
  if not r:await reply(i,'No unfinished game. Check /history for completed results.');return
  r=bot.engine.session(r[0]);await reply(i,render_session(r),view=SessionView(bot,r))
 @bot.tree.command(name='prizes',description='See your kit/points rewards, make choices and check delivery status')
 async def prizes(i:discord.Interaction):await show_prizes(i)
 @bot.tree.command(name='claim_prize',description='Choose kits/items or KAOS points for an older unclaimed reward')
 async def claim_prize(i:discord.Interaction,reward_id:str,reward:Kind):
  guard(i,player=True);bot.engine.choose_reward(i.guild_id,i.user.id,reward_id,reward);await reply(i,'Reward choice saved. See /prizes or ask staff for the report.')
 @bot.tree.command(name='history',description='Download your ticket and game history')
 async def history(i:discord.Interaction):
  guard(i,player=True);rows=[dict(r)for r in bot.store.db.execute('SELECT delta,reason,reference,created FROM ledger WHERE guild=? AND uid=? ORDER BY id DESC LIMIT 1000',(i.guild_id,i.user.id))];games=[{'id':r['id'],'game':r['game'],'status':r['status'],'result':json.loads(r['state']).get('result'),'tier':json.loads(r['state']).get('tier')}for r in bot.store.db.execute('SELECT * FROM sessions WHERE guild=? AND uid=? ORDER BY created DESC LIMIT 100',(i.guild_id,i.user.id))]
  await reply(i,'Your recent ticket ledger and game results.',file=file_json('my-games-history.json',{'ledger':rows,'games':games,'rewards':[dict(r)for r in bot.store.db.execute('SELECT id,tier,payload,status,detail FROM rewards WHERE guild=? AND uid=? ORDER BY created DESC LIMIT 1000',(i.guild_id,i.user.id))]}))
 @bot.tree.command(name='events',description='Join community bingo and free ticket giveaways')
 async def events(i:discord.Interaction):await show_events(i)
 @lottery.command(name='show',description='See the current draw, rules, entry cost and odds')
 async def show(i:discord.Interaction):await show_lottery(i)
 @lottery.command(name='enter',description='Review manual picks or Quick Pick combinations before paying')
 @app_commands.describe(combinations='Number of unique three-number combinations to buy',numbers='Optional: 1,2,3; 4,5,6. Leave blank for Quick Pick.',reward='Kits/items or KAOS points')
 async def enter(i:discord.Interaction,combinations:app_commands.Range[int,1,100]=1,numbers:str='',reward:Kind='kits'):
  c=guard(i,player=True);r=bot.store.db.execute('SELECT id FROM draws WHERE guild=? AND type="lottery" AND status="open"',(i.guild_id,)).fetchone()
  if not r:raise ValueError('No open lottery.')
  draw=bot.engine.draw(r[0]);lo=draw['state']['config']['lottery'];prob=lottery_probabilities(lo['min'],lo['max'],combinations)
  async def accept(j):
   guard(j,player=True);picks=bot.engine.lottery_enter(j.guild_id,j.user.id,r[0],combinations,numbers,reward,'lotteryentry:'+str(j.id),roles(j));await j.response.edit_message(content='Entered draw `'+r[0]+'`. Your numbers:\n'+'\n'.join(', '.join(map(str,x))for x in picks),view=None)
  await reply(i,f'Buy **{combinations} combinations** for **{lo["bundles"].get(str(combinations),combinations*lo["cost"])} {c["currency"]}**?\nPicks: {numbers or "Quick Pick"}\nPayout: {lo["payout"]}; reward: {reward if draw["state"]["config"]["choice_timing"]=="entry" else "choose after winning"}.\n1/2/3 matches: '+', '.join(lo['reward_tiers'][str(k)]for k in (1,2,3))+f'. Zero-match return: {json.dumps(lo["zero_return"])}.\nChance of all three numbers across these new unique combinations: {prob["premium_any"]:.6%}. Lower match odds depend on overlap between your combinations.',view=Confirm(i.user.id,accept),file=file_json('lottery-prize-rules.json',draw['state']['config']['prizes']))
 @lottery.command(name='entries',description='See your combinations in the current lottery')
 async def entries(i:discord.Interaction):
  guard(i,player=True);rs=[dict(r)for r in bot.store.db.execute('SELECT entries.* FROM entries JOIN draws ON entries.draw=draws.id WHERE draws.guild=? AND entries.uid=? AND draws.type="lottery" ORDER BY draws.created DESC LIMIT 1000',(i.guild_id,i.user.id))];await reply(i,'Your latest lottery entries.',file=file_json('lottery-entries.json',rs))
 @admin.command(name='setup',description='Owner selects Games, Daily claim, Transactions and admin channels')
 @app_commands.describe(games_channel='Channel where members play games and run game commands',daily_channel='Channel with daily ticket button and/or daily claim command',transactions_channel='KAOS Transactions channel for in-game kit, item and points commands',kaos_bot='Select the actual KAOS bot member',server_id='KAOS game server number: S1 = 1, S2 = 2',results_channel='Channel for lottery numbers and community event results',admin_channel='Private channel for owner and authorized staff commands')
 async def setup(i:discord.Interaction,games_channel:discord.TextChannel,daily_channel:discord.TextChannel,transactions_channel:discord.TextChannel,kaos_bot:discord.Member,results_channel:discord.TextChannel,admin_channel:discord.TextChannel,server_id:app_commands.Range[int,1,100]=1,linked_role:Optional[discord.Role]=None):
  guard(i,owner=True)
  if not kaos_bot.bot:raise ValueError('Select the actual KAOS bot, not a person.')
  if transactions_channel.id in (games_channel.id,daily_channel.id,results_channel.id):raise ValueError('Keep Transactions separate from public channels.')
  for ch in (games_channel,daily_channel,transactions_channel,results_channel,admin_channel):
   p=ch.permissions_for(i.guild.me)
   if not(p.view_channel and p.send_messages and p.read_message_history):raise ValueError(f'Bot needs View Channel, Send Messages and Read Message History in {ch.name}.')
   if ch in (games_channel,admin_channel) and not(p.attach_files and p.embed_links):raise ValueError(f'Bot needs Attach Files and Embed Links in {ch.name}.')
  c=bot.store.cfg(i.guild_id);c.update(games_channel=games_channel.id,daily_channel=daily_channel.id,transactions_channel=transactions_channel.id,kaos_bot_id=kaos_bot.id,results_channel=results_channel.id,admin_channel=admin_channel.id,server_id=server_id,linked_role=linked_role.id if linked_role else 0);bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Channels saved. Games and delivery remain at their existing enabled/paused settings. Configure prizes and participation, test delivery, then enable.')
 @admin.command(name='configure',description='Owner edits validated settings for a game, prizes or community controls')
 @app_commands.describe(section='general, daily, lottery, bingo, giveaway, products, game:rps, prize:base, etc.')
 async def configure(i:discord.Interaction,section:str):
  c=guard(i,owner=True)
  if section=='general':value={k:v for k,v in c.items()if k not in ('games','prizes','daily','lottery','bingo','giveaway','products')}
  elif section.startswith('game:')and section.split(':')[1]in GAMES:value=c['games'][section.split(':')[1]]
  elif section.startswith('prize:')and section.split(':')[1]in TIERS:value=c['prizes'][section.split(':')[1]]
  elif section in ('daily','lottery','bingo','giveaway','products'):value=c[section]
  else:raise ValueError('Choose a configuration section from the suggestions.')
  if len(json.dumps(value,indent=2))>4000:raise ValueError('This section exceeds the editor size. Export and use /gamesadmin import_config.')
  await i.response.send_modal(ConfigModal(section,value))
 @configure.autocomplete('section')
 async def sections(i,current):return [app_commands.Choice(name=x,value=x)for x in ['general','daily','lottery','bingo','giveaway','products']+['game:'+g for g in GAMES]+['prize:'+t for t in TIERS]if current.lower()in x][:25]
 @admin.command(name='settings',description='Export all current settings and prize rules')
 async def settings(i:discord.Interaction):guard(i,owner=True);await reply(i,'Current community configuration. No secrets included.',file=file_json('games-settings.json',bot.store.cfg(i.guild_id)))
 @admin.command(name='import_config',description='Owner uploads a complete configuration JSON file')
 async def import_config(i:discord.Interaction,file:discord.Attachment):
  guard(i,owner=True)
  if file.size>100000:raise ValueError('Configuration maximum 100 KB.')
  await i.response.defer(ephemeral=True);c=json.loads(await file.read());validate(c)
  async def accept(j):guard(j,owner=True);bot.store.save(j.guild_id,c,j.user.id);await j.response.edit_message(content='Configuration replaced. Existing game and draw rules are preserved.',view=None)
  await reply(i,'Replace all settings using this validated file?',view=Confirm(i.user.id,accept))
 @admin.command(name='enable',description='Owner separately enables or pauses new games and in-game delivery')
 async def enable(i:discord.Interaction,games:bool,delivery:bool):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);c.update(enabled=games,delivery_enabled=delivery);bot.store.save(i.guild_id,c,i.user.id);await reply(i,f'New games: {games}. KAOS delivery: {delivery}. Open paid draws and active games still settle.')
 @admin.command(name='panel',description='Post or update the Games menu or Daily claim button')
 async def panel(i:discord.Interaction,type:Literal['games','daily']):
  c=guard(i,owner=True);channel=i.guild.get_channel(c['games_channel'if type=='games'else 'daily_channel'])
  if not channel:raise ValueError('Configure the channel first.')
  await i.response.defer(ephemeral=True);text='**Games**\nChoose a game, check your balance or collect your prizes.'if type=='games'else f'**Daily {c["currency"]}**\nClaim {c["daily"]["amount"]} {c["currency"]}. Reset: {c["daily"]["reset"]}. Button and /daily share one claim allowance.'
  old=bot.store.db.execute('SELECT channel,message FROM panels WHERE guild=? AND type=?',(i.guild_id,type)).fetchone();msg=None
  if old and old['channel']==channel.id:
   try:msg=await channel.fetch_message(old['message']);await msg.edit(content=text,view=Panel(type))
   except discord.NotFound:pass
  if msg is None:msg=await channel.send(text,view=Panel(type),allowed_mentions=discord.AllowedMentions.none())
  bot.store.db.execute('INSERT INTO panels VALUES(?,?,?,?) ON CONFLICT(guild,type) DO UPDATE SET channel=excluded.channel,message=excluded.message',(i.guild_id,type,channel.id,msg.id));await reply(i,'Panel posted/updated. Re-run this after changing its text settings.')
 @admin.command(name='tickets',description='Grant or remove tickets for a player with an audit reason')
 async def tickets(i:discord.Interaction,player:discord.Member,amount:app_commands.Range[int,-1000000,1000000],reason:str):
  guard(i)
  if player.bot or amount==0:raise ValueError('Choose a person and a nonzero amount.')
  async def accept(j):
   guard(j);bot.store.money(j.guild_id,player.id,amount,'Staff: '+reason[:200],'staff:'+str(j.id));bot.store.audit(j.guild_id,j.user.id,'tickets',f'{player.id}: {amount}; {reason[:200]}');await j.response.edit_message(content=f'Balance adjusted by {amount}.',view=None)
  await reply(i,f'Adjust {player.display_name} by **{amount} tickets**? Reason: {reason[:200]}',view=Confirm(i.user.id,accept))
 @admin.command(name='verify_link',description='Owner records a KAOS link after checking it in KAOS')
 async def verify_link(i:discord.Interaction,player:discord.Member,linked:bool):
  guard(i,owner=True);bot.store.verify(i.guild_id,player.id,linked,i.user.id);await reply(i,'Link verification recorded. This does not create a KAOS link; verify their actual /link in KAOS first. Explicit false overrides the linked role.')
 @admin.command(name='event',description='Owner opens, draws or cancels lottery, bingo and ticket giveaways')
 async def event(i:discord.Interaction,type:Literal['lottery','bingo','giveaway'],action:Literal['open','draw','cancel']):
  guard(i,owner=True)
  async def accept(j):
   guard(j,owner=True)
   if action=='open':key=bot.engine.open_lottery(j.guild_id)if type=='lottery'else bot.engine.open_event(j.guild_id,type,j.user.id);result='Opened `'+key+'`.'
   else:
    r=bot.store.db.execute('SELECT id FROM draws WHERE guild=? AND type=? AND status="open"',(j.guild_id,type)).fetchone()
    if not r:raise ValueError('No open event of that type.')
    if action=='cancel':bot.engine.cancel_draw(r[0]);result='Event cancelled. Entry costs refunded.'
    else:
     st=bot.engine.settle_lottery(r[0],True)if type=='lottery'else bot.engine.settle_event(r[0],True);result='Draw completed; rewards recorded. '+json.dumps({k:v for k,v in st.items()if k!='config'})[:1200]
   bot.store.audit(j.guild_id,j.user.id,'event_'+action,type);await j.response.edit_message(content=result,view=None)
  await reply(i,f'Confirm **{action} {type}**? Drawing settles all current entries. Cancelling refunds entry costs.',view=Confirm(i.user.id,accept))
 @admin.command(name='daily_settings',description='Owner sets daily ticket amount, reset schedule and claim method')
 async def daily_settings(i:discord.Interaction,amount:app_commands.Range[int,1,1000000],reset:Literal['midnight','24h']='midnight',method:Literal['button','command','both']='both',timezone:str='America/New_York'):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);c['daily']={'amount':amount,'reset':reset,'method':method};c['timezone']=timezone;bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Daily claim rules saved. Re-post/update the daily panel to refresh its description.')
 @admin.command(name='participation',description='Owner allows everyone or only verified KAOS-linked players')
 async def participation(i:discord.Interaction,allow_unlinked:bool,linked_role:Optional[discord.Role]=None):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);c['allow_unlinked']=allow_unlinked
  if linked_role:c['linked_role']=linked_role.id
  bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Participation saved. In-game prizes always wait for a verified KAOS link before posting to Transactions.')
 @admin.command(name='currency',description='Owner renames tickets and controls player-to-player transfers')
 async def currency(i:discord.Interaction,name:str,allow_transfers:bool=True):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);c.update(currency=name,transfers_enabled=allow_transfers);bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Ticket name and transfer setting saved. Update the daily panel to refresh its text.')
 @admin.command(name='game_settings',description='Owner sets a game’s ticket costs, initial prize odds and availability')
 async def game_settings(i:discord.Interaction,game:GameName,level:Level,cost:app_commands.Range[int,1,1000000],base_odds:app_commands.Range[int,0,100],elite_odds:app_commands.Range[int,0,100],premium_odds:app_commands.Range[int,0,100],enabled:bool=True):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);g=c['games'][game];g['costs'][level]=cost;g['odds'][level]=[base_odds,elite_odds,premium_odds];g['enabled']=enabled;bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Game settings saved. Odds must total 100 and higher-priced levels must not have worse initial tier odds. RPS uses the selected level directly; its bot choices always have equal odds.')
 @admin.command(name='prize',description='Owner configures tier points or adds/removes weighted kit/item alternatives')
 async def prize(i:discord.Interaction,action:Literal['add','remove','points','list'],tier:Level,kind:Literal['kit','item']='kit',name:str='',quantity:app_commands.Range[int,1,1000000]=1,weight:app_commands.Range[int,1,1000000]=1,option_number:Optional[int]=None):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);p=c['prizes'][tier]
  if action=='list':await reply(i,'Prize alternatives are numbered from 1.',file=file_json(tier+'-prizes.json',p));return
  if action=='points':p['points']['amount']=quantity
  elif action=='add':
   from configuration import safe_name
   safe_name(name);p['kits'].append({'weight':weight,'rewards':[{'kind':kind,'name':name,'quantity':quantity}]})
  else:
   if option_number is None or not 1<=option_number<=len(p['kits']):raise ValueError('Choose an existing option_number from prize list.')
   p['kits'].pop(option_number-1)
  bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Prize settings saved. Different alternatives are randomly selected by relative weight. Use the configuration editor for a bundle containing several rewards.')
 @admin.command(name='reward_settings',description='Owner selects kits, KAOS points or player choice and its timing')
 async def reward_settings(i:discord.Interaction,availability:Literal['kits','points','both'],choice_timing:Literal['entry','after']='entry'):
  guard(i,owner=True);c=bot.store.cfg(i.guild_id);c.update(reward_mode=availability,choice_timing=choice_timing);bot.store.save(i.guild_id,c,i.user.id);await reply(i,'Reward availability and choice timing saved.')
 @admin.command(name='help',description='Owner setup steps, command guide and configuration reference')
 async def admin_help(i:discord.Interaction):
  guard(i);await reply(i,'Owner guide and all settings are included below.',file=discord.File(ROOT/'OWNER_GUIDE.md'))
 @admin.command(name='report',description='Download community rewards, open events and recent ticket audit')
 async def report(i:discord.Interaction):
  guard(i);data={}
  for table in ('rewards','ledger','audit','draws'):
   cols='id,uid,tier,kind,payload,status,channel,message,detail,created'if table=='rewards'else '*';data[table]=[dict(x)for x in bot.store.db.execute(f'SELECT {cols} FROM {table} WHERE guild=? ORDER BY '+('created DESC')+' LIMIT 2000',(i.guild_id,))]
  await reply(i,'Community report. Sent means posted to KAOS, not confirmed in-game.',file=file_json('games-report.json',data))
 @admin.command(name='test',description='Owner previews and confirms one real tier prize without spending tickets')
 async def test(i:discord.Interaction,player:discord.Member,tier:Level,reward:Kind='points'):
  c=guard(i,owner=True)
  if player.bot:raise ValueError('Choose a person.')
  async def accept(j):
   guard(j,owner=True)
   if not bot.store.linked(j.guild_id,player.id,[x.id for x in player.roles]):raise ValueError('Verify the player’s KAOS link first.')
   if not c['transactions_channel']or not c['kaos_bot_id']:raise ValueError('Run setup first.')
   with bot.store.atomic():bot.engine.award(j.guild_id,player.id,tier,c,reward,'test:'+str(j.id));bot.store.audit(j.guild_id,j.user.id,'live_reward_test',f'{player.id} {tier} {reward}')
   await j.response.edit_message(content='Real test reward queued. Enable delivery to send it; inspect /gamesadmin report and the player’s bank/balance.',view=None)
  await reply(i,f'Give a REAL **{tier} {reward}** prize to **{player.display_name}** on KAOS server **{c["server_id"]}**? No tickets charged.\nPrize settings: '+json.dumps(c['prizes'][tier])[:1200],view=Confirm(i.user.id,accept))
 @admin.command(name='delivery',description='Owner inspects or resolves a specific reward after checking KAOS Transactions')
 async def delivery(i:discord.Interaction,reward_id:str,action:Literal['inspect','reconcile','retry','mark_sent']='inspect'):
  guard(i,owner=True);r=bot.store.db.execute('SELECT * FROM rewards WHERE guild=? AND id=?',(i.guild_id,reward_id)).fetchone()
  if not r:raise ValueError('Unknown reward ID.')
  if action=='inspect':await reply(i,json.dumps({k:r[k]for k in ('id','uid','status','payload','channel','message','detail')})[:1900]);return
  if action=='reconcile':
   await i.response.defer(ephemeral=True);found=await bot.delivery.reconcile(i.guild,reward_id);await reply(i,'Original parser post found; marked sent.'if found else 'Not found in the last 1,000 messages. This does not prove it was never sent; inspect older history before retrying.');return
  async def accept(j):
   guard(j,owner=True);latest=bot.store.db.execute('SELECT status FROM rewards WHERE id=?',(reward_id,)).fetchone()[0]
   if action=='retry':
    if latest not in ('failed','uncertain'):raise ValueError('Only failed/uncertain sends can be retried. Sent rewards are never replayed automatically.')
    bot.store.db.execute('UPDATE rewards SET status="pending",detail="Owner approved retry after review" WHERE id=?',(reward_id,))
   else:
    if latest not in ('uncertain','failed'):raise ValueError('Only uncertain or failed sends can be manually marked sent.')
    bot.store.db.execute('UPDATE rewards SET status="sent",detail="Owner marked sent after review" WHERE id=?',(reward_id,))
   bot.store.audit(j.guild_id,j.user.id,'delivery_'+action,reward_id);await j.response.edit_message(content='Delivery state updated.',view=None)
  await reply(i,'Confirm '+action+'? Inspect the Transactions channel AND KAOS result first. Retrying a command KAOS already processed can duplicate the reward.',view=Confirm(i.user.id,accept))
 bot.tree.add_command(admin);bot.tree.add_command(lottery)
 @bot.tree.error
 async def error(i,exc):
  original=getattr(exc,'original',exc)
  if isinstance(original,(ValueError,KeyError,TypeError)):await reply(i,str(original))
  else:log.error('Command failed',exc_info=(type(exc),exc,exc.__traceback__));await reply(i,'Could not complete that action. Check /history or /resume before repeating it.')
 return bot

def main():
 logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
 token=os.getenv('DISCORD_BOT_TOKEN')
 if not token:raise SystemExit('Set DISCORD_BOT_TOKEN in Railway Variables. Never place it in source files.')
 attach_commands(GamesBot()).run(token,log_handler=None)
if __name__=='__main__':main()
