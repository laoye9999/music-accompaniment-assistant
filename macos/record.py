import sys, os, time, wave
import numpy as np
import sounddevice as sd

out = sys.argv[1]
stopfile = sys.argv[2]
max_dur = float(sys.argv[3])
auto_stop = (sys.argv[4] == '1')
sr = 44100

dev = None
for i, d in enumerate(sd.query_devices()):
    if d['name'] == 'BlackHole 2ch' and d['max_input_channels'] >= 2:
        dev = i
        break
assert dev is not None, 'BlackHole 2ch input not found'

chunks = []
state = {'signal': False, 'silent': 0.0, 'last': 0.0, 'stop': False}

def cb(indata, frames, t, status):
    try:
        chunks.append(indata.copy())
        rms = float(np.sqrt((indata ** 2).mean()))
        if not state['signal'] and rms > 0.0005:
            state['signal'] = True
            print('SIGNAL_STARTED', flush=True)
        if state['signal']:
            if rms < 0.0005:
                state['silent'] += frames / sr
            else:
                state['silent'] = 0.0
            if auto_stop and state['silent'] >= 8.0:
                state['stop'] = True
                print('AUTOSTOP', flush=True)
        if t.currentTime - state['last'] >= 5.0:
            state['last'] = t.currentTime
            print(f'PROGRESS t={t.currentTime:.0f} rms={rms:.4f}', flush=True)
    except Exception as e:
        print('CALLBACK_ERROR', e, flush=True)

print('RECORDING_STARTED', flush=True)
t0 = time.time()
with sd.InputStream(device=dev, channels=2, samplerate=sr, dtype='float32',
                    callback=cb, blocksize=4410):
    while time.time() - t0 < max_dur and not state['stop']:
        if os.path.exists(stopfile):
            print('STOPPED_BY_USER', flush=True)
            break
        time.sleep(0.2)

print('RECORDING_END', flush=True)
data = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, 2), dtype=np.float32)
pcm = (data * 32767).clip(-32768, 32767).astype('<i2')
w = wave.open(out, 'wb')
w.setnchannels(2)
w.setsampwidth(2)
w.setframerate(sr)
w.writeframes(pcm.tobytes())
w.close()
print(f'SAVED dur={len(data)/sr:.1f} had_signal={1 if state["signal"] else 0}', flush=True)
