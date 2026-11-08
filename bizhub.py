#!/usr/bin/env python3
"""bizhub 185 protocol research CLI; no unverified print traffic is sent."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
VOLUME = Path('/Volumes/W')
ARTIFACTS = VOLUME / 'Downloads/autoChrome/bizhub185'
VOLUME_UUID = '13A3CA69-E67A-3BA4-BD8B-C87B3036A62C'
DISK_UUID = '89B74195-9CB8-4E57-875A-64B88F461D31'


def command(args, timeout=15):
    return subprocess.run(args, capture_output=True, check=True, timeout=timeout).stdout


def external_directory():
    info = plistlib.loads(command(['diskutil', 'info', '-plist', str(VOLUME)]))
    if (info.get('VolumeUUID') != VOLUME_UUID or info.get('DiskUUID') != DISK_UUID
            or info.get('MountPoint') != str(VOLUME) or info.get('Internal') is not False
            or not info.get('WritableVolume') or not os.path.ismount(VOLUME)):
        raise RuntimeError('W 盘未挂载、身份不符或不可写；已停止，禁止回退到内置磁盘。')
    # Reject symlink redirection outside the verified volume.
    if not ARTIFACTS.resolve().is_relative_to(VOLUME):
        raise RuntimeError('输出路径被重定向到 W 盘以外。')
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS


def walk(nodes):
    if isinstance(nodes, dict):
        nodes = [nodes]
    for node in nodes:
        yield node
        yield from walk(node.get('IORegistryEntryChildren', []))


def usb_devices(tree):
    devices = []
    for node in walk(tree):
        name = str(node.get('USB Product Name', node.get('kUSBProductString', node.get('IORegistryEntryName', ''))))
        vendor = str(node.get('USB Vendor Name', node.get('kUSBVendorString', '')))
        if not re.search(r'bizhub|konica|minolta', name + ' ' + vendor, re.I):
            continue
        devices.append({'product': name, 'manufacturer': vendor,
                        'vendor_id': node.get('idVendor'), 'product_id': node.get('idProduct'),
                        'location_id': node.get('locationID'),
                        'model_185_candidate': bool(re.search(r'\b185\b', name))})
    return devices


def probe():
    tree = plistlib.loads(command(['ioreg', '-p', 'IOUSB', '-l', '-a']))
    devices = usb_devices(tree)
    result = {'system': platform.platform(), 'architecture': platform.machine(),
              'usb_devices': devices, 'protocol_verified': False,
              'message': '已找到候选设备，仍需核对机身型号与打印样本。' if devices else
                         '未检测到柯尼卡美能达 USB 设备。请给打印机通电并连接 USB 数据线。'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if devices else 3


def status():
    binary = ROOT / 'build/usb-status'
    if not binary.is_file():
        raise RuntimeError('请先运行 make 编译 USB 状态工具。')
    report = json.loads(command([str(binary)], timeout=10))
    report['warning'] = '这是 USB 类协议的原始状态；本机曾报告缺纸但面板正常，不可单独据此判断缺纸。'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def inspect_bytes(data):
    """Identify containers/markers, never infer a printer protocol from a name."""
    result = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'prefix_hex': data[:64].hex(' '), 'container': 'unknown',
              'printer_protocol_verified': False}
    if data.startswith(b'%PDF-'):
        result['container'] = 'pdf'
    elif zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            # Inspect names only: do not decompress untrusted archives.
            result['container'] = 'xps-candidate' if any(
                n.lower().endswith(('.fpage', '.fdseq')) for n in names) else 'zip'
            result['members'] = names[:100]
    markers = re.findall(rb'@PJL[^\r\n\x00]{0,240}', data[:65536])
    result['pjl_markers'] = [m.decode('ascii', 'backslashreplace') for m in markers[:32]]
    return result


def inspect(path):
    # Bound memory consumption when accepting externally supplied spool files.
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('样本超过 256 MiB；请采集一页测试稿。')
    print(json.dumps(inspect_bytes(path.read_bytes()), ensure_ascii=False, indent=2))
    return 0


def render(args):
    target = external_directory() / args.name
    if Path(args.name).name != args.name or not args.name.endswith('.pbm'):
        raise ValueError('输出名称必须是无目录的 .pbm 文件名。')
    binary = ROOT / 'build/pdf-raster'
    if not binary.is_file():
        raise RuntimeError('请先运行 make 编译本机栅格转换器。')
    with target.open('xb') as output:
        try:
            subprocess.run([str(binary), str(args.pdf.resolve()), str(args.page),
                            str(args.dpi), args.mode], stdout=output, check=True, timeout=120)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    print(f'黑白栅格已生成：{target}\n这不是可直接发送到 bizhub 185 的打印数据。')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('probe', help='只读检测 USB 设备，不发送打印任务')
    sub.add_parser('status', help='只读查询 USB 打印端点及原始状态')
    item = sub.add_parser('inspect', help='分析一页官方打印数据样本')
    item.add_argument('sample', type=Path)
    item = sub.add_parser('render', help='PDF 单页转换为一位黑白 PBM')
    item.add_argument('pdf', type=Path)
    item.add_argument('--page', type=int, default=1)
    item.add_argument('--dpi', type=int, choices=(300, 600), default=600)
    item.add_argument('--mode', choices=('threshold', 'ordered'), default='threshold')
    item.add_argument('--name', default='page.pbm')
    args = parser.parse_args()
    try:
        if args.action == 'probe': return probe()
        if args.action == 'status': return status()
        if args.action == 'inspect': return inspect(args.sample)
        return render(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            plistlib.InvalidFileException, zipfile.BadZipFile) as error:
        print(f'错误：{error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
