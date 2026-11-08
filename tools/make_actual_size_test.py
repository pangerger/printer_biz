"""Create a one-page original-size/edge calibration sheet; no print submission."""
from pathlib import Path
import json
import subprocess
import sys

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import bizhub
from test_native import first_page_pixels

folder=bizhub.external_directory()/'actual-size-0.3.1'
folder.mkdir(exist_ok=True)
pdf=folder/'actual-size-calibration.pdf'
mm=72/25.4
w,h=210*mm,297*mm
pdfmetrics.registerFont(TTFont('Heiti','/System/Library/Fonts/STHeiti Light.ttc',subfontIndex=0))
c=canvas.Canvas(str(pdf),pagesize=(w,h))
c.setTitle('bizhub 185 0.3.1 - Original Size Calibration')
c.setFont('Heiti',18);c.drawString(20*mm,274*mm,'原尺寸打印校准  0.3.1')
c.setFont('Heiti',10)
c.drawString(20*mm,262*mm,'请用尺量下方横线：应为 100 毫米（10 厘米）。')
c.drawString(20*mm,254*mm,'本页用于检查缩放和机器实际能打印到的纸边位置。')
c.drawString(20*mm,240*mm,'保留文字 B、灰度 D；A4 / 600 dpi')

# Exact 100 mm ruler, away from the physical paper edges.
c.setLineWidth(0.25*mm)
c.line(20*mm,200*mm,120*mm,200*mm)
for i in range(101):
    length=4 if i%10==0 else 2 if i%5==0 else 1
    x=(20+i)*mm
    c.line(x,200*mm,x,(200+length)*mm)
    if i%10==0:
        c.setFont('Helvetica',8);c.drawCentredString(x,194*mm,str(i))
c.setFont('Heiti',12);c.drawString(44*mm,213*mm,'横线长度：100.00 mm')

# A vertical 100 mm reference checks scale on the other axis.
c.line(35*mm,65*mm,35*mm,165*mm)
for i in range(0,101,10):
    y=(65+i)*mm;c.line(31*mm,y,35*mm,y)
    c.setFont('Helvetica',8);c.drawRightString(29*mm,y-2,str(i))
c.setFont('Heiti',10);c.drawString(42*mm,112*mm,'竖线同样为 100 mm')

# Each short vertical mark has a known center distance from the sheet edge.
# Labels remain well inside the sheet, even if the engine clips a mark.
distances=[0.5,1,2,3,4,5,8]
c.setFont('Heiti',10);c.drawString(135*mm,175*mm,'右侧边缘标记（距纸边）')
for i,distance in enumerate(distances):
    y=(163-i*10)*mm
    c.setFont('Heiti',10);c.drawString(145*mm,y,f'{distance:g} mm')
    x=(210-distance)*mm
    c.setLineWidth(0.3*mm);c.line(x,y-1*mm,x,y+2*mm)
    x=distance*mm;c.line(x,y-1*mm,x,y+2*mm)

c.setFont('Heiti',10)
c.drawString(20*mm,44*mm,'检查：横线 10 厘米；右边最靠边的哪一条标记能看到？')
c.drawString(20*mm,35*mm,'标记可能被机器纸路边缘截掉；这与自动缩小是两回事。')
c.drawString(20*mm,26*mm,'请保持 A4、原尺寸；不要选择适合纸张或自定义缩放。')
c.showPage();c.save()

result=subprocess.run([str(ROOT/'build/bizhub185-filter'),'1','test','actual size','1',
    'PageSize=A4 Rendering=Text print-scaling=none',str(pdf)],capture_output=True,check=True,timeout=30)
bits=np.unpackbits(np.frombuffer(first_page_pixels(result.stdout),dtype=np.uint8).reshape(7015,620),axis=1)
y=round(7016-200*600/25.4)
row=bits[y,round(15*600/25.4):round(125*600/25.4)]
xs=np.flatnonzero(row)
length_mm=(int(xs[-1])-int(xs[0])+1)*25.4/600
assert abs(length_mm-100)<0.1,length_mm
proof={'version':'0.3.1','ruler_raster_length_mm':length_mm,
    'raster_geometry':[4960,7015],'pdf':str(pdf),'physical_print_submitted':False}
(folder/'calibration-verification.json').write_text(json.dumps(proof,indent=2))
print(json.dumps(proof,indent=2))
