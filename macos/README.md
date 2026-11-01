# 音乐伴奏助力 · macOS 版

三板块工具：① QQ音乐下载查询 ② 制作伴奏 ③ 识别歌词

## 环境准备（首次使用）

1. **BlackHole 虚拟声卡**：用于录制系统声音（内录），到 [existential.audio](https://existential.audio/) 免费下载安装。
2. **Python 3 + 依赖**：
```bash
/usr/bin/python3 -m pip install --user "numpy==1.26.4" sounddevice
/usr/bin/python3 -m pip install --user torch torchaudio demucs
# 国内网络可加清华镜像：-i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 构建 app

```bash
cd macos
chmod +x build.sh
./build.sh
```
生成 `音乐助手.app`，双击即可运行。

## 使用

### ① QQ音乐下载查询
点「打开 QQ音乐下载目录」，直达 QQ音乐 的下载文件夹。

### ② 制作伴奏
1. 顶部「选择保存路径」设置成品位置
2. 点「开始制作伴奏」
3. 首次会弹「访问麦克风」→ 点【允许】
4. 程序自动退出 QQ音乐 → 重新打开 QQ音乐播放歌曲
5. 歌曲结束约8秒自动停止 → 自动 AI 消人声 → 生成 `伴奏-日期.wav` + `人声.wav`

### ③ 识别歌词
1. 点「浏览…」选歌曲文件夹 → 点「开始识别」
2. 自动联网查找歌词，用人声文件精准对齐 → 生成 `歌名-标准歌词.lrc`

## 说明

- 制作伴奏期间电脑暂时没声音，处理完自动恢复
- AI 消音约需 3-15 分钟
- 首次使用需授权麦克风权限
