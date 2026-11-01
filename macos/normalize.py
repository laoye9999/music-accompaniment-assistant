import sys, wave
import numpy as np

src, dst = sys.argv[1], sys.argv[2]
w = wave.open(src, 'rb')
sr = w.getframerate()
ch = w.getnchannels()
sw = w.getsampwidth()
n = w.getnframes()
pcm = np.frombuffer(w.readframes(n), dtype='<i2').reshape(-1, ch)
w.close()

f = pcm.astype(np.float64) / 32768.0
peak = float(np.abs(f).max())
gain = 0.891 / peak if peak > 0 else 1.0  # normalize to -1 dBFS
out = np.clip(f * gain, -1.0, 1.0)
out16 = (out * 32767).astype('<i2')

w2 = wave.open(dst, 'wb')
w2.setnchannels(ch)
w2.setsampwidth(sw)
w2.setframerate(sr)
w2.writeframes(out16.tobytes())
w2.close()
print(f'peak {peak:.3f} -> gain {gain:.2f} ({20*np.log10(gain):+.1f} dB), saved {dst} ({len(f)/sr:.1f}s)')
