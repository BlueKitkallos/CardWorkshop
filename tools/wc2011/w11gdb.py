import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import view_deal

FRAME_FN = 0x020162e4


class Gdb(view_deal.Rsp):
    def cmd(self, data, reply=True):
        r = super().cmd(data, reply)
        while reply and data[0] in 'mMpPzZ' and r[:1] in ('S', 'T'):
            r = self.reply()
        return r

    def halt(self):
        self.s.sendall(b'\x03')
        self.reply()

    def go(self):
        self.cmd('c', reply=False)

    def bp(self, addr):
        self.ok(f'Z0,{addr:x},2')

    def unbp(self, addr):
        self.cmd(f'z0,{addr:x},2')

    def read(self, addr, n):
        r = self.cmd(f'm{addr:x},{n:x}')
        out, i = [], 0
        while i < len(r):
            if r[i] == '*':
                out.append(out[-1] * (ord(r[i + 1]) - 29))
                i += 2
            else:
                out.append(r[i])
                i += 1
        try:
            data = bytes.fromhex(''.join(out))
        except ValueError:
            raise SystemExit(f'GDB read {addr:#x}+{n:#x}: {r[:40]!r}')
        if len(data) != n:
            raise SystemExit(f'GDB read {addr:#x}+{n:#x}: got {len(data)} bytes ({r[:16]})')
        return data

    def read_big(self, addr, n):
        return b''.join(self.read(addr + o, min(0x100, n - o)) for o in range(0, n, 0x100))

    def u16(self, addr):
        return struct.unpack('<H', self.read(addr, 2))[0]

    def wait(self, timeout):
        self.s.settimeout(timeout)
        try:
            self.reply()
            return True
        except SystemExit:
            return False
        finally:
            self.s.settimeout(60)

    def regs(self):
        return {n: self.reg(n) for n in range(17)}

    def resume(self, regs):
        for n in list(range(15)) + [16]:
            self.set_reg(n, regs[n])
        self.set_reg(15, regs[15] | (regs[16] >> 5 & 1))
        self.go()

    def at_frame(self):
        self.bp(FRAME_FN)
        self.go()
        self.reply()
        self.unbp(FRAME_FN)

    def call(self, fn, *args):
        self.bp(FRAME_FN)
        for i, v in enumerate(args):
            self.set_reg(i, v)
        self.set_reg(14, FRAME_FN | 1)
        self.set_reg(15, fn | 1)
        self.go()
        self.reply()
        self.unbp(FRAME_FN)
        if self.reg(15) != FRAME_FN:
            raise SystemExit(f'call {fn:#x}: stopped at {self.reg(15):#x}')
        return self.reg(0)
