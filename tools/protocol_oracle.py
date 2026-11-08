"""Offline micro-harness for the licensed, pinned official output module.

Executes selected x86-64 routines in Unicorn's emulated memory. It does not
load a Windows DLL into macOS, expose host syscalls, or communicate with USB.
Inputs are synthetic; this is a protocol oracle, not a Windows spooler.
"""
import hashlib
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'build/vendor')]
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_RAX, UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_RSP, UC_X86_REG_RIP
import bizhub

BASE = 0x40400000
STATE = 0x10000000
GSD = STATE + 0xfa0
SCRATCH = 0x10010000
BAND = 0x10020000
PIXELS = 0x10030000
STACK = 0x20010008
STOP = 0x30000000
DIGEST = '1a7881f960226c4dd92c8c27b54a96515e8d5ed9e71a4866ae235bac893b1527'


class Oracle:
    def __init__(self):
        path = bizhub.ARTIFACTS / 'official-xps/BH165XPSWin8x64_11000EN/PSSX8gsmo.dll'
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != DIGEST:
            raise ValueError('Official module checksum mismatch')
        self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mu.mem_map(BASE, 0x100000)
        self.mu.mem_map(STATE, 0x1000000)
        self.mu.mem_map(0x20000000, 0x20000)
        self.mu.mem_map(STOP, 0x1000)
        self.mu.mem_write(STOP, b'\xc3')
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        sections = struct.unpack_from('<H', data, pe+6)[0]
        optional_size = struct.unpack_from('<H', data, pe+20)[0]
        for i in range(sections):
            off = pe + 24 + optional_size + i*40
            _, rva, size, ptr = struct.unpack_from('<IIII', data, off+8)
            self.mu.mem_write(BASE+rva, data[ptr:ptr+size])
        self.output = bytearray()
        self.heap = 0x10100000
        self.hooks = {}
        self.hook(BASE+0x1070, self.write)
        self.hook(BASE+0x1000, lambda: 1)  # captured writes need no buffering
        self.hook(BASE+0x29d40, self.copy)
        self.hook(BASE+0x2a320, self.fill)
        self.hook(BASE+0x2ab34, self.sprintf)
        self.hook(BASE+0x2a100, self.allocate)
        self.hook(BASE+0x2a1fc, lambda:0)
        # Network byte order imports, identified in the PE import table.
        for offset, addr, size in [(0x402e0, STOP+0x10, 4), (0x402e8, STOP+0x20, 2)]:
            self.put(BASE+offset, 'Q', addr)
            self.hook(addr, lambda n=size: int.from_bytes(
                (self.reg(UC_X86_REG_RCX) & ((1 << (n*8))-1)).to_bytes(n, 'little'), 'big'))

    def load_codec(self):
        path = bizhub.ARTIFACTS / 'official-xps/BH165XPSWin8x64_11000EN/PSSX8.dll'
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != '6f19614de0d23b35b7729de93687cce55228acd290c2be99f5564ce6cce1871d':
            raise ValueError('Official codec checksum mismatch')
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        sections = struct.unpack_from('<H', data, pe+6)[0]
        optional_size = struct.unpack_from('<H', data, pe+20)[0]
        base = struct.unpack_from('<Q', data, pe+48)[0]
        size = struct.unpack_from('<I', data, pe+80)[0]
        if base != 0x180000000: raise ValueError('Unexpected codec base')
        self.mu.mem_map(base, (size+4095)&~4095)
        for i in range(sections):
            off = pe+24+optional_size+i*40
            _, rva, raw_size, ptr = struct.unpack_from('<IIII', data, off+8)
            if raw_size: self.mu.mem_write(base+rva, data[ptr:ptr+raw_size])
        for offset, fn in [(0x2e6b74,self.allocate), (0x2e8c30,self.callocate),
                           (0x2e6c2c,lambda:0), (0x2e6c80,self.fill),
                           (0x2ea1b0,self.compare), (0xa65e0,lambda:0)]:
            self.hook(base+offset,fn)
        for iat, rva in [(0x741d0,0xa66f0), (0x741d8,0xa6770), (0x741e0,0xa6690),
                         (0x741e8,0xa66a0), (0x741f0,0xa66d0)]:
            self.put(BASE+iat,'Q',base+rva)

    def callocate(self):
        length=self.reg(UC_X86_REG_RCX)*self.reg(UC_X86_REG_RDX)
        self.mu.reg_write(UC_X86_REG_RCX,length)
        result=self.allocate()
        self.mu.mem_write(result,b'\0'*length)
        return result

    def compare(self):
        a,b,n=(self.reg(r) for r in (UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_R8))
        aa,bb=bytes(self.mu.mem_read(a,n)),bytes(self.mu.mem_read(b,n))
        return 0 if aa==bb else 1 if aa>bb else 0xffffffffffffffff

    def compressed(self,width,height,pixels):
        self.load_codec()
        stride=(width+7)//8
        self.put(GSD+0x1024,'I',1)
        self.put(GSD+0x1020,'I',1)
        self.put(GSD+0x10e8,'Q',SCRATCH)
        self.put(GSD+0x10f8,'I',0)
        # GsdPageStart parameter block: DPI, bounds pointer, plane count,
        # physical width/height in thousandths of an inch.
        params=BAND+0x100
        bounds=BAND+0x200
        self.mu.mem_write(bounds,struct.pack('<4i',0,0,width,height))
        self.mu.mem_write(params,struct.pack('<IIQIII',600,600,bounds,1,
            (width*1000+599)//600,(height*1000+599)//600))
        self.call(0x58a0,GSD,params)
        assert self.read_int(GSD+0x1028,'Q')
        self.put(BAND+0x20,'I',1)
        self.put(BAND+0x28,'I',width)
        self.put(BAND+0x2c,'I',height)
        self.put(BAND+0x30,'I',stride)
        self.put(BAND+0x38,'Q',PIXELS)
        self.mu.mem_write(PIXELS,pixels)
        self.call(0x54f0,GSD,BAND)
        self.call(0x5e30,GSD)
        return bytes(self.output)

    def reg(self, name): return self.mu.reg_read(name)
    def put(self, address, fmt, value): self.mu.mem_write(address, struct.pack('<'+fmt, value))
    def read_int(self, address, fmt='I'): return struct.unpack('<'+fmt, self.mu.mem_read(address, struct.calcsize(fmt)))[0]
    def string(self, address):
        data = bytes(self.mu.mem_read(address, 4096))
        if b'\0' not in data: raise ValueError('Unterminated string')
        return data.split(b'\0', 1)[0].decode('ascii')

    def hook(self, address, fn):
        def callback(mu, pc, size, user):
            result = fn()
            rsp = self.reg(UC_X86_REG_RSP)
            mu.reg_write(UC_X86_REG_RAX, result or 0)
            mu.reg_write(UC_X86_REG_RIP, self.read_int(rsp, 'Q'))
            mu.reg_write(UC_X86_REG_RSP, rsp+8)
        self.hooks[address] = self.mu.hook_add(UC_HOOK_CODE, callback, begin=address, end=address)

    def write(self):
        length = self.reg(UC_X86_REG_R8)
        if length > 16*1024*1024: raise ValueError('Oversized write')
        self.output.extend(self.mu.mem_read(self.reg(UC_X86_REG_RDX), length))
        return 1

    def copy(self):
        dest, src, length = (self.reg(r) for r in (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8))
        if length > 16*1024*1024: raise ValueError('Oversized copy')
        self.mu.mem_write(dest, bytes(self.mu.mem_read(src, length)))
        return dest

    def fill(self):
        dest, value, length = (self.reg(r) for r in (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8))
        if length > 16*1024*1024: raise ValueError('Oversized fill')
        self.mu.mem_write(dest, bytes([value & 255])*length)
        return dest

    def allocate(self):
        length = self.reg(UC_X86_REG_RCX)
        result = self.heap
        self.heap += (length + 15) & ~15
        if self.heap >= STATE+0x1000000: raise ValueError('Emulated heap limit')
        return result

    def sprintf(self):
        dest = self.reg(UC_X86_REG_RCX)
        fmt = self.string(self.reg(UC_X86_REG_RDX))
        args = iter([self.reg(UC_X86_REG_R8), self.reg(UC_X86_REG_R9)])
        def subst(match):
            code = match[0][-1]
            if code == '%': return '%'
            value = next(args)
            if code == 's': return self.string(value)
            if code == 'c': return chr(value & 255)
            if code == 'd': return str(struct.unpack('<i', struct.pack('<I', value & 0xffffffff))[0])
            raise ValueError('Unsupported format')
        text = re.sub(r'%[%scd]', subst, fmt).encode('ascii')
        if len(text) >= 128: raise ValueError('Formatted output too large')
        self.mu.mem_write(dest, text+b'\0')
        return len(text)

    def call(self, offset, *args):
        self.put(STACK, 'Q', STOP)
        self.mu.reg_write(UC_X86_REG_RSP, STACK)
        for reg, value in zip((UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9), args):
            self.mu.reg_write(reg, value)
        self.mu.emu_start(BASE+offset, STOP, timeout=10000000, count=50000000)
        if self.reg(UC_X86_REG_RIP) != STOP: raise RuntimeError('Emulation did not return within limits')
        return self.reg(UC_X86_REG_RAX)

    def raw_band(self, width, height, pixels):
        stride = (width+7)//8
        assert len(pixels) == stride*height
        self.put(GSD+0x1024, 'I', 0)
        self.put(GSD+0x10f0, 'I', 1)
        self.put(GSD+0x10e8, 'Q', SCRATCH)
        self.put(BAND+0x28, 'I', width)
        self.put(BAND+0x2c, 'I', height)
        self.put(BAND+0x30, 'I', stride)
        self.put(BAND+0x38, 'Q', PIXELS)
        self.mu.mem_write(PIXELS, pixels)
        before = len(self.output)
        self.call(0x54f0, GSD, BAND)
        return bytes(self.output[before:])


if __name__ == '__main__':
    folder = bizhub.external_directory()
    oracle = Oracle()
    data = oracle.raw_band(32, 24, b'\xaa\x55\x00\xff'*24)
    (folder/'oracle-raw-band.bin').write_bytes(data)
    print('Official raw-band output:', len(data), 'bytes', data[:28].hex())
