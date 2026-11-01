# 音乐伴奏助力 🎵

一键制作「去人声伴奏」+「标准 LRC 歌词」的桌面工具，支持 macOS 和 Windows。

## 功能（三板块）

| 板块 | 功能 | 说明 |
|---|---|---|
| ① QQ音乐下载查询 | 一键打开 QQ音乐 下载目录 | 找到 .mflac / .mgg 歌曲文件 |
| ② 制作伴奏 | 录制系统声音 + AI 消人声 | 生成 `伴奏.wav` + `人声.wav` |
| ③ 识别歌词 | 联网查歌词 + 精准对齐时间戳 | 生成标准 LRC（全民K歌可直接上传） |

## 目录结构

```
音乐伴奏助力/
├── macos/            # macOS 版（Swift 界面）
│   ├── main_combined.swift   # 主界面（三板块）
│   ├── build.sh              # 构建脚本
│   ├── record.py             # 录音（BlackHole 虚拟声卡）
│   ├── segment.py            # 歌曲分段
│   ├── normalize.py          # 音量标准化
│   ├── gen_lrc.py            # 歌词搜索+对齐
│   └── AppIcon.icns          # 图标
├── windows/          # Windows 版（Python + tkinter 界面）
│   ├── 音乐伴奏助力.py        # 主界面（三板块）
│   ├── record.py             # 录音（WASAPI 回环 / VB-Cable）
│   ├── segment.py            # 歌曲分段
│   ├── normalize.py          # 音量标准化
│   ├── gen_lrc.py            # 歌词搜索+对齐
│   └── requirements.txt      # 依赖
└── README.md
```

## 工作原理

1. **制作伴奏**：录制系统播放的声音（无损内录，不破解加密）→ 用 Meta 开源的 Demucs 模型分离人声 → 输出伴奏 + 人声。
2. **识别歌词**：从文件名识别歌手/歌名 → 网易云音乐搜索歌词 → 用人声文件精准对齐时间戳 → 生成标准 LRC。

## 各平台说明

- **macOS**：见 [macos/README.md](macos/README.md)（需 BlackHole 虚拟声卡）
- **Windows**：见 [windows/README.md](windows/README.md)（需 Python + 依赖，可选 VB-Cable）

## 注意事项

- AI 消音对「现场版（Live）」歌曲可能残留轻微人声尾音，属正常现象
- 首次使用 macOS 版需授权「麦克风」权限（录制虚拟声卡必需）
- 识别歌词需联网
