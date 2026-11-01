# -*- coding: utf-8 -*-
"""
音乐伴奏助力 · Windows 版
三板块：① QQ音乐下载查询  ② 制作伴奏  ③ 识别歌词
依赖：pip install -r requirements.txt
"""
import os, sys, time, threading, subprocess, shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def run_script(script, args, log_func):
    """运行一个 python 脚本，实时输出到 log_func。"""
    cmd = [PYTHON, os.path.join(BASE, script)] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    for line in p.stdout:
        log_func(line.rstrip())
    p.wait()
    return p.returncode


class App:
    def __init__(self, root):
        self.root = root
        root.title('音乐伴奏助力（Windows 版）')
        root.geometry('700x760')

        # 共享保存路径
        top = ttk.Frame(root)
        top.pack(fill='x', padx=10, pady=8)
        ttk.Label(top, text='保存路径:').pack(side='left')
        self.save_path = tk.StringVar(value=os.path.expanduser('~\\Music'))
        ttk.Entry(top, textvariable=self.save_path, width=45).pack(side='left', padx=5)
        ttk.Button(top, text='选择', command=self.choose_save).pack(side='left')

        # ===== 板块① QQ音乐下载 =====
        f1 = ttk.LabelFrame(root, text='① QQ音乐下载查询')
        f1.pack(fill='x', padx=10, pady=4)
        ttk.Button(f1, text='打开 QQ音乐下载目录', command=self.open_qq_folder).pack(padx=10, pady=6)

        # ===== 板块② 制作伴奏 =====
        f2 = ttk.LabelFrame(root, text='② 制作伴奏')
        f2.pack(fill='x', padx=10, pady=4)
        row2 = ttk.Frame(f2); row2.pack(fill='x', pady=4)
        self.btn_record = ttk.Button(row2, text='开始制作伴奏', command=self.make_accomp)
        self.btn_record.pack(side='left', padx=8)
        self.btn_stop = ttk.Button(row2, text='停止录音', command=self.stop_record, state='disabled')
        self.btn_stop.pack(side='left', padx=4)
        self.rec_status = ttk.Label(row2, text='', foreground='blue')
        self.rec_status.pack(side='left', padx=8)
        self.log2 = scrolledtext.ScrolledText(f2, height=8, font=('微软雅黑', 9))
        self.log2.pack(fill='x', padx=8, pady=4)

        # ===== 板块③ 识别歌词 =====
        f3 = ttk.LabelFrame(root, text='③ 识别歌词')
        f3.pack(fill='both', expand=True, padx=10, pady=4)
        row3 = ttk.Frame(f3); row3.pack(fill='x', pady=4)
        self.song_folder = tk.StringVar()
        ttk.Entry(row3, textvariable=self.song_folder, width=45).pack(side='left', padx=5)
        ttk.Button(row3, text='浏览…', command=self.choose_song_folder).pack(side='left')
        self.btn_lyric = ttk.Button(row3, text='开始识别', command=self.make_lyric)
        self.btn_lyric.pack(side='left', padx=8)
        self.log3 = scrolledtext.ScrolledText(f3, height=8, font=('微软雅黑', 9))
        self.log3.pack(fill='both', expand=True, padx=8, pady=4)

        self.stop_file = None

    def log(self, widget, text):
        widget.insert('end', text + '\n')
        widget.see('end')

    def choose_save(self):
        d = filedialog.askdirectory(title='选择保存文件夹')
        if d:
            self.save_path.set(d)

    def choose_song_folder(self):
        d = filedialog.askdirectory(title='选择歌曲存放的文件夹')
        if d:
            self.song_folder.set(d)

    def open_qq_folder(self):
        """打开 QQ音乐 下载目录（尝试常见路径）。"""
        candidates = [
            os.path.expandvars(r'%USERPROFILE%\AppData\Local\Tencent\QQMusic'),
            os.path.expanduser('~\\Music\\QQ音乐'),
            os.path.expanduser('~\\Documents\\Tencent Files\\QQMusic'),
            os.path.expanduser('~\\Downloads'),
        ]
        for c in candidates:
            if os.path.isdir(c):
                os.startfile(c)
                return
        messagebox.showinfo('提示', '未自动找到 QQ音乐下载目录，请用文件管理器手动定位')

    def make_accomp(self):
        save = self.save_path.get()
        if not os.path.isdir(save):
            messagebox.showwarning('提示', '请先选择有效的保存路径')
            return
        self.log2.delete('1.0', 'end')
        self.btn_record.config(state='disabled')
        self.btn_stop.config(state='normal')

        work = os.path.join(os.environ.get('TEMP', '/tmp'), 'yybz-' + str(int(time.time())))
        os.makedirs(work, exist_ok=True)
        rec_out = os.path.join(work, 'recording.wav')
        stop_file = os.path.join(work, 'stop')
        self.stop_file = stop_file
        if os.path.exists(stop_file):
            os.remove(stop_file)

        def worker():
            self.log(self.log2, '▶ 开始制作伴奏（请先准备好要播放的歌曲）')
            self.log(self.log2, '🎙 请播放歌曲，录完会自动停止（也可点「停止录音」）')
            rc = run_script('record.py', [rec_out, stop_file, '1200', '1'], lambda s: self._on_rec_line(s))
            if rc != 0 or not os.path.exists(rec_out):
                self.log(self.log2, '❌ 录音失败，请确认已安装 VB-Cable 或系统支持回环录音')
                self._done()
                return
            # 检测到信号？
            # 分段
            self.log(self.log2, '✂️ 分析音频，裁剪出歌曲…')
            run_script('segment.py', [rec_out, os.path.join(work, 'seg')], lambda s: self.log(self.log2, s))
            song = os.path.join(work, 'seg_seg0.wav')
            if not os.path.exists(song):
                self.log(self.log2, '❌ 未能在录音中识别出歌曲')
                self._done()
                return
            # demucs
            self.log(self.log2, '🧠 AI 分离人声中…（约 3-15 分钟）')
            run_script('-m', ['demucs', '--two-stems=vocals', '-d', 'cpu', '-o',
                              os.path.join(work, 'demucs_out'), song], lambda s: None)
            # 保存
            base = os.path.splitext(os.path.basename(song))[0]
            nv = os.path.join(work, 'demucs_out', 'htdemucs', base, 'no_vocals.wav')
            vv = os.path.join(work, 'demucs_out', 'htdemucs', base, 'vocals.wav')
            if not os.path.exists(nv):
                self.log(self.log2, '❌ AI 分离失败')
                self._done()
                return
            date = time.strftime('%Y年%m月%d日')
            out_path = os.path.join(save, f'伴奏-{date}.wav')
            if os.path.exists(out_path):
                out_path = os.path.join(save, f'伴奏-{date}-{time.strftime("%H%M%S")}.wav')
            run_script('normalize.py', [nv, out_path], lambda s: self.log(self.log2, s))
            shutil.copy(vv, os.path.join(save, os.path.splitext(os.path.basename(out_path))[0] + '-人声.wav'))
            self.log(self.log2, f'✅ 完成！伴奏已保存：{out_path}')
            self._done()

        threading.Thread(target=worker, daemon=True).start()

    def _on_rec_line(self, s):
        if s.startswith('PROGRESS'):
            self.rec_status.config(text='录音中… ' + s.replace('PROGRESS ', ''))
        elif 'SIGNAL' in s:
            self.log(self.log2, '🎵 检测到音乐信号')
        elif 'AUTOSTOP' in s:
            self.log(self.log2, '歌曲结束，自动停止录音')

    def stop_record(self):
        if self.stop_file:
            open(self.stop_file, 'w').close()
            self.log(self.log2, '⏹ 已请求停止录音…')

    def _done(self):
        self.root.after(0, lambda: self.btn_record.config(state='normal'))
        self.root.after(0, lambda: self.btn_stop.config(state='disabled'))
        self.root.after(0, lambda: self.rec_status.config(text=''))

    def make_lyric(self):
        folder = self.song_folder.get()
        save = self.save_path.get()
        if not os.path.isdir(folder):
            messagebox.showwarning('提示', '请先选择歌曲文件夹')
            return
        if not os.path.isdir(save):
            messagebox.showwarning('提示', '请先选择有效的保存路径')
            return
        self.log3.delete('1.0', 'end')
        self.btn_lyric.config(state='disabled')

        def worker():
            run_script('gen_lrc.py', [folder, save], lambda s: self.log(self.log3, s))
            self.root.after(0, lambda: self.btn_lyric.config(state='normal'))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
