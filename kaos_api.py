"""Community-scoped KAOS kapi_minor client. No parser writes or API response logging."""
import asyncio,hashlib,json,math,os,time
from collections import defaultdict,deque
import aiohttp
from cryptography.fernet import Fernet,InvalidToken
BASE='https://minor.ka0s.uk'
TTL=900
class APIError(ValueError):
 def __init__(self,message,retryable=False,delay=60):super().__init__(message);self.retryable=retryable;self.delay=max(1,min(delay,3600))

def parse_link(payload,uid):
 if not isinstance(payload,dict):return None
 if payload.get('linked')is False or payload.get('found')is False:return False
 for key in ('uid','discord_id','discord_user_id'):
  value=payload.get(key)
  if value is not None:
   if str(value)!=str(uid):return None
   if type(value)in (str,int)and str(value).isdecimal()and 0<int(value)<2**64:return True
 if payload.get('linked')is True:return True
 for key in ('data','link','player','result'):
  if isinstance(payload.get(key),dict):
   answer=parse_link(payload[key],uid)
   if answer is not None:return answer
 return None

class KeyVault:
 def __init__(self,store):self.s=store
 def cipher(self):
  raw=os.getenv('KAOS_KEY_ENCRYPTION_KEY','')
  if not raw:raise ValueError('Host must set KAOS_KEY_ENCRYPTION_KEY to enable private key entry, or configure a community key in Railway Variables.')
  try:return Fernet(raw.encode())
  except (ValueError,TypeError):raise ValueError('Host encryption key is invalid. Contact the bot host.')from None
 def get(self,guild):
  token=os.getenv(f'KAOS_API_KEY_{guild}','').strip()
  if token:
   if any(ch.isspace()for ch in token):raise ValueError('Invalid host-managed KAOS key configuration.')
   return token
  if os.getenv('KAOS_API_GUILD_ID')==str(guild) and os.getenv('KAOS_API_KEY','').strip():
   token=os.environ['KAOS_API_KEY'].strip()
   if any(ch.isspace()for ch in token):raise ValueError('Invalid host-managed KAOS key configuration.')
   return token
  r=self.s.db.execute('SELECT token FROM api_keys WHERE guild=?',(guild,)).fetchone()
  if not r:return None
  try:
   data=json.loads(self.cipher().decrypt(r[0].encode()).decode())
   if data['guild']!=guild:raise ValueError('Stored community key binding is invalid.')
   return data['key']
  except InvalidToken:raise ValueError('Cannot decrypt this community key. Restore the host encryption key or re-enter the KAOS key.')from None
 def save(self,guild,token,actor):
  if not isinstance(token,str)or not 10<=len(token.strip())<=4096 or any(ch.isspace()for ch in token.strip()):raise ValueError('Enter the KAOS API key only, without Bearer or whitespace.')
  encrypted=self.cipher().encrypt(json.dumps({'guild':guild,'key':token.strip()}).encode()).decode()
  with self.s.atomic():
   self.s.db.execute('INSERT INTO api_keys VALUES(?,?) ON CONFLICT(guild) DO UPDATE SET token=excluded.token',(guild,encrypted));self.s.db.execute('DELETE FROM api_links WHERE guild=?',(guild,));self.s.audit(guild,actor,'api_key_updated','Community key replaced; secret not recorded')
 def delete(self,guild,actor):
  with self.s.atomic():
   self.s.db.execute('DELETE FROM api_keys WHERE guild=?',(guild,));self.s.db.execute('DELETE FROM api_links WHERE guild=?',(guild,));self.s.audit(guild,actor,'api_key_removed','Stored key removed')

def reward_request(row):
 p=json.loads(row['payload']);c=json.loads(row['config']);kind=p['kind'];qty=p['quantity']
 if type(qty)is not int or not 1<=qty<=1000000000:raise ValueError('Invalid reward quantity.')
 # Stable across retries, key rotation and restarts; scoped by community and reward row.
 key='games-'+hashlib.sha256(f'{row["guild"]}:{row["id"]}'.encode()).hexdigest()
 body={'uid':str(row['uid']),'idempotency_key':key}
 if kind=='points':route='economy/credit';body['amount']=qty;body['reason']='Games Bot reward'
 elif kind in ('kit','item'):
  from configuration import safe_name
  route='bank/'+kind;body[kind]=safe_name(p['name']);body['quantity']=qty
 else:raise ValueError('Unknown reward kind.')
 return f'/v1/{row["guild"]}/{c["server_id"]}/{route}',body

class KaosAPI:
 def __init__(self,store,session=None):
  self.s=store;self.vault=KeyVault(store);self.session=session;self.owns=session is None;self.limits=defaultdict(deque);self.blocked={};self.lock=asyncio.Lock()
 async def close(self):
  if self.owns and self.session:await self.session.close()
 async def throttle(self,guild,bucket):
  async with self.lock:
   now=time.monotonic();blocked=self.blocked.get(guild,0)-now
   if blocked>0:raise APIError('KAOS rate limit: wait before trying again.',True,blocked)
   q=self.limits[guild,bucket]
   while q and q[0]<=now-60:q.popleft()
   limit={'whoami':5,'lookup':120,'mutation':60}[bucket]
   if len(q)>=limit:raise APIError('KAOS request limit reached; try again shortly.',True,60-(now-q[0]))
   q.append(now)
 async def request(self,guild,method,path,body=None,params=None,token=None):
  token=token or self.vault.get(guild)
  if not token:raise APIError('Add this community’s KAOS API key using /gamesadmin api action:set.',False)
  if not path.startswith(f'/v1/{guild}/'):raise ValueError('API route community mismatch.')
  bucket='mutation'if method=='POST'else 'whoami'if path.endswith('/whoami')else 'lookup'
  await self.throttle(guild,bucket)
  if self.session is None:self.session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
  try:
   async with self.session.request(method,BASE+path,json=body,params=params,headers={'Authorization':'Bearer '+token},allow_redirects=False)as r:
    if r.status==429:
     try:delay=float(r.headers.get('Retry-After','60'));delay=delay if math.isfinite(delay)else 60
     except ValueError:delay=60
     self.blocked[guild]=time.monotonic()+max(1,delay);raise APIError('KAOS rate limited the request.',True,delay)
    if method=='GET'and path.endswith('/whois')and r.status==404:return {'linked':False}
    if r.status>=500:raise APIError('KAOS temporarily unavailable.',True,30)
    if not 200<=r.status<300:raise APIError(f'KAOS HTTP {r.status}: check the community key, permissions, server ID and reward name.',False)
    if method=='POST':return {'accepted':True}
    try:return await r.json()
    except (ValueError,aiohttp.ContentTypeError):raise APIError('KAOS returned an unrecognized response. No link eligibility assumed.',True,60)from None
  except (aiohttp.ClientError,asyncio.TimeoutError):raise APIError('KAOS connection interrupted; retry uses the same reward ID.',True,30)from None
 async def check(self,guild,token=None):
  data=await self.request(guild,'GET',f'/v1/{guild}/whoami',token=token)
  def declared_sid(p):
   if not isinstance(p,dict):return None
   for k in ('sid','guild_id','discord_server_id'):
    if k in p:return str(p[k])
   for k in ('data','result'):
    x=declared_sid(p.get(k))
    if x is not None:return x
   return None
  sid=declared_sid(data)
  if sid is not None and sid!=str(guild):raise APIError('This API key belongs to another Discord community.')
  return True
 async def link(self,guild,uid,force=False):
  if not force:
   r=self.s.db.execute('SELECT status,checked FROM api_links WHERE guild=? AND uid=?',(guild,uid)).fetchone()
   if r and r['status']is not None and time.time()-r['checked']<TTL:return bool(r['status'])
  try:
   data=await self.request(guild,'GET',f'/v1/{guild}/whois',params={'uid':str(uid)});status=parse_link(data,uid)
   if status is None:raise APIError('KAOS link response was not recognized. Ask the host to verify a non-secret response example.',True,60)
  except (APIError,ValueError):
   # Never allow a stale positive result after a failed refresh.
   self.s.cache_api_link(guild,uid,None);raise
  self.s.cache_api_link(guild,uid,status);return status
