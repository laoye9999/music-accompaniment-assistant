import AppKit
import CoreAudio

// MARK: - 音频设备控制

func audioAddr(_ sel: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func allDevices() -> [AudioDeviceID] {
    var a = audioAddr(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    let sys = AudioObjectID(kAudioObjectSystemObject)
    guard AudioObjectGetPropertyDataSize(sys, &a, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(sys, &a, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

func deviceName(_ id: AudioDeviceID) -> String {
    var name: CFString = "" as CFString
    var a = audioAddr(kAudioDevicePropertyDeviceNameCFString)
    var size = UInt32(MemoryLayout.size(ofValue: name))
    let e = AudioObjectGetPropertyData(id, &a, 0, nil, &size, &name)
    return e == noErr ? (name as String) : ""
}

func findDevice(_ target: String) -> AudioDeviceID? {
    allDevices().first { deviceName($0) == target }
}

func currentDefault(_ sel: AudioObjectPropertySelector) -> AudioDeviceID? {
    var a = audioAddr(sel)
    var id = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size, &id) == noErr else { return nil }
    return id
}

func setDefault(_ id: AudioDeviceID, _ sel: AudioObjectPropertySelector) -> Bool {
    var a = audioAddr(sel)
    var dev = id
    let size = UInt32(MemoryLayout<AudioDeviceID>.size)
    return AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, size, &dev) == noErr
}

@discardableResult
func runSync(_ exe: String, _ args: [String]) -> (code: Int32, out: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    try? p.run()
    p.waitUntilExit()
    let d = pipe.fileHandleForReading.readDataToEndOfFile()
    return (p.terminationStatus, String(data: d, encoding: .utf8) ?? "")
}

func systemVolume() -> Int {
    let r = runSync("/usr/bin/osascript", ["-e", "output volume of (get volume settings)"])
    return Int(r.out.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 85
}

func setSystemVolume(_ v: Int) {
    _ = runSync("/usr/bin/osascript", ["-e", "set volume output volume \(v)"])
}

func resPath(_ name: String) -> String {
    if let r = Bundle.main.resourceURL?.appendingPathComponent(name).path, FileManager.default.fileExists(atPath: r) {
        return r
    }
    let bin = CommandLine.arguments[0]
    return (bin as NSString).deletingLastPathComponent + "/../Resources/" + name
}

func blackholeInstalled() -> Bool {
    FileManager.default.fileExists(atPath: "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver")
}

func pythonDepsOK() -> Bool {
    runSync("/usr/bin/python3", ["-c", "import demucs, torch, sounddevice, soundfile"]).code == 0
}

// MARK: - 伴奏制作流水线

final class Pipeline {
    var logFn: (String) -> Void = { _ in }
    var recStatusFn: (String) -> Void = { _ in }
    var runningFn: (Bool) -> Void = { _ in }
    var doneFn: (URL?) -> Void = { _ in }
    var outputDir: URL = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Desktop")

    var origOutName = ""
    var origSysName = ""
    var origVol = 85
    var switched = false
    var stopFilePath = ""

    func log(_ s: String) { logFn(s) }

    func restoreAudio() {
        if switched {
            if let d = findDevice(origOutName) { _ = setDefault(d, kAudioHardwarePropertyDefaultOutputDevice) }
            if let d = findDevice(origSysName) { _ = setDefault(d, kAudioHardwarePropertyDefaultSystemOutputDevice) }
            switched = false
        }
        setSystemVolume(origVol)
    }

    func fail(_ msg: String) {
        log("❌ \(msg)")
        restoreAudio()
        log("🔊 声音已恢复")
        runningFn(false)
        doneFn(nil)
    }

    func run() {
        runningFn(true)
        log("▶ 开始制作伴奏（录音模式）")

        guard let bh = findDevice("BlackHole 2ch") else {
            fail("未检测到 BlackHole 虚拟声卡。请先到 existential.audio 下载安装")
            return
        }

        origOutName = currentDefault(kAudioHardwarePropertyDefaultOutputDevice).map(deviceName) ?? ""
        origSysName = currentDefault(kAudioHardwarePropertyDefaultSystemOutputDevice).map(deviceName) ?? ""
        origVol = systemVolume()

        guard setDefault(bh, kAudioHardwarePropertyDefaultOutputDevice),
              setDefault(bh, kAudioHardwarePropertyDefaultSystemOutputDevice) else {
            fail("切换虚拟声卡失败")
            return
        }
        switched = true
        setSystemVolume(90)
        log("🔇 声音已切到虚拟声卡（电脑暂时没声音，属正常）")

        let workDir = URL(fileURLWithPath: "/tmp/voiceoff-work-\(Int(Date().timeIntervalSince1970))")
        try? FileManager.default.createDirectory(at: workDir, withIntermediateDirectories: true)
        let recOut = workDir.appendingPathComponent("recording.wav").path
        stopFilePath = workDir.appendingPathComponent("stop").path
        try? FileManager.default.removeItem(atPath: stopFilePath)

        _ = runSync("/usr/bin/osascript", ["-e", "tell application \"QQMusic\" to quit"])
        log("已退出 QQ音乐")

        var hadSignal = false

        let rec = Process()
        rec.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        rec.arguments = [resPath("record.py"), recOut, stopFilePath, "1200", "1"]
        let rp = Pipe()
        rec.standardOutput = rp
        rec.standardError = rp
        rp.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty, let self else { return }
            for line in (String(data: d, encoding: .utf8) ?? "").split(separator: "\n") {
                let l = String(line)
                if l.contains("SIGNAL_STARTED") {
                    hadSignal = true
                    self.log("🎵 检测到音乐信号")
                } else if l.contains("AUTOSTOP") {
                    self.log("歌曲结束，自动停止录音")
                } else if l.hasPrefix("PROGRESS") {
                    self.recStatusFn(l)
                }
            }
        }
        try? rec.run()
        log("👉 请重新打开 QQ音乐 并播放歌曲（结束后约8秒自动停止）")
        rec.waitUntilExit()

        restoreAudio()
        log("🔊 已恢复正常声音")
        recStatusFn("")

        guard hadSignal else {
            fail("录音中没有检测到声音。请确认已授予麦克风权限、并重新打开 QQ音乐 播放")
            return
        }
        guard FileManager.default.fileExists(atPath: recOut) else {
            fail("录音文件缺失")
            return
        }

        log("✂️ 分析音频，裁剪出歌曲…")
        let segPrefix = workDir.appendingPathComponent("seg").path
        let seg = runSync("/usr/bin/python3", [resPath("segment.py"), recOut, segPrefix])
        let songPath = segPrefix + "_seg0.wav"
        guard FileManager.default.fileExists(atPath: songPath) else {
            fail("未能在录音中识别出歌曲：\(seg.out)")
            return
        }

        log("🧠 AI 分离人声中…（约 3-15 分钟，取决于歌曲时长）")
        let dmp = Process()
        dmp.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        dmp.arguments = ["-m", "demucs", "--two-stems=vocals", "-d", "cpu",
                         "-o", workDir.appendingPathComponent("demucs_out").path, songPath]
        let dp = Pipe()
        dmp.standardOutput = dp
        dmp.standardError = dp
        dp.fileHandleForReading.readabilityHandler = { h in _ = h.availableData }
        try? dmp.run()
        dmp.waitUntilExit()

        let songBase = ((songPath as NSString).lastPathComponent as NSString).deletingPathExtension
        let noVocals = workDir.appendingPathComponent("demucs_out/htdemucs/\(songBase)/no_vocals.wav").path
        guard dmp.terminationStatus == 0, FileManager.default.fileExists(atPath: noVocals) else {
            fail("AI 分离失败（请重试）")
            return
        }

        log("💾 保存成品…")
        let df = DateFormatter()
        df.dateFormat = "yyyy年MM月dd日"
        let base = "伴奏-\(df.string(from: Date()))"
        var finalPath = outputDir.appendingPathComponent(base + ".wav").path
        if FileManager.default.fileExists(atPath: finalPath) {
            let tf = DateFormatter()
            tf.dateFormat = "HHmmss"
            finalPath = outputDir.appendingPathComponent(base + "-\(tf.string(from: Date())).wav").path
        }
        let norm = runSync("/usr/bin/python3", [resPath("normalize.py"), noVocals, finalPath])
        log(norm.out)

        let finalBase = ((finalPath as NSString).lastPathComponent as NSString).deletingPathExtension
        let vocalsSrc = workDir.appendingPathComponent("demucs_out/htdemucs/\(songBase)/vocals.wav").path
        let vocalsOut = outputDir.appendingPathComponent(finalBase + "-人声.wav").path
        if FileManager.default.fileExists(atPath: vocalsSrc) {
            try? FileManager.default.removeItem(atPath: vocalsOut)
            try? FileManager.default.copyItem(atPath: vocalsSrc, toPath: vocalsOut)
            log("🎤 已保存人声轨: \(finalBase)-人声.wav（用于歌词对齐）")
        }

        log("✅ 完成！伴奏已保存：\n\(finalPath)")
        runningFn(false)
        doneFn(URL(fileURLWithPath: finalPath))
    }

    func stopRecording() {
        if !stopFilePath.isEmpty {
            FileManager.default.createFile(atPath: stopFilePath, contents: nil)
        }
    }
}

// MARK: - 界面

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var saveField: NSTextField!
    var saveDir: URL = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Desktop")

    // 伴奏板块
    var startBtn: NSButton!
    var stopBtn: NSButton!
    var spinner1: NSProgressIndicator!
    var recLabel: NSTextField!
    var log1: NSTextView!
    var pipeline = Pipeline()
    var recRunning = false

    // 歌词板块
    var folderField: NSTextField!
    var identifyBtn: NSButton!
    var spinner2: NSProgressIndicator!
    var log2: NSTextView!
    var songFolder: URL?
    var lyricRunning = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        saveDir = Bundle.main.bundleURL.deletingLastPathComponent()
        pipeline.outputDir = saveDir
        buildUI()
        pipeline.logFn = { [weak self] s in self?.append1(s) }
        pipeline.recStatusFn = { [weak self] s in
            DispatchQueue.main.async {
                guard let self else { return }
                if s.isEmpty { self.recLabel.stringValue = "" }
                else {
                    var time = "--"; var level = "--"
                    for pp in s.split(separator: " ") {
                        if pp.hasPrefix("t=") { time = String(pp.dropFirst(2)) + "s" }
                        if pp.hasPrefix("rms=") { level = String(pp.dropFirst(4)) }
                    }
                    self.recLabel.stringValue = "录音中… 已录 \(time)｜电平 \(level)"
                }
            }
        }
        pipeline.runningFn = { [weak self] running in
            DispatchQueue.main.async { self?.setRecRunning(running) }
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        checkEnvironment()
    }

    func buildUI() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "音乐助手（下载 + 伴奏 + 歌词）"
        window.center()

        let root = NSView()
        window.contentView = root

        let title = NSTextField(labelWithString: "音乐助手")
        title.font = .boldSystemFont(ofSize: 19)

        // 共享保存路径
        saveField = NSTextField()
        saveField.isEditable = false
        saveField.stringValue = saveDir.path
        let saveBtn = NSButton(title: "选择保存路径", target: self, action: #selector(chooseSaveDir))
        let revealBtn = NSButton(title: "在访达中显示", target: self, action: #selector(revealSave))
        let saveRow = NSStackView(views: [saveField, saveBtn, revealBtn])
        saveRow.orientation = .horizontal
        saveRow.spacing = 8
        saveField.widthAnchor.constraint(equalTo: saveRow.widthAnchor, constant: -240).isActive = true

        // ===== 板块1：QQ音乐下载 =====
        let sec0Title = NSTextField(labelWithString: "① QQ音乐下载查询")
        sec0Title.font = .boldSystemFont(ofSize: 14)
        sec0Title.textColor = .systemOrange
        let qqHint = NSTextField(labelWithString: "一键打开 QQ音乐 的下载目录，找到你下载的 .mflac/.mgg 歌曲文件")
        qqHint.font = .systemFont(ofSize: 11)
        qqHint.textColor = .secondaryLabelColor
        let qqBtn = NSButton(title: "打开 QQ音乐下载目录", target: self, action: #selector(openQQFolder))
        qqBtn.bezelStyle = .rounded
        let qqRow = NSStackView(views: [qqBtn, qqHint])
        qqRow.orientation = .horizontal
        qqRow.spacing = 10
        let sep0 = NSBox()
        sep0.boxType = .separator

        // ===== 板块2：伴奏制作 =====
        let sec1Title = NSTextField(labelWithString: "② 制作伴奏")
        sec1Title.font = .boldSystemFont(ofSize: 14)
        sec1Title.textColor = .systemBlue

        startBtn = NSButton(title: "开始制作伴奏", target: self, action: #selector(start))
        startBtn.bezelStyle = .rounded
        stopBtn = NSButton(title: "停止录音", target: self, action: #selector(stopRec))
        stopBtn.bezelStyle = .rounded
        stopBtn.isHidden = true
        spinner1 = NSProgressIndicator()
        spinner1.style = .spinning
        spinner1.isDisplayedWhenStopped = false
        let btn1Row = NSStackView(views: [startBtn, stopBtn, spinner1])
        btn1Row.orientation = .horizontal
        btn1Row.spacing = 12

        recLabel = NSTextField(labelWithString: "")
        recLabel.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        recLabel.textColor = .systemBlue

        let scroll1 = NSScrollView()
        scroll1.hasVerticalScroller = true
        scroll1.borderType = .bezelBorder
        log1 = NSTextView()
        log1.isEditable = false
        log1.font = .systemFont(ofSize: 11)
        log1.textContainerInset = NSSize(width: 6, height: 6)
        scroll1.documentView = log1

        let sep1 = NSBox()
        sep1.boxType = .separator

        // ===== 板块3：歌词识别 =====
        let sec2Title = NSTextField(labelWithString: "③ 识别歌词")
        sec2Title.font = .boldSystemFont(ofSize: 14)
        sec2Title.textColor = .systemGreen

        folderField = NSTextField()
        folderField.placeholderString = "选择歌曲存放的文件夹（放 .mflac 等歌曲文件）"
        folderField.isEditable = false
        let browseBtn = NSButton(title: "浏览…", target: self, action: #selector(browseFolder))
        identifyBtn = NSButton(title: "开始识别", target: self, action: #selector(identify))
        identifyBtn.bezelStyle = .rounded
        spinner2 = NSProgressIndicator()
        spinner2.style = .spinning
        spinner2.isDisplayedWhenStopped = false
        let folderRow = NSStackView(views: [folderField, browseBtn])
        folderRow.orientation = .horizontal
        folderRow.spacing = 8
        folderField.widthAnchor.constraint(equalTo: folderRow.widthAnchor, constant: -90).isActive = true
        let btn2Row = NSStackView(views: [identifyBtn, spinner2])
        btn2Row.orientation = .horizontal
        btn2Row.spacing = 12

        let scroll2 = NSScrollView()
        scroll2.hasVerticalScroller = true
        scroll2.borderType = .bezelBorder
        log2 = NSTextView()
        log2.isEditable = false
        log2.font = .systemFont(ofSize: 11)
        log2.textContainerInset = NSSize(width: 6, height: 6)
        scroll2.documentView = log2

        let stack = NSStackView(views: [title, saveRow,
                                        sec0Title, qqRow, sep0,
                                        sec1Title, btn1Row, recLabel, scroll1, sep1,
                                        sec2Title, folderRow, btn2Row, scroll2])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: root.topAnchor, constant: 16),
            stack.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16),
            stack.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16),
            stack.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -16),
            saveRow.widthAnchor.constraint(equalTo: stack.widthAnchor),
            qqRow.widthAnchor.constraint(equalTo: stack.widthAnchor),
            sep0.widthAnchor.constraint(equalTo: stack.widthAnchor),
            btn1Row.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll1.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll1.heightAnchor.constraint(greaterThanOrEqualToConstant: 100),
            sep1.widthAnchor.constraint(equalTo: stack.widthAnchor),
            folderRow.widthAnchor.constraint(equalTo: stack.widthAnchor),
            btn2Row.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll2.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll2.heightAnchor.constraint(greaterThanOrEqualToConstant: 100),
        ])

        append1("板块②：点「开始制作伴奏」→ 按提示在 QQ音乐 播放歌曲 → 生成伴奏+人声。")
        append2("板块③：选歌曲文件夹 → 点「开始识别」→ 自动联网查找并生成标准 LRC。")
    }

    // MARK: 共享

    @objc func chooseSaveDir() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.message = "选择成品保存的文件夹"
        panel.begin { [weak self] resp in
            guard resp == .OK, let url = panel.url else { return }
            self?.saveDir = url
            self?.saveField.stringValue = url.path
        }
    }

    @objc func revealSave() {
        NSWorkspace.shared.activateFileViewerSelecting([saveDir])
    }

    @objc func openQQFolder() {
        let qqPath = NSHomeDirectory() + "/Library/Containers/com.tencent.QQMusicMac/Data/Library/Application Support/QQMusicMac/iQmc"
        if FileManager.default.fileExists(atPath: qqPath) {
            NSWorkspace.shared.open(URL(fileURLWithPath: qqPath))
        } else {
            let a = NSAlert()
            a.messageText = "未找到 QQ音乐下载目录"
            a.informativeText = "请确认已安装 QQ音乐 Mac 版"
            a.alertStyle = .warning
            a.runModal()
        }
    }

    // MARK: 板块1 伴奏

    @objc func start() {
        guard !recRunning else { return }
        if !blackholeInstalled() {
            append1("⚠️ 缺少 BlackHole 虚拟声卡（录音必需），正在自动下载…")
            downloadBlackHole()
            return
        }
        if !pythonDepsOK() {
            append1("⚠️ 缺少 AI 依赖（demucs/torch），正在自动安装（首次约 5-10 分钟）…")
            installPythonDeps()
            return
        }
        clearLog(log1)
        pipeline.outputDir = saveDir
        recRunning = true
        stopBtn.isHidden = false
        spinner1.startAnimation(nil)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.pipeline.run()
        }
    }

    @objc func stopRec() {
        pipeline.stopRecording()
        append1("⏹ 已请求停止录音…")
    }

    // MARK: 环境自动检查与修复

    func checkEnvironment() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            if blackholeInstalled() {
                self.append1("✅ BlackHole 虚拟声卡：已安装")
            } else {
                self.append1("⚠️ 未检测到 BlackHole 虚拟声卡，正在自动下载…")
                self.downloadBlackHole()
            }
            if pythonDepsOK() {
                self.append1("✅ AI 依赖（demucs/torch）：已就绪")
            } else {
                self.append1("⚠️ 未检测到 AI 依赖，正在自动安装（首次约 5-10 分钟）…")
                self.installPythonDeps()
            }
        }
    }

    func downloadBlackHole() {
        let dest = NSHomeDirectory() + "/Downloads/BlackHole2ch-0.7.1.pkg"
        let url = "https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg"
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let r = runSync("/usr/bin/curl", ["-sL", "--max-time", "300", "-A", "Mozilla/5.0", "-o", dest, url])
            DispatchQueue.main.async {
                if r.code == 0 && FileManager.default.fileExists(atPath: dest) {
                    NSWorkspace.shared.open(URL(fileURLWithPath: dest))
                    self?.append1("✅ 已下载 BlackHole 安装包，请在弹窗中完成安装，装完再点「开始制作伴奏」")
                } else {
                    self?.append1("❌ 下载 BlackHole 失败，请到 existential.audio 手动下载")
                }
            }
        }
    }

    func installPythonDeps() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = ["-m", "pip", "install", "--user",
                           "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                           "numpy==1.26.4", "sounddevice", "soundfile",
                           "torch==2.2.2", "torchaudio==2.2.2", "demucs==4.0.1"]
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            pipe.fileHandleForReading.readabilityHandler = { h in
                let d = h.availableData
                guard let s = String(data: d, encoding: .utf8), !s.isEmpty else { return }
                for line in s.split(separator: "\n") {
                    let l = String(line)
                    if l.contains("Successfully installed") || l.contains("ERROR") || l.contains("error") {
                        DispatchQueue.main.async { self?.append1(l) }
                    }
                }
            }
            try? p.run()
            p.waitUntilExit()
            DispatchQueue.main.async {
                if p.terminationStatus == 0 {
                    self?.append1("✅ 依赖安装完成，现在可以点「开始制作伴奏」了")
                } else {
                    self?.append1("❌ 依赖安装失败，请检查网络后重启应用重试")
                }
            }
        }
    }

    func setRecRunning(_ running: Bool) {
        recRunning = running
        startBtn.isEnabled = !running
        stopBtn.isHidden = !running
        if !running { spinner1.stopAnimation(nil) }
    }

    func append1(_ s: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.log1.textStorage?.append(NSAttributedString(string: s + "\n"))
            self.log1.scrollToEndOfDocument(nil)
        }
    }

    // MARK: 板块2 歌词

    @objc func browseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.message = "选择歌曲存放的文件夹"
        panel.begin { [weak self] resp in
            guard resp == .OK, let url = panel.url else { return }
            self?.songFolder = url
            self?.folderField.stringValue = url.path
        }
    }

    @objc func identify() {
        guard !lyricRunning else { return }
        guard let folder = songFolder, FileManager.default.fileExists(atPath: folder.path) else {
            let a = NSAlert(); a.messageText = "请先选择歌曲文件夹"; a.alertStyle = .warning; a.runModal()
            return
        }
        clearLog(log2)
        lyricRunning = true
        identifyBtn.isEnabled = false
        spinner2.startAnimation(nil)

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        proc.arguments = [resPath("gen_lrc.py"), folder.path, saveDir.path]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty, let self else { return }
            for line in (String(data: d, encoding: .utf8) ?? "").split(separator: "\n") {
                self.append2(String(line))
            }
        }
        proc.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.lyricRunning = false
                self.identifyBtn.isEnabled = true
                self.spinner2.stopAnimation(nil)
            }
        }
        try? proc.run()
    }

    func append2(_ s: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.log2.textStorage?.append(NSAttributedString(string: s + "\n"))
            self.log2.scrollToEndOfDocument(nil)
        }
    }

    func clearLog(_ tv: NSTextView) {
        tv.string = ""
        recLabel.stringValue = ""
    }

    func applicationWillTerminate(_ notification: Notification) {
        pipeline.restoreAudio()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
