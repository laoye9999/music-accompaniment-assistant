# -*- coding: utf-8 -*-
"""Windows 录音：录制系统播放的声音（WASAPI 回环 / 虚拟声卡），带自动停止。"""
import sys, os, time, wave
import numpy as np
import sounddevice as sd

out = sys.argv[1]          # 输出 wav
stopfile = sys.argv[2]     # 停止标记文件
max_dur = float(sys.argv[3])  # 最大录音秒数
auto_stop = (sys.argv[4] == '1')  # 检测到歌曲结束自动停止
sr = 44100

def find_loopback_device():
    """查找可用的回环（loopback）录音设备。"""
    # 1. 优先找名字里带 loopback / 立体声混音 / Stereo Mix 的设备
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            name = (d['name'] or '').lower()
            if d['max_input_channels'] > 0 and ('loopback' in name or 'stereo mix' in name or '立体声混音' in name):
                return i, d['name']
    except Exception:
        pass
    # 2. 尝试默认输出的 WASAPI 回环（Windows 10/11 支持）
    try:
        hostapis = sd.query_hostapis()
        for h in hostapis:
            if 'wasapi' in h['name'].lower() and h['default_output_device'] >= 0:
                # 用输出设备做回环录音（需要 sounddevice 0.4.4+ 的 WASAPI loopback）
                return h['default_output_device'], 'WASAPI loopback'
    except Exception:
        pass
    return None, None

dev, devname = find_loopback_device()
if dev is None:
    print('未找到可用的回环录音设备。请安装 VB-Cable 虚拟声卡（https://vb-audio.com/Cable/），'
          '并在系统声音里把输出设为 CABLE Input。', flush=True)
    sys.exit(1)
print(f'使用录音设备: {devname}', flush=True)

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
ch = 2
try:
    with sd.InputStream(device=dev, channels=ch, samplerate=sr, dtype='float32',
                        callback=cb, blocksize=4410):
        t0 = time.time()
        while time.time() - t0 < max_dur and not state['stop']:
            if os.path.exists(stopfile):
                print('STOPPED_BY_USER', flush=True)
                break
            time.sleep(0.2)
except Exception as e:
    # 如果2声道失败，退到1声道
    try:
        ch = 1
        chunks.clear()
        with sd.InputStream(device=dev, channels=ch, samplerate=sr, dtype='float32',
                            callback=cb, blocksize=4410):
            t0 = time.time()
            while time.time() - t0 < max_dur and not state['stop']:
                if os.path.exists(stopfile):
                    break
                time.sleep(0.2)
    except Exception as e2:
        print(f'录音失败: {e2}', flush=True)
        sys.exit(1)

print('RECORDING_END', flush=True)
data = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, ch), dtype=np.float32)
pcm = (data * 32767).clip(-32768, 32767).astype('<i2')
w = wave.open(out, 'wb')
w.setnchannels(ch)
w.setsampwidth(2)
w.setframerate(sr)
w.writeframes(pcm.tobytes())
w.close()
print(f'SAVED dur={len(data)/sr:.1f} had_signal={1 if state["signal"] else 0}', flush=True)
