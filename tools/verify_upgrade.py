"""Create two install verification pages and compare decoded native B/D output.

Does not submit print jobs. Run with the bundled Python (Pillow/ReportLab/numpy).
The original physical comparison samples remain unchanged.
"""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import sys
import numpy as np
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import bizhub
from test_native import first_page_pixels

base=bizhub.external_directory()
folder=base/'quality-upgrade-0.3.0'
folder.mkdir(exist_ok=True)
source=base/'quality-comparison/source-gray.png'
page_w,page_h=595.2755905512,841.8897637795
records=[]
for mode,reference in [('Text','B-strong'),('Photo','D-diffusion')]:
    pdf=folder/f'verify-{mode.lower()}.pdf'
    c=canvas.Canvas(str(pdf),pagesize=(page_w,page_h),pageCompression=1)
    c.setTitle(f'bizhub 185 v0.3.0 - {mode}')
    c.setFont('Helvetica-Bold',19)
    c.drawString(28.8,page_h-42,f'bizhub 185 v0.3.0 - {mode}')
    c.setFont('Helvetica',11)
    c.drawString(28.8,page_h-64,'B: stronger text' if mode=='Text' else 'D: smoother grayscale')
    c.drawString(28.8,page_h-81,'A4 / 600 dpi / native driver verification')
    # Native CoreGraphics canvas rounds A4 up to 7016 rows. Align the image
    # to that pixel grid to avoid subpixel resampling of the reference gray.
    c.drawImage(ImageReader(str(source)),28.8,(7016-950-2250)*0.12,width=2100*0.12,height=2250*0.12)
    c.setLineWidth(0.5);c.rect(24,24,page_w-48,page_h-48)
    c.showPage();c.save()
    result=subprocess.run([str(ROOT/'build/bizhub185-filter'),'1','test','upgrade','1',
        f'PageSize=A4 Rendering={mode}',str(pdf)],capture_output=True,check=True,timeout=30)
    (folder/f'verify-{mode.lower()}.prn').write_bytes(result.stdout)
    packed=np.frombuffer(first_page_pixels(result.stdout),dtype=np.uint8).reshape(7015,620)
    pixels=np.unpackbits(packed,axis=1)
    actual=pixels[950:3200,240:2340]
    expected=1-np.asarray(Image.open(base/f'quality-comparison/{reference}.png'),dtype=np.uint8)
    # Compare the native algorithm directly to the physically selected sample.
    # Full-page diffusion includes the surrounding header and frame, so its
    # dots can differ from an isolated panel with the same gray input.
    # The PDF roundtrip is also checked for text alignment and coverage.
    native=subprocess.run([str(ROOT/'build/native-halftone'),'2104','2250',mode],
        input=np.pad(np.asarray(Image.open(source)),((0,0),(0,4)),constant_values=255).tobytes(),
        capture_output=True,check=True)
    # Both the reference candidate and native code must use the same canvas.
    reference_mode='strong' if mode=='Text' else 'diffusion'
    oracle=subprocess.run([str(ROOT/'build/quality-halftone'),'2104','2250',reference_mode],
        input=np.pad(np.asarray(Image.open(source)),((0,0),(0,4)),constant_values=255).tobytes(),
        capture_output=True,check=True)
    if native.stdout!=oracle.stdout:raise AssertionError(f'{mode}: native halftone differs from chosen algorithm')
    native_pixels=1-np.asarray(Image.open(io.BytesIO(native.stdout)),dtype=np.uint8)[:,:2100]
    differences=int(np.count_nonzero(native_pixels!=expected))
    # Padding white pixels must not affect the original user-selected sample.
    if differences:raise AssertionError(f'{mode}: {differences} native sample pixels differ')
    pdf_differences=int(np.count_nonzero(actual!=expected))
    if mode=='Text' and pdf_differences:raise AssertionError('Text PDF pixel alignment changed')
    if abs(float(actual.mean())-float(expected.mean()))>0.002:raise AssertionError('PDF gray coverage changed')
    records.append({'mode':mode,'reference':reference,'native_sample_different_pixels':differences,
        'pdf':str(pdf),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
        'printer_data_bytes':len(result.stdout),'pdf_different_dots':pdf_differences,
        'pdf_black_coverage':float(actual.mean()),'sample_black_coverage':float(expected.mean())})
    if differences:raise AssertionError(f'{mode}: {differences} pixels differ from user-selected sample')
proof={'version':'0.3.0','filter_sha256':hashlib.sha256((ROOT/'build/bizhub185-filter').read_bytes()).hexdigest(),
    'comparisons':records,'physical_print_submitted':False}
(folder/'verification.json').write_text(json.dumps(proof,indent=2))
print(json.dumps(proof,indent=2))
