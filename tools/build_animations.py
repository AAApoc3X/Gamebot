"""Generate original geometric Rock Paper Scissors animations, no external artwork."""
from pathlib import Path
import math
from PIL import Image,ImageDraw,ImageFont
OUT=Path(__file__).resolve().parents[1]/'assets';OUT.mkdir(exist_ok=True)
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
def font(n):
 try:return ImageFont.truetype(FONT,n)
 except OSError:return ImageFont.load_default()
def rock(d,x,y,s=1):
 pts=[(x-42*s,y+22*s),(x-46*s,y-12*s),(x-19*s,y-40*s),(x+22*s,y-35*s),(x+48*s,y-4*s),(x+35*s,y+30*s)]
 d.polygon(pts,fill='#718096',outline='#e2e8f0',width=3);d.line([(x-20*s,y-20*s),(x+6*s,y),(x-10*s,y+20*s)],fill='#a0aec0',width=3)
def paper(d,x,y,s=1):
 d.rounded_rectangle((x-35*s,y-44*s,x+35*s,y+44*s),radius=5,fill='#edf2f7',outline='#9fb7d2',width=3)
 for off in (-20,-5,10,25):d.line((x-23*s,y+off*s,x+23*s,y+off*s),fill='#849bb5',width=2)
def scissors(d,x,y,s=1):
 d.ellipse((x-45*s,y+8*s,x-10*s,y+43*s),outline='#f56565',width=7);d.ellipse((x+5*s,y+8*s,x+40*s,y+43*s),outline='#f56565',width=7)
 d.line((x-18*s,y+12*s,x+38*s,y-42*s),fill='#dce8ef',width=8);d.line((x+15*s,y+12*s,x-38*s,y-42*s),fill='#dce8ef',width=8);d.ellipse((x-5,y-6,x+5,y+4),fill='#4a5568')
ICONS={'rock':rock,'paper':paper,'scissors':scissors}
for winner,loser,title in [('rock','scissors','ROCK SMASHES SCISSORS'),('scissors','paper','SCISSORS CUT PAPER'),('paper','rock','PAPER WRAPS ROCK')]:
 frames=[]
 for frame in range(28):
  im=Image.new('RGB',(640,360),'#0e1724');d=ImageDraw.Draw(im);d.text((320,35),'RUST GAMES',font=font(24),anchor='mm',fill='#e4b86a')
  t=min(1,frame/14);x=150+130*t;other=490-130*t
  if frame<15:ICONS[winner](d,x,170);ICONS[loser](d,other,170)
  else:
   if winner=='rock':
    rock(d,320,170)
    for a in range(8):
     angle=a*math.pi/4;r=50+(frame-15)*5;px=320+math.cos(angle)*r;py=170+math.sin(angle)*r;d.line((px-8,py-7,px+8,py+7),fill='#cad6e2',width=5)
   elif winner=='scissors':
    paper(d,280-(frame-15)*2,170);paper(d,360+(frame-15)*2,170);scissors(d,320,170)
   else:
    rock(d,320,170);d.rounded_rectangle((267,112,373,228),radius=20,outline='#edf2f7',width=min(35,5+(frame-15)*3));d.line((275,150,365,190),fill='#849bb5',width=3)
  d.text((320,295),title,font=font(23),anchor='mm',fill='#f7fafc');frames.append(im)
 frames[0].save(OUT/(winner+'.gif'),save_all=True,append_images=frames[1:],duration=65,loop=0)
frames=[]
for num in (3,2,1):
 im=Image.new('RGB',(640,360),'#0e1724');d=ImageDraw.Draw(im);d.text((320,160),str(num),font=font(120),anchor='mm',fill='#e4b86a');d.text((320,280),'ROCK PAPER SCISSORS',font=font(25),anchor='mm',fill='white');frames.append(im)
frames[0].save(OUT/'countdown.gif',save_all=True,append_images=frames[1:],duration=1000,loop=0)
frames=[]
for n in range(12):
 im=Image.new('RGB',(640,360),'#0e1724');d=ImageDraw.Draw(im);d.text((320,160),'SAME CHOICE',font=font(38),anchor='mm',fill='#edf2f7');d.text((320,285),'DRAW',font=font(35),anchor='mm',fill='#e4b86a');frames.append(im)
frames[0].save(OUT/'draw.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
print('Created five original GIFs')
