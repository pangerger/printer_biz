"""Offline checks; no test in this file submits a physical print job."""
import hashlib
import io
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import bizhub
import gdi
from protocol_oracle import Oracle

POPCOUNT=bytes(bin(n).count('1') for n in range(256))
def black_count(pixels):
    return sum(value*count for value,count in Counter(pixels.translate(POPCOUNT)).items())


def geometry_pdf(width=841.8897637795,height=595.2755905512,rotation=0,stream=None):
    if stream is None:
        stream=f'0 g 24 {height-64} 24 40 re f\n{width-70} 24 40 16 re f\n'.encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Rotate {rotation} /Resources << >> /Contents 4 0 R >>'.encode(),
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    data=bytearray(b'%PDF-1.4\n');offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(data);data.extend(b'xref\n0 5\n0000000000 65535 f \n')
    for offset in offsets:data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(data)


def first_page_pixels(data):
    offset=data.index(b'@PJL SET IMAGELEN=');chunks=[]
    while data[offset:].startswith(b'@PJL SET IMAGELEN='):
        line,end=data[offset:].split(b'\r\n',1)
        length=int(line.split(b'=')[1]);offset+=len(line)+2
        chunks.append(data[offset:offset+length]);offset+=length
    result=subprocess.run([str(ROOT/'build/decode-jbig')],input=b''.join(chunks),capture_output=True,check=True)
    magic,size,pixels=result.stdout.split(b'\n',2)
    assert magic==b'P4' and size==b'4960 7015'
    return pixels


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='native-verification-',dir=bizhub.external_directory())
        cls.path=Path(cls.temp.name)/'test.pdf'
        cls.path.write_bytes(gdi.test_pdf())

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def run_filter(self,data=None,copies='1',options='PageSize=A4 Rendering=Text'):
        cmd=[str(ROOT/'build/bizhub185-filter'),'1','test','test',copies,options]
        if data is None:cmd.append(str(self.path))
        return subprocess.run(cmd,input=data,capture_output=True,timeout=30)

    def test_printed_bytes_and_stdin_match(self):
        results=[self.run_filter(),self.run_filter(data=self.path.read_bytes())]
        for result in results:
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(result.stdout.startswith(gdi.UEL+b'@PJL\r\n'))
            self.assertTrue(result.stdout.endswith(b'@PJL EOJ\r\n'+gdi.UEL+b'\r\n'))
        self.assertEqual(results[0].stdout,results[1].stdout)
        self.assertGreater(black_count(first_page_pixels(results[0].stdout)),0)

    def test_invalid_inputs_have_no_output(self):
        cases=[self.run_filter(copies='0'),self.run_filter(copies='1x'),
               self.run_filter(options='PageSize=Letter'),
               self.run_filter(options='Duplex=DuplexNoTumble'),
               self.run_filter(data=b'not a pdf')]
        for result in cases:
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(result.stdout,b'')

    def test_photo_tone_lightens_shadows_and_midgray_and_preserves_endpoints(self):
        patches=(b'0 g 72 600 96 96 re f\n0.5019608 g 216 600 96 96 re f\n'
                 b'1 g 360 600 96 96 re f\n0.0784314 g 504 600 64 96 re f\n')
        pdf=geometry_pdf(595.2755905512,841.8897637795,stream=patches)
        for mode,midtone,shadow in [('Photo',166,112),('PhotoNatural',161,100),('Auto',161,100)]:
            with self.subTest(mode=mode):
                result=self.run_filter(data=pdf,options=f'PageSize=A4 Rendering={mode}')
                self.assertEqual(result.returncode,0,result.stderr)
                pixels=first_page_pixels(result.stdout)
                coverage=[]
                for x in (800,2000,3200,4400):
                    start=x//8
                    patch=b''.join(pixels[y*620+start:y*620+start+32] for y in range(1300,1450))
                    coverage.append(black_count(patch)/(len(patch)*8))
                self.assertEqual(coverage[0],1.0)
                self.assertAlmostEqual(coverage[1],(255-midtone)/255,delta=0.01)
                self.assertEqual(coverage[2],0.0)
                self.assertAlmostEqual(coverage[3],(255-shadow)/255,delta=0.01)

    def test_auto_defaults_to_text_on_sparse_black_content(self):
        explicit=self.run_filter()
        automatic=self.run_filter(options='PageSize=A4')
        self.assertEqual(automatic.returncode,0,automatic.stderr)
        self.assertEqual(explicit.returncode,0,explicit.stderr)
        self.assertEqual(automatic.stdout,explicit.stdout)

    def test_auto_recognizes_picture_and_separates_close_color_tones(self):
        stream=(b'0.75 0.2 0.22 rg 72 600 96 96 re f\n0.13 0.475 0.18 rg 216 600 96 96 re f\n'
                b'0.35 0.28 0.74 rg 360 600 96 96 re f\n0.15 0.38 0.44 rg 504 600 64 96 re f\n')
        pdf=geometry_pdf(595.2755905512,841.8897637795,stream=stream)
        outputs={}
        for mode in ('PhotoNatural','PhotoDefault','Auto'):
            result=self.run_filter(data=pdf,options=f'PageSize=A4 Rendering={mode}')
            self.assertEqual(result.returncode,0,result.stderr)
            outputs[mode]=first_page_pixels(result.stdout)

        def coverage(pixels,x):
            patch=b''.join(pixels[y*620+x:y*620+x+32] for y in range(1300,1450))
            return black_count(patch)/(len(patch)*8)

        self.assertEqual(outputs['Auto'],outputs['PhotoDefault'])
        for left,right,gap in ((100,250,0.12),(400,550,0.08)):
            self.assertLess(abs(coverage(outputs['PhotoNatural'],left)-coverage(outputs['PhotoNatural'],right)),0.02)
            self.assertGreater(abs(coverage(outputs['Auto'],left)-coverage(outputs['Auto'],right)),gap)
        self.assertLess(coverage(outputs['Auto'],400),0.52)
        self.assertLess(coverage(outputs['Auto'],550),0.61)

    def test_two_page_job(self):
        stream=b'0 g 72 700 20 20 re f\n'
        objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>']
        for _ in range(2):objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.2755905512 841.8897637795] /Resources << >> /Contents 5 0 R >>')
        objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream')
        data=bytearray(b'%PDF-1.4\n');offsets=[]
        for i,obj in enumerate(objects,1):
            offsets.append(len(data));data.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
        xref=len(data);data.extend(b'xref\n0 6\n0000000000 65535 f \n')
        for offset in offsets:data.extend(f'{offset:010d} 00000 n \n'.encode())
        data.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
        result=self.run_filter(data=bytes(data))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.count(b'@PJL SET PAGESTATUS=START\r\n'),2)
        self.assertEqual(result.stdout.count(b'@PJL SET PAGESTATUS=END\r\n'),2)
        self.assertTrue(result.stdout.endswith(b'@PJL EOJ\r\n'+gdi.UEL+b'\r\n'))

    def test_official_codec_matches_native(self):
        rng=random.Random(185)
        for width,height in [(64,32),(129,65),(256,128)]:
            stride=(width+7)//8
            pixels=bytearray(rng.randrange(256) for _ in range(stride*height))
            if width%8:
                for y in range(height):pixels[y*stride+stride-1]&=(255<<(8-width%8))&255
            reference=Oracle().compressed(width,height,bytes(pixels)).split(b'\r\n',1)[1]
            native=subprocess.run([str(ROOT/'build/pbm-jbig')],
                input=f'P4\n{width} {height}\n'.encode()+pixels,capture_output=True,check=True).stdout
            self.assertEqual(native,reference)

    def test_official_a4_page_header(self):
        self.assertEqual(gdi.page_header(),(bizhub.ARTIFACTS/'oracle-page-header-a4.bin').read_bytes())

    def test_landscape_pdf_and_rotated_portrait_pdf(self):
        # Native landscape dimensions and PDF /Rotate must both be accepted.
        for content in [geometry_pdf(),geometry_pdf(595.2755905512,841.8897637795,90),
                        geometry_pdf(595.2755905512,841.8897637795,270)]:
            result=self.run_filter(data=content)
            self.assertEqual(result.returncode,0,result.stderr)
            pixels=first_page_pixels(result.stdout)
            # Two dissimilar rectangles survive rotation without clipping.
            count=black_count(pixels)
            self.assertGreater(count,108000)
            self.assertLess(count,114000)

    def test_landscape_is_not_rotated_twice_by_job_option(self):
        content=geometry_pdf()
        auto=self.run_filter(data=content)
        explicit=self.run_filter(data=content,options='PageSize=A4 orientation-requested=4')
        legacy=self.run_filter(data=content,options='PageSize=A4 landscape=true')
        self.assertEqual(auto.returncode,0,auto.stderr)
        self.assertEqual(explicit.stdout,auto.stdout)
        self.assertEqual(legacy.stdout,auto.stdout)

    def test_landscape_marker_geometry_and_reverse_direction(self):
        results=[self.run_filter(data=geometry_pdf(),options=f'PageSize=A4 orientation-requested={n}') for n in (4,5)]
        for result in results:self.assertEqual(result.returncode,0,result.stderr)
        images=[first_page_pixels(r.stdout) for r in results]
        self.assertNotEqual(images[0],images[1])
        def black(pixels,x,y):return bool(pixels[y*620+x//8]&(128>>(x%8)))
        # Rotate=90 maps the top-left tall rectangle to a wide rectangle
        # at the top right of the physical portrait raster.
        self.assertTrue(black(images[0],4600,300))
        self.assertFalse(black(images[0],4600,600))
        self.assertTrue(black(images[1],350,6700))
        self.assertFalse(black(images[1],350,6400))

    def test_explicit_landscape_on_portrait_page(self):
        data=geometry_pdf(595.2755905512,841.8897637795)
        normal=self.run_filter(data=data)
        landscape=self.run_filter(data=data,options='PageSize=A4 orientation-requested=4')
        self.assertEqual(landscape.returncode,0,landscape.stderr)
        self.assertNotEqual(normal.stdout,landscape.stdout)
        self.assertGreater(black_count(first_page_pixels(landscape.stdout)),50000)


if __name__=='__main__':unittest.main()
