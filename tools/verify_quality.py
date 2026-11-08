"""Check experimental halftone candidates without sending printer jobs."""
from pathlib import Path
import subprocess
import sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def raster(gray,mode,w=256,h=128):
    p=subprocess.run([str(ROOT/'build/quality-halftone'),str(w),str(h),mode],input=gray,capture_output=True,check=True)
    magic,dims,bits=p.stdout.split(b'\n',2)
    assert magic==b'P4' and dims==f'{w} {h}'.encode() and len(bits)==((w+7)//8)*h
    return bits

for mode in ['text','strong','ordered','diffusion']:
    assert raster(bytes(256*128),mode)==b'\xff'*(32*128)
    assert raster(b'\xff'*(256*128),mode)==bytes(32*128)
for gray in [32,64,128,192,224]:
    bits=raster(bytes([gray])*(256*128),'diffusion')
    black=sum(bin(k).count('1')*v for k,v in Counter(bits).items())/(256*128)
    assert abs(black-(255-gray)/255)<0.012,(gray,black)
gray=bytes(range(256))*128
a,b=raster(gray,'text'),raster(gray,'strong')
assert all((x & ~y)==0 for x,y in zip(a,b))
assert a!=b
for data,args in [(b'', ['16','16','diffusion']),(b'x',['-1','16','text']),
                  (b'x',['16','16','unknown'])]:
    p=subprocess.run([str(ROOT/'build/quality-halftone'),*args],input=data,capture_output=True)
    assert p.returncode!=0 and p.stdout==b''
print('Halftone checks passed: solid colors, gray coverage, stronger text, malformed input.')
