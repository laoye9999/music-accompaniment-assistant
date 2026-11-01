# 音乐伴奏助力 · Windows 版

三板块工具：① QQ音乐下载查询 ② 制作伴奏 ③ 识别歌词

## 环境准备（首次使用）

1. 安装 Python 3.9 ~ 3.11（[python.org](https://www.python.org/downloads/) 下载，安装时勾选 "Add to PATH"）

2. 安装依赖（在项目目录打开命令行）：
```bat
pip install -r requirements.txt
```

3. 准备「录制系统声音」的通道（二选一）：
   - **Windows 10/11 自带**：本工具会自动使用 WASAPI 回环录音，无需额外设置。
   - **若自动回环不可用**：安装 [VB-Cable 虚拟声卡](https://vb-audio.com/Cable/)，并把系统播放设备设为 `CABLE Input`。

## 使用

```bat
python 音乐伴奏助力.py
```

### ① QQ音乐下载查询
点「打开 QQ音乐下载目录」，自动定位 QQ音乐 的下载文件夹（找不到时手动定位即可）。

### ② 制作伴奏
1. 顶部「选择」设置保存路径
2. 点「开始制作伴奏」
3. 在 QQ音乐 播放歌曲，录完自动停止（约8秒后），或点「停止录音」
4. 自动 AI 消人声 → 生成 `伴奏-日期.wav` + `伴奏-日期-人声.wav`

### ③ 识别歌词
1. 选歌曲文件夹（点「浏览…」）
2. 点「开始识别」
3. 自动联网查找歌词，用人声文件精准对齐 → 生成 `歌名-标准歌词.lrc`

## 打包成 exe（可选）

安装 PyInstaller 后，在项目目录执行：
```bat
pip install pyinstaller
pyinstaller --onefile --windowed --name "音乐伴奏助力" 音乐伴奏助力.py
```
生成的 exe 在 `dist\` 目录。（注意：exe 运行同样需要本机已安装 Python 依赖）
