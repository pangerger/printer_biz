"""Verify the installed 0.2 driver preserves all four pre-halftoned panels."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import numpy as np
from PIL import Image
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bizhub

folder=bizhub.external_directory()/'quality-comparison'
pdf=folder/'bizhub185-quality-comparison.pdf'
manifest=json.loads((folder/'manifest.json').read_text())
reader=PdfReader(pdf)
assert len(reader.pages)==1 and not reader.is_encrypted
text=reader.pages[0].extract_text()
for label in ['当前文字','文字加深候选','当前灰度','新灰度候选']:
    assert label in text,label
binary=Path('/Library/Printers/bizhub185/bizhub185-filter')
digest=hashlib.sha256(binary.read_bytes()).hexdigest()
encoded=subprocess.run([str(binary),'1','test','quality proof','1',
    'PageSize=A4 Rendering=Text orientation-requested=3',str(pdf)],capture_output=True,check=True,timeout=60).stdout
offset=encoded.index(b'@PJL SET IMAGELEN=');chunks=[]
while encoded[offset:].startswith(b'@PJL SET IMAGELEN='):
    end=encoded.index(b'\r\n',offset)
    length=int(encoded[offset:end].split(b'=')[1]);offset=end+2
    chunks.append(encoded[offset:offset+length]);offset+=length
assert encoded[offset:].startswith(b'@PJL SET PAGESTATUS=END\r\n')
pbm=subprocess.run([str(ROOT/'build/decode-jbig')],input=b''.join(chunks),capture_output=True,check=True).stdout
magic,dims,pixels=pbm.split(b'\n',2)
assert magic==b'P4' and dims==b'4960 7015' and len(pixels)==620*7015
raster=np.unpackbits(np.frombuffer(pixels,dtype=np.uint8),bitorder='big').reshape(7015,4960).astype(bool)
checks=[]
w,h=manifest['dimensions']
for variant in manifest['variants']:
    reference=~np.asarray(Image.open(variant['pbm']),dtype=bool)
    x,y=variant['x_px'],variant['top_px']
    matches=[]
    for dy in range(-2,3):
        for dx in range(-1,2):
            mismatch=int(np.count_nonzero(raster[y+dy:y+dy+h,x+dx:x+dx+w] != reference))
            matches.append((mismatch,dx,dy))
    mismatch,dx,dy=min(matches)
    checks.append({'label':variant['label'],'different_pixels':mismatch,'offset_px':[dx,dy]})
    assert mismatch==0,checks[-1]
manifest.update(pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),installed_filter_sha256=digest,
    verified_one_page=True,pixel_preservation=checks,printer_data_bytes=len(encoded))
(folder/'verified-test.prn').write_bytes(encoded)
(folder/'verification.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({'panels':checks,'printer_data_bytes':len(encoded)},ensure_ascii=False,indent=2))
