"""增强配置页的「扩展插件」分栏：本机自研插件的状态与一键安装。

安装策略：先按插件 metadata 里的 repo 走 AstrBot 插件市场（服务端从 GitHub 拉），
失败（未上架、网络不通）自动回退为把启动器随包分发的本地插件 zip 上传安装。
"""

from __future__ import annotations

from .common import (
    ApiError,
    APP_DIR,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
    zip_folder,
)

EXT_PLUGINS = (
    ("astrbot_plugin_share_card", "分享卡片转文字"),
    ("astrbot_plugin_bili_vision", "B站视频画面理解"),
    ("astrbot_plugin_snow_sleep", "机器人作息"),
    ("astrbot_plugin_snow_continuity", "连续对话接话"),
    ("astrbot_plugin_snow_messenger", "Bot 传话"),
    ("astrbot_plugin_snow_profile", "Bot 用户画像"),
    ("astrbot_plugin_snow_experience", "Bot 真实经历"),
    ("astrbot_plugin_snow_knowledge", "Bot 知识库"),
    ("astrbot_plugin_snow_guard", "Bot 安全守卫"),
    ("astrbot_plugin_snow_balance", "Bot 余额感知"),
    ("astrbot_plugin_snow_friend", "Bot 好友申请"),
    ("astrbot_plugin_snow_imagebox", "Bot 图库"),
    ("astrbot_plugin_obsidian_notes", "Bot Obsidian 笔记"),
    ("astrbot_plugin_search_manners", "搜索礼仪"),
    ("astrbot_plugin_star_citizen", "星际公民数据"),
)


def _plugin_repo(name: str) -> str:
    """读随包插件 metadata 里的 repo 字段（用于走插件市场安装）。"""
    meta = APP_DIR / "plugins" / name / "metadata.yaml"
    try:
        for line in meta.read_text(encoding="utf-8").splitlines():
            if line.startswith("repo:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


class ExtendMixin:
    def _build_extend_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        intro = QLabel(
            "SnowBot 的本机扩展插件集中在这里安装。优先从插件市场拉取最新版，"
            "网络不通时自动改用启动器内置的版本，离线也能装。安装后回到对应"
            "分栏（作息与接话 / 存储 / 搜索等）做配置。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        group = QGroupBox("本机扩展插件")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(9)
        self._ext_rows: dict[str, tuple[QLabel, QPushButton]] = {}
        for name, display in EXT_PLUGINS:
            name_label = QLabel(f"<b>{display}</b><br><span style='color:#8b93a7'>{name}</span>")
            status = QLabel("未连接")
            status.setObjectName("muted")
            button = QPushButton("一键安装")
            button.setObjectName("ghost")
            button.clicked.connect(lambda _=False, n=name: self.install_ext_plugin(n))
            row = QHBoxLayout()
            row.addWidget(status, 1)
            row.addWidget(button)
            form.addRow(name_label, row)
            self._ext_rows[name] = (status, button)
        note = QLabel("豆包语音插件（第三方）在「语音」分栏单独安装。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(group)
        layout.addWidget(note)
        layout.addStretch(1)

        self.extend_result = QLabel("")
        self.extend_result.setWordWrap(True)
        self.extend_result.setObjectName("muted")
        self.extend_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(self.extend_result)
        return page

    def _load_extend_ui(self):
        if not self.client:
            for status, button in self._ext_rows.values():
                status.setText("未连接 AstrBot")
                button.setEnabled(False)
            return
        entries = {
            p.get("name"): p for p in self.plugins if isinstance(p, dict)
        }
        for name, (status, button) in self._ext_rows.items():
            entry = entries.get(name)
            if entry is None:
                status.setText("未安装")
                button.setText("一键安装")
            else:
                version = str(entry.get("version") or "").lstrip("v")
                state = "已启用" if entry.get("activated", True) else "已停用"
                shown = f"已安装 · {state}" + (f" · v{version}" if version else "")
                status.setText(shown)
                button.setText("重装")
            button.setEnabled(True)

    def install_ext_plugin(self, name: str):
        if not self._need_client():
            return
        source = APP_DIR / "plugins" / name
        repo = _plugin_repo(name)

        def task():
            market_error = ""
            if repo:
                try:
                    self.client.install_market_plugin(repo)
                    return "market", ""
                except Exception as exc:
                    market_error = str(exc)
            if not (source / "metadata.yaml").is_file():
                raise ApiError(
                    f"本地没有 {name} 的插件源（{source}），且市场安装未成功"
                    + (f"：{market_error}" if market_error else "")
                )
            # 回退：上传启动器随包的本地插件（zip 上传即安装）
            self.client.upload_plugin(zip_folder(source), name + ".zip")
            detail = f"（市场安装未成功，已用内置版本：{market_error}）" if market_error else ""
            return "local", detail

        def done(result):
            via, detail = result
            self.plugins = self.client.list_plugins()
            display = dict(EXT_PLUGINS).get(name, name)
            self._load_extend_ui()
            how = "插件市场" if via == "market" else "内置版本"
            self.extend_result.setText(f"{display} 已通过{how}安装完成。{detail}")
            self._set_status(f"{display} 安装完成（{how}）", True)

        def failed(message: str):
            self.extend_result.setText(f"{name} 安装失败：{message}")
            self._set_status(f"{name} 安装失败", False)

        self._run_task(task, done, f"正在安装 {name}…", on_failed=failed)
