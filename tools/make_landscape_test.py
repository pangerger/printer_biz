"""Create a synthetic A4 landscape verification page on verified W storage."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'build/vendor')]
import fitz
import bizhub

folder=bizhub.external_directory()
pdf=folder/'landscape-test-185.pdf'
if pdf.exists():raise RuntimeError('Test PDF already exists; refusing overwrite')
doc=fitz.open()
page=doc.new_page(width=841.8897637795,height=595.2755905512)
page.draw_rect(fitz.Rect(24,24,817.8897637795,571.2755905512),color=(0,0,0),width=1)
page.insert_text((45,75),'LANDSCAPE 185',fontsize=28)
page.insert_text((45,103),'A4 landscape | 600 dpi | one sheet',fontsize=13)
page.insert_text((45,135),'TOP LEFT',fontsize=11)
page.draw_rect(fitz.Rect(45,148,65,168),fill=(0,0,0))
page.insert_text((610,520),'BOTTOM RIGHT',fontsize=11)
page.draw_rect(fitz.Rect(610,533,625,548),fill=(0,0,0))
page.draw_rect(fitz.Rect(635,533,650,548),fill=(0,0,0))
page.draw_line(fitz.Point(70,270),fitz.Point(70+100*72/25.4,270),color=(0,0,0),width=1)
page.draw_line(fitz.Point(70,260),fitz.Point(70,280),color=(0,0,0),width=1)
page.draw_line(fitz.Point(70+100*72/25.4,260),fitz.Point(70+100*72/25.4,280),color=(0,0,0),width=1)
page.insert_text((160,300),'100 mm',fontsize=14)
page.insert_text((45,415),'The frame, top-left square, and bottom-right squares should all be visible.',fontsize=13)
page.insert_text((45,440),'Text should read upright when the sheet is held in landscape orientation.',fontsize=13)
doc.save(pdf)
page.get_pixmap().save(folder/'landscape-test-preview.png')
print(pdf)
