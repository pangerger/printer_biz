import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bizhub
import xps_test


def pdf_bytes(rotation=0, crop='[0 0 72 72]'):
    # Deliberately asymmetric page: 18pt black square at top left.
    stream = b'0 g 0 54 18 18 re f\n'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] '
                f'/CropBox {crop} /Rotate {rotation} /Resources << >> /Contents 4 0 R >>').encode(),
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'endstream']
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(data)
    data.extend(b'xref\n0 5\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return data


class AnalysisTests(unittest.TestCase):
    def test_xps_test_package_references(self):
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(xps_test.package())) as archive:
            self.assertIsNone(archive.testzip())
            rel = ET.fromstring(archive.read('_rels/.rels'))[0]
            sequence = ET.fromstring(archive.read(rel.attrib['Target'].lstrip('/')))
            doc = ET.fromstring(archive.read(sequence[0].attrib['Source'].lstrip('/')))
            page = ET.fromstring(archive.read(doc[0].attrib['Source'].lstrip('/')))
            self.assertEqual(page.tag, '{' + xps_test.NS + '}FixedPage')
            self.assertGreater(len(page), 10)
            self.assertEqual(len(doc), 1)

    def test_zip_does_not_imply_xps_or_device_support(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr('Documents/1/Pages/1.fpage', 'test')
        result = bizhub.inspect_bytes(buf.getvalue())
        self.assertEqual(result['container'], 'xps-candidate')
        self.assertFalse(result['printer_protocol_verified'])

    def test_pjl_and_unknown_data(self):
        result = bizhub.inspect_bytes(b'\x1b%-12345X@PJL ENTER LANGUAGE=GDI\r\n\x00\x01')
        self.assertEqual(result['container'], 'unknown')
        self.assertEqual(result['pjl_markers'], ['@PJL ENTER LANGUAGE=GDI'])

    def test_device_selection_and_no_serial_collection(self):
        tree = [{'USB Product Name': 'USB disk'}, {'IORegistryEntryChildren': [
            {'USB Product Name': 'bizhub 185', 'idVendor': 1, 'idProduct': 2,
             'USB Serial Number': 'private'}]}]
        result = bizhub.usb_devices(tree)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]['model_185_candidate'])
        self.assertNotIn('private', str(result))

    def test_wrong_volume_blocks_before_mkdir(self):
        import plistlib
        with patch.object(bizhub, 'command', return_value=plistlib.dumps({'VolumeUUID': 'wrong'})), \
                patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaises(RuntimeError): bizhub.external_directory()
            mkdir.assert_not_called()

    def test_registry_name_fallback(self):
        result = bizhub.usb_devices({'IORegistryEntryName': 'KONICA MINOLTA 185'})
        self.assertTrue(result[0]['model_185_candidate'])

    def test_probe_requests_registry_properties(self):
        import plistlib
        node = {'USB Product Name': 'KONICA MINOLTA 185', 'idVendor': 4907, 'idProduct': 8423}
        with patch.object(bizhub, 'command', return_value=plistlib.dumps(node)) as run, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(bizhub.probe(), 0)
            self.assertIn('-l', run.call_args[0][0])


class RasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='verification-', dir=bizhub.external_directory())
        cls.folder = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_raster(self, content, page='1', dpi='300', mode='threshold'):
        file = self.folder / 'fixture.pdf'
        file.write_bytes(content)
        return subprocess.run([str(bizhub.ROOT / 'build/pdf-raster'), str(file), page, dpi, mode],
                              capture_output=True, timeout=30)

    def test_orientation_geometry_and_bit_polarity(self):
        result = self.run_raster(pdf_bytes())
        self.assertEqual(result.returncode, 0, result.stderr)
        magic, size, pixels = result.stdout.split(b'\n', 2)
        self.assertEqual((magic, size), (b'P4', b'300 300'))
        self.assertEqual(len(pixels), 38 * 300)
        def black(x, y): return bool(pixels[y * 38 + x//8] & (0x80 >> (x%8)))
        self.assertTrue(black(20, 20))
        self.assertFalse(black(20, 280))
        self.assertFalse(black(280, 20))
        self.assertTrue(all(pixels[y*38+37] & 15 == 0 for y in range(300)))

    def test_rotation(self):
        result = self.run_raster(pdf_bytes(rotation=90))
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels = result.stdout.split(b'\n', 2)[2]
        self.assertTrue(pixels[20*38+280//8] & (0x80 >> (280%8)))
        self.assertFalse(pixels[20*38+20//8] & (0x80 >> (20%8)))

    def test_crop_and_600dpi(self):
        result = self.run_raster(pdf_bytes(crop='[0 0 36 72]'), dpi='600', mode='ordered')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(b'P4\n300 600\n'))

    def test_reject_bad_page_pdf_and_options_without_output(self):
        for content, page, dpi in [(pdf_bytes(), '2', '300'), (b'bad', '1', '300'),
                                  (pdf_bytes(), '1x', '300'), (pdf_bytes(), '1', '999999')]:
            with self.subTest(page=page, dpi=dpi, pdf=content[:8]):
                result = self.run_raster(content, page=page, dpi=dpi)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')


if __name__ == '__main__': unittest.main()
