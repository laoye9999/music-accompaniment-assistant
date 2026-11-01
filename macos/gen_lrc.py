#!/usr/bin/env python3
"""歌词识别后端：从文件名识别歌曲 -> 网易云搜索 -> 抓取带时间戳LRC -> 清洗 -> 对齐 -> 生成标准LRC"""
import sys, os, re, json, wave, urllib.request, urllib.parse

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
HEADERS = {'User-Agent': UA, 'Referer': 'https://music.163.com'}
AUDIO_EXT = ('.mflac', '.mgg', '.qmc', '.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.aiff', '.aif')
META_KEYS = ('作词', '作曲', '演唱', '原唱', '总监', '制作', '编曲', '混音', '弦乐', '吉他', '键盘',
             '贝斯', '鼓', '打击乐', '和音', 'PGM', '统筹', '舞台', '音响', '设计', '改编', '母带',
             '录音', '监制', '出品', '发行', '词：', '曲：')

def log(s):
    print(s, flush=True)

def http_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8'))

def parse_filename(name):
    base = re.sub(r'\.(mflac|mgg|qmc\d*|mp3|m4a|wav|flac|aac|ogg|aiff|aif)$', '', name, flags=re.I)
    sep = '-' if '-' in base else ('－' if '－' in base else None)
    if sep:
        artist, title = base.split(sep, 1)
    else:
        artist, title = '', base
    # 去掉伴奏/人声等后缀词
    title = re.sub(r'[（(]?(伴奏|纯音乐|消音|无人声|instrumental|人声|vocals)[)）]?$', '', title, flags=re.I).strip()
    title = re.sub(r'\s*\(?live\)?\s*$', '', title, flags=re.I).strip()
    return artist.strip(), title.strip()

def _search_once(q):
    url = 'https://music.163.com/api/search/get/web?' + urllib.parse.urlencode(
        {'s': q, 'type': 1, 'limit': 10, 'offset': 0})
    d = http_json(url)
    r = d.get('result')
    return r.get('songs', []) if isinstance(r, dict) else []

def search_song(artist, title):
    # 多个查询组合搜索，合并去重，避免单一查询漏掉正确结果
    queries = []
    if artist:
        queries.append(f'{title} {artist}')
        for a in re.split(r'[,，/、&]', artist):
            a = a.strip()
            if a:
                queries.append(f'{title} {a}')
    queries.append(title)
    seen = {}
    for q in queries:
        try:
            for s in _search_once(q):
                seen[s['id']] = s
        except Exception as e:
            log(f'搜索失败({q}): {e}')
    return list(seen.values())

def score(song, artist, title):
    s = 0
    nm = (song.get('name') or '').lower()
    tt = title.lower()
    if tt and tt in nm:
        s += 6
    elif tt and re.sub(r'[（(].*?[)）]', '', nm).strip() == tt:
        s += 5
    # 翻唱/伴奏惩罚
    if 'cover' in nm or '翻唱' in nm or '翻自' in nm or '伴奏' in nm or '纯音乐' in nm:
        s -= 4
    arts = ''.join(a.get('name', '') for a in song.get('artists', []))
    for a in re.split(r'[,，/、&]', artist):
        a = a.strip()
        if a and a in arts:
            s += 4
    return s

def fetch_lrc(song_id):
    url = f'https://music.163.com/api/song/lyric?id={song_id}&lv=-1&kv=-1&tv=-1'
    d = http_json(url)
    return d.get('lrc', {}).get('lyric', '')

def clean_lrc(text):
    lines = []
    for l in text.splitlines():
        m = re.match(r'\[(\d{2}):(\d{2})[.:](\d{1,3})\](.*)', l.strip())
        if not m:
            continue
        mm, ss, cs, txt = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4).strip()
        if not txt:
            continue
        if any(k in txt for k in META_KEYS):
            continue
        if len(cs) == 1:
            cs += '0'
        elif len(cs) == 3:
            cs = cs[:2]
        lines.append((mm * 60 + ss + int(cs) / 100, txt))
    return lines

def format_lrc(lines):
    return '\n'.join(f'[{int(t//60):02d}:{t%60:05.2f}]{txt}' for t, txt in lines)

def first_lyric_time(lines):
    # 第一句真正的歌词（跳过纯歌手标签行，如 王赫野/合/黄霄雲）
    for t, txt in lines:
        if len(txt) > 4:  # 歌名标签一般很短
            return t
    return lines[0][0] if lines else 0.0

def first_vocal_onset(path):
    import numpy as np
    w = wave.open(path, 'rb')
    sr = w.getframerate()
    n = w.getnframes()
    ch = w.getnchannels()
    d = np.frombuffer(w.readframes(n), dtype='<i2').astype(np.float32)
    w.close()
    if ch >= 2:
        d = d.reshape(-1, ch).mean(axis=1)
    d = d / 32768.0
    win = int(sr * 0.02)
    nn = len(d) // win
    env = np.sqrt((d[:nn * win].reshape(nn, win) ** 2).mean(axis=1))
    env = np.convolve(env, np.ones(5) / 5, mode='same')
    thr = max(env.max() * 0.02, 0.0003)
    for i, e in enumerate(env):
        if e > thr:
            return i * 0.02
    return None

def run_demucs(song_path, workdir):
    sub = __import__('subprocess')
    outdir = os.path.join(workdir, 'demucs_out')
    r = sub.run(['/usr/bin/python3', '-m', 'demucs', '--two-stems=vocals', '-d', 'cpu',
                 '-o', outdir, song_path], capture_output=True, text=True, timeout=3600)
    base = os.path.splitext(os.path.basename(song_path))[0]
    vp = os.path.join(outdir, 'htdemucs', base, 'vocals.wav')
    return vp if os.path.exists(vp) else None

def find_file(folder, keywords, exts=AUDIO_EXT):
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(exts) and any(k in f for k in keywords):
            return os.path.join(folder, f)
    return None

def main():
    if len(sys.argv) < 3:
        print('用法: gen_lrc.py <歌曲文件夹> <输出目录>')
        sys.exit(2)
    folder, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    # 1. 找歌曲文件（优先mflac等主文件，跳过伴奏/人声/歌词）
    files = [f for f in os.listdir(folder)
             if f.lower().endswith(AUDIO_EXT) and not os.path.isdir(os.path.join(folder, f))]
    song_file = None
    for f in files:
        if not re.search(r'(伴奏|纯音乐|消音|无人声|instrumental|人声|vocals)', f, re.I):
            song_file = os.path.join(folder, f)
            break
    if not song_file:
        log('❌ 未在文件夹中找到歌曲文件')
        sys.exit(1)
    log(f'识别到歌曲文件: {os.path.basename(song_file)}')

    # 2. 解析歌手/歌名
    artist, title = parse_filename(os.path.basename(song_file))
    log(f'解析: 歌手="{artist}" 歌名="{title}"')
    if not title:
        log('❌ 无法从文件名解析歌名')
        sys.exit(1)

    # 3. 搜索
    log('🔍 正在联网搜索歌词…')
    songs = search_song(artist, title)
    if not songs:
        log('❌ 未搜索到结果')
        sys.exit(1)
    songs.sort(key=lambda s: score(s, artist, title), reverse=True)
    best = songs[0]
    best_name = best['name']
    best_arts = '/'.join(a['name'] for a in best.get('artists', []))
    log(f'最佳匹配: {best_name} - {best_arts}')

    # 4. 抓取LRC
    lrc_text = fetch_lrc(best['id'])
    lines = clean_lrc(lrc_text)
    if not lines:
        log('❌ 该歌曲没有可用的歌词')
        sys.exit(1)
    log(f'获取到 {len(lines)} 句歌词')

    # 5. 对齐：在 歌曲文件夹 / 保存路径 / 上一级文件夹 里找「人声」文件（取最新的）
    offset = 0.0
    aligned = False
    search_dirs = []
    for d in (folder, outdir, os.path.dirname(folder.rstrip('/'))):
        if d and os.path.isdir(d) and d not in search_dirs:
            search_dirs.append(d)
    vocal_candidates = []
    for d in search_dirs:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if os.path.isfile(p) and f.lower().endswith(AUDIO_EXT) \
               and re.search(r'(人声|vocals|vocal)', f, re.I):
                vocal_candidates.append(p)
    if vocal_candidates:
        vocal_file = max(vocal_candidates, key=os.path.getmtime)  # 最近的人声文件
        log(f'找到人声文件: {os.path.basename(vocal_file)}')
    else:
        vocal_file = None

    if not vocal_file:
        # 尝试用完整歌曲做demucs分离人声
        full = None
        for f in files:
            if not re.search(r'(伴奏|纯音乐|消音|无人声|instrumental|人声|vocals)', f, re.I) \
               and f.lower().endswith(('.mp3', '.m4a', '.wav', '.flac', '.aac')):
                full = os.path.join(folder, f)
                break
        if full:
            log('🧠 检测到完整歌曲，正在分离人声以精确对齐…')
            work = '/tmp/lyric-work-' + str(int(__import__('time').time()))
            os.makedirs(work, exist_ok=True)
            vp = run_demucs(full, work)
            if vp:
                vocal_file = vp

    if vocal_file:
        onset = first_vocal_onset(vocal_file)
        if onset is not None:
            ref = first_lyric_time(lines)
            offset = onset - ref
            aligned = True
            log(f'🎯 精确对齐：第一句人声在 {onset:.2f}s，偏移 {offset:+.2f}s')

    if offset:
        lines = [(max(0.0, t + offset), txt) for t, txt in lines]

    # 6. 生成并保存
    out_name = f'{title}-标准歌词.lrc'
    out_path = os.path.join(outdir, out_name)
    with open(out_path, 'w', encoding='utf-8') as fp:
        fp.write(format_lrc(lines) + '\n')

    if not aligned and not offset:
        if vocal_file:
            log('⚠️ 人声文件是静音（伴奏可能没录完整），无法对齐，使用网络歌词原始时间')
        else:
            log('⚠️ 未找到人声/完整歌曲，使用网络歌词原始时间（可能与伴奏有偏差）')
    log(f'✅ 完成！已保存: {out_path}')

if __name__ == '__main__':
    main()
