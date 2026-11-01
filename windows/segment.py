import sys, wave
import numpy as np

src = sys.argv[1]
outprefix = sys.argv[2] if len(sys.argv) > 2 else '/tmp/audio-tools/seg'

w = wave.open(src, 'rb')
sr = w.getframerate()
ch = w.getnchannels()
sw = w.getsampwidth()
n = w.getnframes()
pcm = np.frombuffer(w.readframes(n), dtype='<i2').reshape(-1, ch)
w.close()

win = int(sr * 0.1)
nwin = len(pcm) // win
rms = np.sqrt((pcm[:nwin * win].reshape(nwin, win, ch).astype(np.float32) ** 2).mean(axis=(1, 2)))
peak = rms.max()
thr = max(peak * 0.04, 0.0003)
active = rms > thr

# find continuous active runs, merge gaps < 8s（歌曲内部的短暂停顿不切段）
segs = []
in_seg = False
gap = 0
for i, a in enumerate(active):
    if a:
        if not in_seg:
            start = i
            in_seg = True
        gap = 0
    elif in_seg:
        gap += 1
        if gap > 80:  # 8s 静音才结束该段
            segs.append((start, i - gap + 1))
            in_seg = False
if in_seg:
    segs.append((start, nwin - 1))

print(f'total={len(pcm)/sr:.1f}s peak={peak:.4f} segments={len(segs)}')
for j, (a, b) in enumerate(segs):
    t0, t1 = a * 0.1, (b + 1) * 0.1
    print(f'  seg{j}: {t0:6.1f}s - {t1:6.1f}s  dur={t1-t0:5.1f}s')

if segs:
    # extract first segment (target song) with padding
    a, b = segs[0]
    s0 = max(0, int((a - 3) * win))
    s1 = min(len(pcm), int((b + 10) * win))
    cut = pcm[s0:s1]
    out = outprefix + '_seg0.wav'
    w2 = wave.open(out, 'wb')
    w2.setnchannels(ch)
    w2.setsampwidth(sw)
    w2.setframerate(sr)
    w2.writeframes(cut.astype('<i2').tobytes())
    w2.close()
    print(f'saved {out} ({len(cut)/sr:.1f}s)')
