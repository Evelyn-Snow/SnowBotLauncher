"""使用说明页。"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit

from snowbot.core.paths import APP_DIR, APP_VERSION, BACKUPS_DIR, DATA_DIR, LOG_DIR, PACKS_DIR


class AboutMixin:
    def _build_about_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            'font-family: "Microsoft YaHei UI"; font-size: 13px; color:#cbd5e1;'
            "background: #0a1020; border: 1px solid #1c2740; border-radius: 12px;"
        )
        snow = str(self.cfg.get("qq_backend") or "napcat") == "snowluma"
        proto = "SnowLuma" if snow else "NapCat"
        proto_port = (
            self.cfg.get("snowluma_webui_port", 5099)
            if snow
            else self.cfg["napcat_port"]
        )
        proto_dir = (
            self.cfg.get("snowluma_dir", "") if snow else self.cfg["napcat_dir"]
        )
        proto_account = (
            "自动读取 config/onebot_<QQ>.json"
            if snow
            else "自动读取 config/webui.json，可在控制台复制"
        )
        proto_log = (
            "SnowLuma → 控制台日志标签页"
            if snow
            else r"NapCat → NapCat.Shell\logs\*.log"
        )
        text.setPlainText(
            f"""SnowBotLauncher v{APP_VERSION}

一、日常使用
  1. 点击「一键启动全部」：先启动 AstrBot（约 5~10 秒），随后拉起 {proto} 与 QQ。
  2. 首次或掉线时，在弹出的 QQ 窗口扫码登录；{proto} 会自动连接 AstrBot。
  3. 点击「打开面板」进入 AstrBot WebUI 配置大模型、插件等。
  4. 关闭窗口默认挂起到系统托盘，服务继续在后台运行。

二、地址与账号
  AstrBot WebUI   http://localhost:{self.cfg['dashboard_port']}
  AstrBot 账号    自动读取 AstrBot 的 dashboard.username（密码按实际填写）
  {proto} WebUI    http://127.0.0.1:{proto_port}
  {proto} 账号    {proto_account}
  OneBot 地址     ws://127.0.0.1:{self.cfg['onebot_port']}/ws（{proto} 作为 WS 客户端连接）

三、配置包
  · 「配置包」页可导入并应用 SnowBot Pack：人格、插件、模型、语音、表情包等一键配置。
  · 每个包用变量表自定义（所有者 QQ、记忆方式、语音方案、密钥等），可预览计划后再执行。
  · 应用前自动备份 AstrBot 配置，可在「还原备份」中回滚；支持重复执行（已完成的跳过）。
  · 兼容大肥鱼等旧版 pack.json 配置包，会以「脚本步骤」方式调用其导入器。
  · 配置包目录：{PACKS_DIR}
  · 备份目录：{BACKUPS_DIR}

四、增强配置
  · 人格：读取/新建/编辑/删除人格，设为默认，导入 Markdown。
  · 表情包：meme_manager 资源广场索引、按 pack_id 下载、默认套装、多套同时使用、GitHub 加速地址。
  · 语音：Edge TTS / MiMo 克隆 / 豆包 Seed Audio，保存前自动测试，可调触发概率。
  · 记忆：本机 Ollama / 硅基流动 / 自定义 OpenAI 兼容 Embedding，自动接入 LivingMemory 插件。
  · 视觉：上下文视觉模型 / 图片描述模式，可选择是否在图片轮次保留工具调用。
  · 存储：自定义记忆文件（Obsidian）和图片图库目录，并可打开语义记忆数据库位置。
  · 群聊：读空气开关、生效群白名单、连聊/反戳概率、@空消息回询与群聊记忆捕获。
  · 搜索：联网查证开关、搜索源 Key、自发搜索频率；明确要求必搜并附来源。
  · 这些操作直接调 AstrBot 后台接口，使用前需在页面顶部连接（密码只保留在本次运行内存中）。

五、后台与自启
  · 「后台挂起」或关闭窗口：隐藏到托盘，服务不中断。
  · 托盘菜单可启动/停止全部、恢复窗口、退出。
  · 设置页可开启开机自启（写入 Windows 计划任务，登录后自动运行且免 UAC）。
  · 还可开启「启动控制台后自动启动全部服务」，配合开机自启即可无人值守挂机。
  · 退出控制台不会自动停止服务；如需停止请用「停止全部」或托盘菜单。

六、常见问题
  · {proto} 启动失败：确认以管理员身份运行；检查 QQ 是否已安装。
  · 面板打不开：查看下方 AstrBot 日志是否报错，检查端口是否被占用。
  · 机器人不回复：AstrBot 中尚未配置大模型服务商，或未设为默认。
  · 配置包应用失败：先预览计划，确认 AstrBot 已启动、账号密码正确、目标插件版本匹配。
  · 增强配置登录失败：账号可能是自定义的（可在 AstrBot 的 data/cmd_config.json 查看 dashboard.username）。
  · 日志：AstrBot → {LOG_DIR}\\astrbot.log；{proto_log}

七、目录
  程序    {APP_DIR}
  数据    {DATA_DIR}
  AstrBot {self.cfg['astrbot_dir']}
  {proto}  {proto_dir}
"""
        )
        layout.addWidget(text)
        return page
