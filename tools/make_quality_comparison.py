"""One-sheet quality comparison, keeping the installed driver unchanged."""
from pathlib import Path
import io
import json
import subprocess
import sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bizhub

folder=bizhub.external_directory()/'quality-comparison'
folder.mkdir(exist_ok=True)
pdf=folder/'bizhub185-quality-comparison.pdf'
if pdf.exists() and '--replace' not in sys.argv:raise RuntimeError('Comparison already exists; use --replace for this generated test page.')
font_path='/System/Library/Fonts/STHeiti Light.ttc'
pdfmetrics.registerFont(TTFont('Heiti',font_path,subfontIndex=0))
W,H=2100,2250
sample=Image.new('L',(W,H),255)
draw=ImageDraw.Draw(sample)
for i,size in enumerate([7,8,9,10,11,12]):
    font=ImageFont.truetype(font_path,round(size*600/72))
    y=[20,190,360,530,680,830][i]
    draw.text((25,y),f'{size}pt  清晰打印 细线灰阶 0123456789',font=font,fill=0)
    if size<=9:
        draw.text((25,y+75),'AaBb  Il1  O0  rn m  1234567890',font=font,fill=0)
font=ImageFont.truetype(font_path,round(9*600/72))
draw.text((25,1050),'浅灰文字  灰度 145',font=font,fill=145)
draw.text((25,1160),'浅灰文字  灰度 190',font=font,fill=190)
for i,width in enumerate([1,2,3,5]):
    y=1300+i*65
    draw.text((25,y-20),f'{width} px',font=ImageFont.truetype(font_path,40),fill=0)
    draw.line((250,y,2000,y),fill=0,width=width)
gradient=np.tile(np.linspace(0,255,2000,dtype=np.uint8),(240,1))
sample.paste(Image.fromarray(gradient),(25,1600))
for i in range(11):
    x=25+i*180
    draw.rectangle((x,1910,x+179,2100),fill=round(i*255/10))
    draw.text((x+30,2140),f'{100-i*10}%',font=ImageFont.truetype(font_path,45),fill=0)
sample.save(folder/'source-gray.png')

variants=[('A','当前文字','text','现有文字模式，用作基准'),
          ('B','文字加深候选','strong','保留更多浅色边缘，可能略显粗'),
          ('C','当前灰度','ordered','现有 Photo 模式：有序网点'),
          ('D','新灰度候选','diffusion','蛇形误差扩散：比较层次和颗粒')]
page_w,page_h=595.2755905512,841.8897637795
c=canvas.Canvas(str(pdf),pagesize=(page_w,page_h),pageCompression=1)
c.setTitle('bizhub 185 打印效果对比测试')
c.setFont('Heiti',19);c.drawString(24,page_h-38,'bizhub 185 打印效果对比')
c.setFont('Heiti',9);c.drawString(24,page_h-56,'600 dpi 原尺寸 · 只测试效果，未修改已安装驱动')
c.setFont('Heiti',9);c.drawString(24,page_h-72,'文字看 A / B：小字是否清楚且不糊；灰度看 C / D：过渡是否平滑、颗粒是否自然。')
manifest={'dpi':600,'dimensions':[W,H],'variants':[],'installed_driver_changed':False}
for i,(tag,title,mode,caption) in enumerate(variants):
    result=subprocess.run([str(ROOT/'build/quality-halftone'),str(W),str(H),mode],
        input=sample.tobytes(),capture_output=True,check=True)
    pbm=folder/f'{tag}-{mode}.pbm';pbm.write_bytes(result.stdout)
    image=Image.open(io.BytesIO(result.stdout));assert image.mode=='1' and image.size==(W,H)
    png=folder/f'{tag}-{mode}.png';image.save(png)
    col,row=i%2,i//2
    x=28.8+col*283.2;top=950+row*2950
    y=page_h-(top+H)*0.12
    c.setLineWidth(0.5);c.setStrokeGray(0.6)
    c.rect(x-5,y-8,W*0.12+10,H*0.12+42)
    c.setFillGray(0);c.setFont('Heiti',12);c.drawString(x,page_h-top*0.12+19,f'{tag}  {title}')
    c.setFont('Heiti',8);c.drawString(x,page_h-top*0.12+6,caption)
    c.drawImage(ImageReader(str(png)),x,y,width=W*0.12,height=H*0.12)
    manifest['variants'].append({'label':tag,'mode':mode,'x_px':round(x/0.12),'top_px':top,'pbm':str(pbm)})
c.setFont('Heiti',9);c.drawString(24,39,'请按纸面判断：文字选 A 或 B，灰度选 C 或 D。浅灰文字变深也是加深处理的预期变化。')
c.setFont('Heiti',8);c.drawString(24,23,'细线从 1 到 5 像素；每格使用同一份原稿。请保持 A4、100% 缩放、文字模式打印。')
c.showPage();c.save()
(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(pdf)
