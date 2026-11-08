"""Experimental A4/600dpi PDF -> bizhub 185 PJL/JBIG encoder.

Byte-level encoding validated against an emulated official module;
hardware output must be verified before installing a printer queue.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import xml.etree.ElementTree as ET

import bizhub
import xps_test

WIDTH, HEIGHT = 4960, 7015
UEL = b'\x1b%-12345X'


def setting(key, value):
    if not key.isalnum() or any(c in str(value) for c in '\r\n\x1b'):
        raise ValueError('Invalid PJL setting')
    return f'@PJL SET {key}={value}\r\n'.encode('ascii')


def job_header():
    result = UEL+b'@PJL\r\n'
    for key, value in [('DRIVERTYPE','XPS'),('COMPRESS','JBIG'),('USERNAME','Codex'),
                       ('HOLD','OFF'),('COVER','OFF'),('SECTION','OFF')]:
        result += setting(key,value)
    return result


def page_header():
    result = b''
    for key, value in [('PAGESTATUS','START'),('ORIENTATION','PORTRAIT'),('COPIES',1),
                       ('DUPLEX','OFF'),('RESOLUTION',600),('PAPERWIDTH',WIDTH),
                       ('PAPERLENGTH',HEIGHT),('PAPER','A4')]:
        result += setting(key,value)
    return result


def frame_jbig(data):
    if len(data) < 22 or struct.unpack('>II',data[4:12]) != (WIDTH,HEIGHT):
        raise ValueError('Unexpected JBIG dimensions')
    result = bytearray()
    for offset in range(0,len(data),32768):
        chunk=data[offset:offset+32768]
        result.extend(setting('IMAGELEN',len(chunk)))
        result.extend(chunk)
    return bytes(result)


def normalize_raster(pbm):
    magic, dims, pixels = pbm.split(b'\n',2)
    width,height=map(int,dims.split())
    if magic!=b'P4' or width not in (WIDTH,WIDTH+1) or height not in (HEIGHT,HEIGHT+1):
        raise ValueError('This prototype accepts portrait A4 pages only')
    stride=(width+7)//8
    if len(pixels)!=stride*height: raise ValueError('Raster length mismatch')
    # CoreGraphics rounds up page dimensions; the official A4 geometry rounds down.
    # Remove at most one pixel from the far right and bottom; never rescale content.
    pixels=b''.join(pixels[y*stride:y*stride+WIDTH//8] for y in range(HEIGHT))
    return f'P4\n{WIDTH} {HEIGHT}\n'.encode()+pixels


def encode_pdf(pdf):
    pdf=Path(pdf).resolve()
    count=int(bizhub.command([str(bizhub.ROOT/'build/pdf-raster'),str(pdf),'--pages']))
    if not 1 <= count <= 100: raise ValueError('Page count outside 1..100')
    output=bytearray(job_header())
    for page in range(1,count+1):
        raster=bizhub.command([str(bizhub.ROOT/'build/pdf-raster'),str(pdf),str(page),'600','threshold'],timeout=120)
        raster=normalize_raster(raster)
        data=subprocess.run([str(bizhub.ROOT/'build/pbm-jbig')],input=raster,
            capture_output=True,check=True,timeout=120).stdout
        output.extend(setting('MEDIASOURCE','AUTO')+setting('MEDIATYPE','PLAIN'))
        output.extend(page_header()+frame_jbig(data)+setting('PAGESTATUS','END'))
        if len(output)>128*1024*1024: raise ValueError('Encoded job exceeds 128 MiB')
    output.extend(b'@PJL EOJ\r\n'+UEL+b'\r\n')
    return bytes(output)


def test_pdf():
    # Match the vector-only XPS test page using the same paths, without fonts.
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(xps_test.package())) as archive:
        page=ET.fromstring(archive.read('Documents/1/Pages/1.fpage'))
    stream=bytearray(b'q\n0.75 0 0 -0.75 0 841.8897637795 cm\n0 G 0 g\n')
    for shape in page:
        tokens=shape.attrib['Data'].replace(',',' ').split()
        i=0
        while i<len(tokens):
            cmd=tokens[i];i+=1
            if cmd=='Z':stream.extend(b'h\n');continue
            if cmd not in ('M','L'): raise ValueError('Unexpected test path')
            x,y=tokens[i:i+2];i+=2
            stream.extend(f'{x} {y} {"m" if cmd=="M" else "l"}\n'.encode())
            # A Path L command may be followed by multiple coordinate pairs.
            while i<len(tokens) and tokens[i] not in ('M','L','Z'):
                x,y=tokens[i:i+2];i+=2;stream.extend(f'{x} {y} l\n'.encode())
        if 'Fill' in shape.attrib: stream.extend(b'f\n')
        else:stream.extend(f'{shape.attrib["StrokeThickness"]} w S\n'.encode())
    stream.extend(b'Q\n')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.2755905512 841.8897637795] /Resources << >> /Contents 4 0 R >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    result=bytearray(b'%PDF-1.4\n');offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(result));result.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(result);result.extend(b'xref\n0 5\n0000000000 65535 f \n')
    for offset in offsets:result.extend(f'{offset:010d} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(result)


def send_once(path):
    folder=bizhub.external_directory()
    uri=xps_test.current_device()
    marker=folder/'gdi-jbig-test-send.json'
    state={'status':'started','physical_print_verified':False,'file':str(path),
           'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    with marker.open('x') as output:json.dump(state,output,indent=2)
    try:
        proc=subprocess.run([xps_test.BACKEND,'2','michael','bizhub185 JBIG test','1','',str(path)],
            env={**os.environ,'DEVICE_URI':uri},capture_output=True,timeout=35)
        state.update(status='backend-completed' if proc.returncode==0 else 'backend-failed',
            returncode=proc.returncode,log=proc.stderr.decode('utf-8','replace').replace(uri,'usb://185[redacted]'))
    except subprocess.TimeoutExpired:
        state['status']='timeout-delivery-unknown'
    finally:
        marker.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    print(json.dumps(state,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',nargs='?',type=Path,help='A4 PDF; omit to use the synthetic test page')
    parser.add_argument('--send-test-once',action='store_true')
    args=parser.parse_args()
    if args.pdf and args.send_test_once:parser.error('Hardware test sends synthetic content only')
    folder=bizhub.external_directory()
    source=args.pdf
    if source is None:
        source=folder/'gdi-test-185.pdf'
        data=test_pdf()
        if not source.exists():source.write_bytes(data)
        elif source.read_bytes()!=data:raise RuntimeError('Test PDF differs; refusing overwrite')
    data=encode_pdf(source)
    target=folder/'gdi-test-185.prn' if args.pdf is None else folder/(source.stem+'.prn')
    if target.exists() and target.read_bytes()!=data:raise RuntimeError('Existing output differs; refusing overwrite')
    if not target.exists():
        with target.open('xb') as output:output.write(data)
    print(f'Encoded {len(data)} bytes: {target}',flush=True)
    if args.send_test_once:send_once(target)


if __name__=='__main__':main()
