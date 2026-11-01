#!/bin/bash
# 构建 macOS 版「音乐助手.app」三板块应用
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/音乐助手.app"
BIN="$APP/Contents/MacOS/音乐助手"
RES="$APP/Contents/Resources"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES"

swiftc -O "$DIR/main_combined.swift" -o "$BIN" 2>&1 | grep -v "warning:" || true

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>音乐助手</string>
    <key>CFBundleDisplayName</key><string>音乐助手</string>
    <key>CFBundleIdentifier</key><string>local.music.assistant</string>
    <key>CFBundleExecutable</key><string>音乐助手</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>NSMicrophoneUsageDescription</key><string>需要使用虚拟声卡录制歌曲音频，用于制作去人声伴奏（不会录制真实麦克风声音）</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
</dict>
</plist>
EOF

cp "$DIR/record.py" "$DIR/segment.py" "$DIR/normalize.py" "$DIR/gen_lrc.py" "$RES/"
cp "$DIR/AppIcon.icns" "$RES/" 2>/dev/null || true

echo "BUILD OK: $APP"
