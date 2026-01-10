#!/usr/bin/env python3
import os

def write_intel_hex(data, outpath, start_addr=0):
    def record(type, addr, payload):
        ln = bytes([len(payload), (addr>>8)&0xFF, addr&0xFF, type]) + payload
        csum = (-sum(ln)) & 0xFF
        return ':' + ''.join(f'{b:02X}' for b in ln) + f'{csum:02X}' + '\n'

    with open(outpath, 'w') as f:
        addr = 0
        length = len(data)
        # write data in 16-byte records
        i = 0
        while i < length:
            chunk = data[i:i+16]
            f.write(record(0x00, (start_addr + i) & 0xFFFF, chunk))
            i += 16
        # end linear address record if needed
        hi_addr = (start_addr + length) >> 16
        # If data spans beyond 64K boundary, we should emit extended linear address records at appropriate points.
        # For simplicity, we will regenerate with proper extended linear address handling below.


def make_hex(outpath, regions):
    # regions: list of (offset, path_to_bin)
    # determine total size
    max_end = 0
    for off, p in regions:
        sz = os.path.getsize(p)
        max_end = max(max_end, off + sz)
    data = bytearray(b'\xFF' * max_end)
    for off, p in regions:
        with open(p, 'rb') as f:
            b = f.read()
        data[off:off+len(b)] = b

    # write intel hex with extended linear address handling
    def record(type, addr, payload):
        ln = bytes([len(payload), (addr>>8)&0xFF, addr&0xFF, type]) + payload
        csum = (-sum(ln)) & 0xFF
        return ':' + ''.join(f'{b:02X}' for b in ln) + f'{csum:02X}' + '\n'

    with open(outpath, 'w') as f:
        base = 0
        length = len(data)
        i = 0
        while i < length:
            abs_addr = i
            upper = (abs_addr >> 16) & 0xFFFF
            if upper != base:
                # write extended linear address record
                f.write(record(0x04, 0, bytes([(upper>>8)&0xFF, upper&0xFF])))
                base = upper
            low_addr = abs_addr & 0xFFFF
            chunk = data[i:i+16]
            f.write(record(0x00, low_addr, bytes(chunk)))
            i += 16
        # End Of File record
        f.write(':00000001FF\n')

if __name__ == '__main__':
    proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    build_dir = os.path.join(proj_root, '.pio', 'build')
    envs = ['baseline', 'improved']
    for env in envs:
        envdir = os.path.join(build_dir, env)
        boot = os.path.join(envdir, 'bootloader.bin')
        parts = os.path.join(envdir, 'partitions.bin')
        fw = os.path.join(envdir, 'firmware.bin')
        if not (os.path.exists(boot) and os.path.exists(parts) and os.path.exists(fw)):
            print('Missing bins for', env)
            continue
        regions = [ (0x1000, boot), (0x8000, parts), (0x10000, fw) ]
        outhex = os.path.join(envdir, 'esp32_combined.hex')
        make_hex(outhex, regions)
        print('Wrote', outhex)
