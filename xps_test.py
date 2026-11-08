"""Single-page XPS interoperability test. This is not a general PDF driver."""
import io
import json
import os
import shlex
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import bizhub

NS = 'http://schemas.microsoft.com/xps/2005/06'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
BACKEND = '/usr/libexec/cups/backend/usb'


def package():
    # A4 at 96 units/inch. No external fonts or images are required.
    page = ET.Element('FixedPage', {'xmlns': NS, 'Width': '793.700787',
        'Height': '1122.519685', 'xml:lang': 'en-US'})
    shapes = [
        {'Data': 'M 48,48 L 745,48 745,1074 48,1074 Z', 'Stroke': '#FF000000', 'StrokeThickness': '1'},
        {'Data': 'M 96,400 L 473.952756,400 M 96,390 L 96,410 M 473.952756,390 L 473.952756,410',
         'Stroke': '#FF000000', 'StrokeThickness': '2'},
        {'Data': 'M 96,480 L 133.795276,480 133.795276,517.795276 96,517.795276 Z', 'Fill': '#FF000000'},
    ]
    # Large seven-segment "185" identifies this synthetic page unambiguously.
    segments = {'a': (0,0,48,0), 'b': (48,0,48,72), 'c': (48,72,48,144),
                'd': (0,144,48,144), 'e': (0,72,0,144), 'f': (0,0,0,72), 'g': (0,72,48,72)}
    for offset, keys in zip((0, 90, 180), ('bc', 'abcdefg', 'afgcd')):
        for key in keys:
            x1, y1, x2, y2 = segments[key]
            shapes.append({'Data': f'M {96+offset+x1},{144+y1} L {96+offset+x2},{144+y2}',
                           'Stroke': '#FF000000', 'StrokeThickness': '6'})
    for attrs in shapes: ET.SubElement(page, 'Path', attrs)
    parts = {
        '[Content_Types].xml': '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="fdseq" ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml"/>
<Default Extension="fdoc" ContentType="application/vnd.ms-package.xps-fixeddocument+xml"/>
<Default Extension="fpage" ContentType="application/vnd.ms-package.xps-fixedpage+xml"/></Types>'''.encode(),
        '_rels/.rels': f'<Relationships xmlns="{REL}"><Relationship Id="R1" Type="{NS}/fixedrepresentation" Target="/FixedDocSeq.fdseq"/></Relationships>'.encode(),
        'FixedDocSeq.fdseq': f'<FixedDocumentSequence xmlns="{NS}"><DocumentReference Source="/Documents/1/FixedDoc.fdoc"/></FixedDocumentSequence>'.encode(),
        'Documents/1/FixedDoc.fdoc': f'<FixedDocument xmlns="{NS}"><PageContent Source="/Documents/1/Pages/1.fpage" Width="793.700787" Height="1122.519685"/></FixedDocument>'.encode(),
        'Documents/1/Pages/1.fpage': ET.tostring(page, encoding='utf-8', xml_declaration=True),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=False) as archive:
        for name, data in parts.items():
            ET.fromstring(data)
            info = zipfile.ZipInfo(name, (2026, 11, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def current_device():
    output = bizhub.command([BACKEND], timeout=10).decode('utf-8', 'replace')
    matches = []
    for line in output.splitlines():
        fields = shlex.split(line)
        if len(fields) < 5: continue
        deviceid = dict(p.split(':', 1) for p in fields[4].split(';') if ':' in p)
        if (fields[0] == 'direct' and fields[1].startswith('usb://KONICA%20MINOLTA/185?')
                and deviceid.get('MFG') == 'KONICA MINOLTA' and deviceid.get('MDL') == '185'
                and 'XPS' in deviceid.get('CMD', '').split(',')):
            matches.append(fields[1])
    if len(matches) != 1:
        raise RuntimeError('Exactly one USB bizhub 185 advertising XPS is required.')
    return matches[0]


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send-once', action='store_true', help='send one synthetic XPS page over USB')
    args = parser.parse_args()
    folder = bizhub.external_directory()
    data = package()
    target = folder / 'xps-test-185.xps'
    if target.exists():
        if target.read_bytes() != data: raise RuntimeError('Existing test file differs; refusing overwrite.')
    else:
        with target.open('xb') as output: output.write(data)
    print(f'Generated: {target}')
    if not args.send_once: return
    uri = current_device()
    # An exclusive persistent marker prevents automatic duplicate jobs, including after timeout.
    record = folder / 'xps-test-send.json'
    state = {'status': 'started', 'file': str(target), 'physical_print_verified': False,
             'sha256': bizhub.hashlib.sha256(data).hexdigest()}
    with record.open('x') as output: json.dump(state, output, indent=2)
    try:
        proc = subprocess.run([BACKEND, '1', 'michael', 'bizhub185 XPS test', '1', '', str(target)],
            env={**os.environ, 'DEVICE_URI': uri}, capture_output=True, timeout=35)
        state.update(status='backend-completed' if proc.returncode == 0 else 'backend-failed', returncode=proc.returncode,
                     log=proc.stderr.decode('utf-8', 'replace'))
    except subprocess.TimeoutExpired:
        state.update(status='timeout-delivery-unknown', log='No automatic retry. Inspect physical printer.')
    except BaseException:
        state.update(status='interrupted-delivery-unknown')
        raise
    finally:
        # The URI may contain a serial number; do not persist it in the research report.
        state['log'] = state.get('log', '').replace(uri, 'usb://KONICA-MINOLTA/185[redacted]')
        record.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps(state, ensure_ascii=False, indent=2))
    print('USB transfer completion alone does not establish that a page printed.')


if __name__ == '__main__': main()
