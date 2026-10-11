"""Chiem VRAM de gay tinh huong thieu bo nho GPU (chi dung trong bai OOM). Chay TRONG container co GPU:
    docker run --rm -d --gpus all --name vr01-hog -v $PWD/tests:/t:ro <image triton> python3 /t/vram_hog.py --leave-free-mib 300
Dung CUDA driver API qua ctypes (libcuda.so.1), khong can PyTorch. Giu bo nho toi khi container bi dung.
In mot dong JSON: tong, da chiem, con trong. CHUA CHAY THU tren GPU (viet 11/10/2026)."""
import argparse
import ctypes
import json
import signal
import sys
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--leave-free-mib', type=int, default=300)
    ap.add_argument('--chunk-mib', type=int, default=256)
    a = ap.parse_args()
    cuda = ctypes.CDLL('libcuda.so.1')
    def ck(rc, what):
        if rc != 0:
            raise SystemExit(f'{what} failed: CUDA error {rc}')
    ck(cuda.cuInit(0), 'cuInit')
    dev, ctx = ctypes.c_int(), ctypes.c_void_p()
    ck(cuda.cuDeviceGet(ctypes.byref(dev), 0), 'cuDeviceGet')
    ck(cuda.cuCtxCreate_v2(ctypes.byref(ctx), 0, dev), 'cuCtxCreate')
    free, total = ctypes.c_size_t(), ctypes.c_size_t()
    ck(cuda.cuMemGetInfo_v2(ctypes.byref(free), ctypes.byref(total)), 'cuMemGetInfo')
    target = free.value - a.leave_free_mib * 2 ** 20
    held, ptrs, chunk = 0, [], a.chunk_mib * 2 ** 20
    while held < target:
        size = min(chunk, target - held)
        p = ctypes.c_void_p()
        if cuda.cuMemAlloc_v2(ctypes.byref(p), ctypes.c_size_t(size)) != 0:
            break
        ptrs.append(p)
        held += size
    ck(cuda.cuMemGetInfo_v2(ctypes.byref(free), ctypes.byref(total)), 'cuMemGetInfo')
    print(json.dumps({'total_mib': total.value // 2 ** 20, 'held_mib': held // 2 ** 20, 'free_mib': free.value // 2 ** 20}), flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(1)


if __name__ == '__main__':
    main()
