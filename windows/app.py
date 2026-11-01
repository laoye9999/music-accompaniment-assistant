# -*- coding: utf-8 -*-
"""
音乐伴奏助力 · Windows 单文件版（可用 PyInstaller 打包成 exe）
三板块：① QQ音乐下载查询  ② 制作伴奏  ③ 识别歌词
"""
import os, sys, time, threading, re, json, wave, urllib.request, urllib.parse, shutil
import numpy as np
import sounddevice as sd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

SR = 44100
UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com'}
AUDIO_EXT = ('.mflac', '.mgg', '.qmc', '.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.aiff', '.aif')
META_KEYS = ('作词', '作曲', '演唱', '原唱', '总监', '制作', '编曲', '混音', '弦乐', '吉他', '键盘',
             '贝斯', '鼓', '打击乐', '和音', 'PGM', '统筹', '舞台', '音响', '设计', '改编', '母带',
             '录音', '监制', '出品', '发行', '词：', '曲：')


# ===================== 录音 =====================
def find_loopback():
    try:
        for i, d in enumerate(sd.query_devices()):
            n = (d['name'] or '').lower()
            if d['max_input_channels'] > 0 and ('loopback' in n or 'stereo mix' in n or '立体声混音' in n):
                return i
    except Exception:
        pass
    try:
        for h in sd.query_hostapis():
            if 'wasapi' in h['name'].lower() and h.get('default_output_device', -1) >= 0:
                return h['default_output_device']
    except Exception:
        pass
    return None


def record_audio(out, stopfile, max_dur, auto_stop, log, status_cb):
    dev = find_loopback()
    if dev is None:
        log('❌ 未找到回环录音设备。请安装 VB-Cable 虚拟声卡并把播放设备设为 CABLE Input')
        return False
    chunks, st = [], {'sig': False, 'sil': 0.0, 'last': 0.0, 'stop': False}

    def cb(indata, frames, t, status):
        try:
            chunks.append(indata.copy())
            rms = float(np.sqrt((indata ** 2).mean()))
            if not st['sig'] and rms > 0.0005:
                st['sig'] = True
                log('🎵 检测到音乐信号')
            if st['sig']:
                st['sil'] = st['sil'] + frames / SR if rms < 0.0005 else 0.0
                if auto_stop and st['sil'] >= 8.0:
                    st['stop'] = True
                    log('歌曲结束，自动停止录音')
            if t.currentTime - st['last'] >= 5.0:
                st['last'] = t.currentTime
                status_cb(f'录音中… 已录 {t.currentTime:.0f}s｜电平 {rms:.4f}')
        except Exception as e:
            log('录音回调错误: ' + str(e))

    try:
        ch = 2
        with sd.InputStream(device=dev, channels=ch, samplerate=SR, dtype='float32', callback=cb, blocksize=4410):
            t0 = time.time()
            while time.time() - t0 < max_dur and not st['stop']:
                if os.path.exists(stopfile):
                    break
                time.sleep(0.2)
    except Exception:
        ch = 1
        with sd.InputStream(device=dev, channels=ch, samplerate=SR, dtype='float32', callback=cb, blocksize=4410):
            t0 = time.time()
            while time.time() - t0 < max_dur and not st['stop']:
                if os.path.exists(stopfile):
                    break
                time.sleep(0.2)

    data = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, ch), np.float32)
    w = wave.open(out, 'wb'); w.setnchannels(ch); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((data * 32767).clip(-32768, 32767).astype('<i2').tobytes()); w.close()
    return st['sig']


# ===================== 分段 =====================
def segment_audio(src, outprefix):
    w = wave.open(src, 'rb'); sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
    pcm = np.frombuffer(w.readframes(n), dtype='<i2').reshape(-1, ch); w.close()
    win = int(sr * 0.1); nwin = len(pcm) // win
    rms = np.sqrt((pcm[:nwin * win].reshape(nwin, win, ch).astype(np.float32) ** 2).mean(axis=(1, 2)))
    thr = max(rms.max() * 0.04, 0.0003)
    active = rms > thr
    segs, in_seg, gap = [], False, 0
    for i, a in enumerate(active):
        if a:
            if not in_seg:
                start, in_seg = i, True
            gap = 0
        elif in_seg:
            gap += 1
            if gap > 80:
                segs.append((start, i - gap + 1)); in_seg = False
    if in_seg:
        segs.append((start, nwin - 1))
    if not segs:
        return None
    a, b = segs[0]
    s0, s1 = max(0, int((a - 3) * win)), min(len(pcm), int((b + 10) * win))
    out = outprefix + '_seg0.wav'
    w2 = wave.open(out, 'wb'); w2.setnchannels(ch); w2.setsampwidth(sw); w2.setframerate(sr)
    w2.writeframes(pcm[s0:s1].astype('<i2').tobytes()); w2.close()
    return out


# ===================== 音量标准化 =====================
def normalize_audio(src, dst):
    w = wave.open(src, 'rb'); sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
    pcm = np.frombuffer(w.readframes(n), dtype='<i2').reshape(-1, ch).astype(np.float64) / 32768.0; w.close()
    peak = float(np.abs(pcm).max())
    gain = 0.891 / peak if peak > 0 else 1.0
    out = np.clip(pcm * gain, -1, 1)
    w2 = wave.open(dst, 'wb'); w2.setnchannels(ch); w2.setsampwidth(sw); w2.setframerate(sr)
    w2.writeframes((out * 32767).astype('<i2').tobytes()); w2.close()


# ===================== 歌词识别 =====================
def _http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8'))


def _parse_name(name):
    base = re.sub(r'\.(mflac|mgg|qmc\d*|mp3|m4a|wav|flac|aac|ogg|aiff|aif)$', '', name, flags=re.I)
    sep = '-' if '-' in base else ('－' if '－' in base else None)
    artist, title = (base.split(sep, 1) if sep else ('', base))
    title = re.sub(r'[（(]?(伴奏|纯音乐|消音|无人声|instrumental|人声|vocals)[)）]?$', '', title, flags=re.I).strip()
    title = re.sub(r'\s*\(?live\)?\s*$', '', title, flags=re.I).strip()
    return artist.strip(), title.strip()


def gen_lrc(folder, outdir, log):
    files = [f for f in os.listdir(folder) if f.lower().endswith(AUDIO_EXT)]
    song = next((os.path.join(folder, f) for f in files
                 if not re.search(r'(伴奏|纯音乐|消音|无人声|instrumental|人声|vocals)', f, re.I)), None)
    if not song:
        log('❌ 未在文件夹中找到歌曲文件'); return
    log('识别到歌曲: ' + os.path.basename(song))
    artist, title = _parse_name(os.path.basename(song))
    log(f'解析: 歌手="{artist}" 歌名="{title}"')
    if not title:
        log('❌ 无法从文件名解析歌名'); return

    log('🔍 联网搜索歌词…')
    queries = []
    if artist:
        queries.append(f'{title} {artist}')
        for a in re.split(r'[,，/、&]', artist):
            if a.strip():
                queries.append(f'{title} {a.strip()}')
    queries.append(title)
    seen = {}
    for q in queries:
        try:
            url = 'https://music.163.com/api/search/get/web?' + urllib.parse.urlencode({'s': q, 'type': 1, 'limit': 10, 'offset': 0})
            d = _http_json(url)
            r = d.get('result')
            for s in (r.get('songs', []) if isinstance(r, dict) else []):
                seen[s['id']] = s
        except Exception:
            pass
    if not seen:
        log('❌ 未搜索到结果'); return
    def _score(s):
        nm = (s.get('name') or '').lower(); tt = title.lower(); sc = 0
        if tt and tt in nm:
            sc += 6
        elif tt and re.sub(r'[（(].*?[)）]', '', nm).strip() == tt:
            sc += 5
        if 'cover' in nm or '翻唱' in nm or '翻自' in nm or '伴奏' in nm or '纯音乐' in nm:
            sc -= 4
        arts = ''.join(a.get('name', '') for a in s.get('artists', []))
        for a in re.split(r'[,，/、&]', artist):
            if a.strip() and a.strip() in arts:
                sc += 4
        return sc
    best = sorted(seen.values(), key=_score, reverse=True)[0]
    log(f'最佳匹配: {best["name"]} - {"/".join(a["name"] for a in best.get("artists", []))}')
    lrc = _http_json(f'https://music.163.com/api/song/lyric?id={best["id"]}&lv=-1&kv=-1&tv=-1').get('lrc', {}).get('lyric', '')
    lines = []
    for l in lrc.splitlines():
        m = re.match(r'\[(\d{2}):(\d{2})[.:](\d{1,3})\](.*)', l.strip())
        if not m:
            continue
        mm, ss, cs, txt = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4).strip()
        if not txt or any(k in txt for k in META_KEYS):
            continue
        if len(cs) == 1:
            cs += '0'
        elif len(cs) == 3:
            cs = cs[:2]
        lines.append((mm * 60 + ss + int(cs) / 100, txt))
    if not lines:
        log('❌ 该歌曲没有可用歌词'); return
    log(f'获取到 {len(lines)} 句歌词')

    # 对齐：找人声文件
    search_dirs = [d for d in (folder, outdir, os.path.dirname(folder.rstrip(os.sep))) if d and os.path.isdir(d)]
    vocal = None
    for d in search_dirs:
        cands = [os.path.join(d, f) for f in os.listdir(d)
                 if f.lower().endswith(AUDIO_EXT) and re.search(r'(人声|vocals|vocal)', f, re.I)]
        if cands:
            vocal = max(cands, key=os.path.getmtime)
            break
    if vocal:
        log('找到人声文件: ' + os.path.basename(vocal))
        w = wave.open(vocal, 'rb'); sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        d = np.frombuffer(w.readframes(n), dtype='<i2').astype(np.float32); w.close()
        if ch >= 2:
            d = d.reshape(-1, ch).mean(axis=1)
        d /= 32768.0
        win = int(sr * 0.02); nn = len(d) // win
        env = np.convolve(np.sqrt((d[:nn * win].reshape(nn, win) ** 2).mean(axis=1)), np.ones(5) / 5, mode='same')
        thr = max(env.max() * 0.02, 0.0003)
        onset = next((i * 0.02 for i, e in enumerate(env) if e > thr), None)
        if onset is not None:
            ref = next((t for t, x in lines if len(x) > 4), lines[0][0])
            off = onset - ref
            lines = [(max(0.0, t + off), x) for t, x in lines]
            log(f'🎯 精确对齐：偏移 {off:+.2f}s')
        else:
            log('⚠️ 人声文件是静音（伴奏可能没录完整），使用网络原始时间')
    else:
        log('⚠️ 未找到人声文件，使用网络歌词原始时间')

    out = os.path.join(outdir, f'{title}-标准歌词.lrc')
    with open(out, 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(f'[{int(t // 60):02d}:{t % 60:05.2f}]{x}' for t, x in lines) + '\n')
    log(f'✅ 完成！已保存: {out}')


# ===================== AI 分离 =====================
def separate_vocals(song, outdir, log):
    from demucs.separate import main as demucs_main
    demucs_main(['--two-stems', 'vocals', '-d', 'cpu', '-o', outdir, song])


# ===================== 界面 =====================
class App:
    def __init__(self, root):
        self.root = root
        root.title('音乐伴奏助力（Windows 版）')
        root.geometry('700x760')

        top = ttk.Frame(root); top.pack(fill='x', padx=10, pady=8)
        ttk.Label(top, text='保存路径:').pack(side='left')
        self.save_path = tk.StringVar(value=os.path.expanduser('~\\Music'))
        ttk.Entry(top, textvariable=self.save_path, width=45).pack(side='left', padx=5)
        ttk.Button(top, text='选择', command=self.choose_save).pack(side='left')

        f1 = ttk.LabelFrame(root, text='① QQ音乐下载查询'); f1.pack(fill='x', padx=10, pady=4)
        ttk.Button(f1, text='打开 QQ音乐下载目录', command=self.open_qq).pack(padx=10, pady=6)

        f2 = ttk.LabelFrame(root, text='② 制作伴奏'); f2.pack(fill='x', padx=10, pady=4)
        r2 = ttk.Frame(f2); r2.pack(fill='x', pady=4)
        self.btn_rec = ttk.Button(r2, text='开始制作伴奏', command=self.make_accomp); self.btn_rec.pack(side='left', padx=8)
        self.btn_stop = ttk.Button(r2, text='停止录音', command=self.stop, state='disabled'); self.btn_stop.pack(side='left', padx=4)
        self.status = ttk.Label(r2, text='', foreground='blue'); self.status.pack(side='left', padx=8)
        self.log2 = scrolledtext.ScrolledText(f2, height=8, font=('微软雅黑', 9)); self.log2.pack(fill='x', padx=8, pady=4)

        f3 = ttk.LabelFrame(root, text='③ 识别歌词'); f3.pack(fill='both', expand=True, padx=10, pady=4)
        r3 = ttk.Frame(f3); r3.pack(fill='x', pady=4)
        self.song_folder = tk.StringVar()
        ttk.Entry(r3, textvariable=self.song_folder, width=45).pack(side='left', padx=5)
        ttk.Button(r3, text='浏览…', command=self.choose_song).pack(side='left')
        self.btn_lyric = ttk.Button(r3, text='开始识别', command=self.make_lyric); self.btn_lyric.pack(side='left', padx=8)
        self.log3 = scrolledtext.ScrolledText(f3, height=8, font=('微软雅黑', 9)); self.log3.pack(fill='both', expand=True, padx=8, pady=4)

        self.stop_file = None

    def _log(self, w, s):
        w.insert('end', s + '\n'); w.see('end')

    def choose_save(self):
        d = filedialog.askdirectory(title='选择保存文件夹')
        if d:
            self.save_path.set(d)

    def choose_song(self):
        d = filedialog.askdirectory(title='选择歌曲存放的文件夹')
        if d:
            self.song_folder.set(d)

    def open_qq(self):
        for c in [os.path.expandvars(r'%USERPROFILE%\AppData\Local\Tencent\QQMusic'),
                  os.path.expanduser('~\\Music\\QQ音乐'),
                  os.path.expanduser('~\\Downloads')]:
            if os.path.isdir(c):
                os.startfile(c); return
        messagebox.showinfo('提示', '未自动找到 QQ音乐下载目录，请手动定位')

    def make_accomp(self):
        save = self.save_path.get()
        if not os.path.isdir(save):
            messagebox.showwarning('提示', '请先选择保存路径'); return
        self.log2.delete('1.0', 'end')
        self.btn_rec.config(state='disabled'); self.btn_stop.config(state='normal')
        work = os.path.join(os.environ.get('TEMP', '.'), 'yybz-' + str(int(time.time())))
        os.makedirs(work, exist_ok=True)
        rec_out = os.path.join(work, 'recording.wav')
        self.stop_file = os.path.join(work, 'stop')
        if os.path.exists(self.stop_file):
            os.remove(self.stop_file)

        def worker():
            self._log(self.log2, '▶ 开始制作伴奏，请播放歌曲（录完自动停止，或点「停止录音」）')
            ok = record_audio(rec_out, self.stop_file, 1200, True,
                              lambda s: self._log(self.log2, s),
                              lambda s: self.root.after(0, lambda: self.status.config(text=s)))
            if not ok:
                self._log(self.log2, '❌ 录音失败或没检测到声音'); self._done(); return
            self._log(self.log2, '✂️ 分析音频，裁剪出歌曲…')
            song = segment_audio(rec_out, os.path.join(work, 'seg'))
            if not song:
                self._log(self.log2, '❌ 未识别出歌曲'); self._done(); return
            self._log(self.log2, '🧠 AI 分离人声中…（约 3-15 分钟）')
            try:
                separate_vocals(song, os.path.join(work, 'demucs_out'), self._log)
            except Exception as e:
                self._log(self.log2, '❌ AI 分离失败: ' + str(e)); self._done(); return
            base = os.path.splitext(os.path.basename(song))[0]
            nv = os.path.join(work, 'demucs_out', 'htdemucs', base, 'no_vocals.wav')
            vv = os.path.join(work, 'demucs_out', 'htdemucs', base, 'vocals.wav')
            if not os.path.exists(nv):
                self._log(self.log2, '❌ 分离结果缺失'); self._done(); return
            date = time.strftime('%Y年%m月%d日')
            out = os.path.join(save, f'伴奏-{date}.wav')
            if os.path.exists(out):
                out = os.path.join(save, f'伴奏-{date}-{time.strftime("%H%M%S")}.wav')
            normalize_audio(nv, out)
            shutil.copy(vv, os.path.join(save, os.path.splitext(os.path.basename(out))[0] + '-人声.wav'))
            self._log(self.log2, f'✅ 完成！伴奏已保存：{out}')
            self._done()

        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        if self.stop_file:
            open(self.stop_file, 'w').close()
            self._log(self.log2, '⏹ 已请求停止录音…')

    def _done(self):
        self.root.after(0, lambda: self.btn_rec.config(state='normal'))
        self.root.after(0, lambda: self.btn_stop.config(state='disabled'))
        self.root.after(0, lambda: self.status.config(text=''))

    def make_lyric(self):
        folder, save = self.song_folder.get(), self.save_path.get()
        if not os.path.isdir(folder):
            messagebox.showwarning('提示', '请先选择歌曲文件夹'); return
        if not os.path.isdir(save):
            messagebox.showwarning('提示', '请先选择保存路径'); return
        self.log3.delete('1.0', 'end')
        self.btn_lyric.config(state='disabled')

        def worker():
            gen_lrc(folder, save, lambda s: self._log(self.log3, s))
            self.root.after(0, lambda: self.btn_lyric.config(state='normal'))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
