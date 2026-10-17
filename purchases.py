"""Tip4Serv payment webhook using a secret URL capability; no invented signature format."""
import hmac,json,re,logging
from aiohttp import web
log=logging.getLogger(__name__)
class Purchases:
 def __init__(self,store,engine,secret):
  if len(secret)<32:raise ValueError('TIP4SERV_WEBHOOK_SECRET must contain at least 32 random characters.')
  self.s=store;self.e=engine;self.secret=secret
 async def health(self,request):return web.json_response({'status':'ok'})
 async def receive(self,request):
  if not hmac.compare_digest(request.match_info.get('secret',''),self.secret):raise web.HTTPNotFound()
  try:data=await request.json()
  except (ValueError,UnicodeDecodeError):raise web.HTTPBadRequest(text='Invalid JSON')
  try:result=self.process(data)
  except (ValueError,KeyError,TypeError):raise web.HTTPBadRequest(text='Invalid payment payload or unconfigured purchase')
  return web.json_response(result)
 def process(self,payload):
  if payload.get('event')!='payment.success':return {'status':'ignored','reason':'Only one-time successful payments are credited; review refunds manually.'}
  if payload.get('mode')!='live':return {'status':'ignored','reason':'Test payments do not grant spendable tickets.'}
  data=payload['data']
  if str(data['type'])!='1':return {'status':'ignored','reason':'Subscriptions are not ticket products.'}
  store_id=str(payload['store_id']);matches=[]
  for row in self.s.db.execute('SELECT guild FROM communities'):
   c=self.s.cfg(row[0])
   if str(c.get('purchase_store_id',0))==store_id and c.get('purchase_store_id'):matches.append((row[0],c))
  if len(matches)!=1:raise ValueError('Store must map to exactly one community.')
  guild,c=matches[0];uid=int(data['user']['discord_id'])
  if not 0<uid<2**64:raise ValueError('Discord user ID required.')
  payment=str(data['id'])
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',payment):raise ValueError('Invalid payment ID.')
  counts={}
  for item in data['basket']:
   code=str(item['id'])
   if code not in c['products']:continue
   qty=int(item['quantity'])
   if not 1<=qty<=1000:raise ValueError('Invalid quantity.')
   counts[code]=counts.get(code,0)+qty
  total=0
  with self.s.atomic():
   for code,qty in counts.items():total+=self.e.purchase(guild,uid,code,qty,'store:'+store_id+':payment:'+payment)
  return {'status':'processed','credited':total}
 def app(self):
  app=web.Application(client_max_size=256*1024);app.router.add_get('/health',self.health);app.router.add_post('/tip4serv/{secret}',self.receive);return app
