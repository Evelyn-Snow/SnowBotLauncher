"""使用说明页。"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QThread, Signal
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QBrush, QFont, QLinearGradient,
    QAction, QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QGridLayout, QPlainTextEdit, QTabWidget, QLineEdit,
    QCheckBox, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QScrollArea,
    QSpinBox, QGroupBox, QFormLayout, QSizePolicy, QSpacerItem, QToolButton,
    QListWidget, QListWidgetItem, QSplitter, QProgressBar, QComboBox, QInputDialog,
)

from snowbot.core.paths import (
    APP_DIR, APP_VERSION, BACKUPS_DIR, DATA_DIR, LOG_DIR, PACKS_DIR,
)


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
        text.setPlainText(
            f"""SnowBotLauncher v{APP_VERSION}

一、日常使用
  1. 点击「一键启动全部」：先启动 AstrBot（约 5~10 秒），随后拉起 NapCat 与 QQ。
  2. 首次或掉线时，在弹出的 QQ 窗口扫码登录；NapCat 会自动连接 AstrBot。
  3. 点击「打开面板」进入 AstrBot WebUI 配置大模型、插件等。
  4. 关闭窗口默认挂起到系统托盘，服务继续在后台运行。

二、地址与账号
  AstrBot WebUI   http://localhost:{self.cfg['dashboard_port']}
  AstrBot 账号    自动读取 AstrBot 的 dashboard.username（密码按实际填写）
  NapCat WebUI    http://127.0.0.1:{self.cfg['napcat_port']}
  NapCat Token    自动读取 config/webui.json，可在控制台复制
  OneBot 地址     ws://127.0.0.1:{self.cfg['onebot_port']}/ws（NapCat 作为 WS 客户端连接）

三、配置包
  · 「配置包」页可导入并应用 SnowBot Pack：人格、插件、模型、语音、表情包等一键配置。
  · 每个包用变量表自定义（主人 QQ、记忆方式、语音方案、密钥等），可预览计划后再执行。
  · 应用前自动备份 AstrBot 配置，可在「还原备份」中回滚；支持重复执行（已完成的跳过）。
  · 兼容大肥鱼等旧版 pack.json 配置包，会以「脚本步骤」方式调用其导入器。
  · 配置包目录：{PACKS_DIR}
  · 备份目录：{BACKUPS_DIR}

四、增强配置
  · 人格：读取/新建/编辑/删除人格，设为默认，导入 Markdown。
  · 表情包：meme_manager 资源广场索引、按 pack_id 下载、默认套装、多套同时使用、GitHub 加速地址。
  · 语音：Edge TTS / MiMo 克隆 / 豆包 Seed Audio，保存前自动测试，可调触发概率。
  · 记忆：本机 Ollama / 硅基流动 / 自定义 OpenAI 兼容 Embedding，自动接入 LivingMemory 插件。
  · 这些操作直接调 AstrBot 后台接口，使用前需在页面顶部连接（密码只保留在本次运行内存中）。

五、后台与自启
  · 「后台挂起」或关闭窗口：隐藏到托盘，服务不中断。
  · 托盘菜单可启动/停止全部、恢复窗口、退出。
  · 设置页可开启开机自启（写入 Windows 计划任务，登录后自动运行且免 UAC）。
  · 还可开启「启动控制台后自动启动全部服务」，配合开机自启即可无人值守挂机。
  · 退出控制台不会自动停止服务；如需停止请用「停止全部」或托盘菜单。

六、常见问题
  · NapCat 启动失败：确认以管理员身份运行；检查 QQ 是否已安装。
  · 面板打不开：查看下方 AstrBot 日志是否报错，检查端口是否被占用。
  · 机器人不回复：AstrBot 中尚未配置大模型服务商，或未设为默认。
  · 配置包应用失败：先预览计划，确认 AstrBot 已启动、账号密码正确、目标插件版本匹配。
  · 增强配置登录失败：账号可能是自定义的（可在 AstrBot 的 data/cmd_config.json 查看 dashboard.username）。
  · 日志：AstrBot → {LOG_DIR}\\astrbot.log；NapCat → NapCat.Shell\\logs\\*.log

七、目录
  程序    {APP_DIR}
  数据    {DATA_DIR}
  AstrBot {self.cfg['astrbot_dir']}
  NapCat  {self.cfg['napcat_dir']}
"""
        )
        layout.addWidget(text)
        return page

    # ---------------- 配置包 ----------------
