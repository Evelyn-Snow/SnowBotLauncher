"""增强配置页外壳与连接逻辑。"""

from __future__ import annotations

from .common import (
    ApiError,
    AstrBotClient,
    Path,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    Worker,
    port_listening,
    scroll_page,
    urlsplit,
)
from snowbot.ui.theme import OK_COLOR, WARN_COLOR
from .persona import PersonaMixin
from .search import SearchMixin
from .meme import MemeMixin
from .voice import VoiceMixin
from .memory import MemoryMixin
from .group import GroupMixin
from .behavior import BehaviorMixin
from .vision import VisionMixin
from .storage import StorageMixin
from .extend import ExtendMixin


class EnhanceTab(
    PersonaMixin,
    MemeMixin,
    VoiceMixin,
    MemoryMixin,
    GroupMixin,
    BehaviorMixin,
    VisionMixin,
    SearchMixin,
    StorageMixin,
    ExtendMixin,
    QWidget,
):
    def __init__(self, cfg: dict, dashboard: dict | None = None):
        super().__init__()
        self.cfg = cfg
        self.dashboard = dashboard or {}
        self.client: AstrBotClient | None = None
        self.config: dict = {}
        self.personas: list = []
        self.plugins: list = []
        self.meme_config: dict | None = None
        self.living_config: dict | None = None
        self.current_persona_id: str | None = None
        self.worker: Worker | None = None
        self.persona_file: Path | None = None
        self._persona_file_mtime: float | None = None
        self._build_ui()
        self._refresh_persona_files()

    # ---------------- 通用 ----------------
    def _plugin_names(self) -> set:
        return {p.get("name") for p in self.plugins if isinstance(p, dict)}

    def _need_client(self) -> bool:
        if not self.client:
            QMessageBox.information(
                self,
                "请先连接 AstrBot",
                "请先在页面顶部填写 AstrBot 后台密码，并点击「连接 AstrBot」。",
            )
            return False
        return True

    def _need_meme(self) -> bool:
        if not self._need_client():
            return False
        if "meme_manager" not in self._plugin_names():
            QMessageBox.information(
                self,
                "未安装表情包插件",
                "请先在 AstrBot 的插件市场安装并启用 meme_manager，再使用这些按钮。",
            )
            return False
        return True

    def _set_status(self, text: str, ok: bool | None = None):
        self.status.setText(text)
        if ok is True:
            self.status.setStyleSheet(f"color:{OK_COLOR};")
        elif ok is False:
            self.status.setStyleSheet(f"color:{WARN_COLOR};")
        else:
            self.status.setObjectName("muted")
            self.status.setStyleSheet("")

    def _sync_intro_code(self):
        """连接成功后，把启动器里配置的熟人暗号同步给画像插件（有差异才推）。"""
        client = self.client
        want = str((self.cfg or {}).get("intro_code") or "")
        if client is None:
            return
        try:
            config = client.get_plugin_config("astrbot_plugin_snow_profile")
            if str(config.get("intro_code") or "") == want:
                return
            config["intro_code"] = want
            client.put_plugin_config("astrbot_plugin_snow_profile", config)
            self._set_status("已把启动器里的熟人暗号同步给画像插件", True)
        except Exception as exc:
            self._set_status(f"熟人暗号同步失败：{str(exc)[:80]}", False)

    def _copy_result(self, text: str, what: str = "信息"):
        text = (text or "").strip()
        if not text:
            self._set_status("没有可复制的内容", False)
            return
        QApplication.clipboard().setText(text)
        self._set_status(f"{what}已复制到剪贴板", True)

    @staticmethod
    def _voice_error_hint(message: str) -> str:
        text = str(message)
        if "45000030" in text or "资源未授权" in text:
            return (
                "\n\n原因：当前应用没有 Seed Audio 1.0 的使用权限（资源未授权）。\n"
                "请确认：1）APP ID 与 Access Token 来自豆包语音控制台的同一个应用；"
                "2）该应用已开通/申请 Seed Audio 1.0；"
                "3）使用的是豆包语音的 Access Token，不是火山方舟 API Key。"
            )
        if "45000010" in text:
            return (
                "\n\n原因：APP ID 与 Access Token 不匹配或已失效。"
                "请到豆包语音控制台重新复制同一应用的 APP ID 和 Access Token。"
            )
        if "401" in text or "403" in text:
            return (
                "\n\n原因：鉴权失败。请检查 APP ID、Access Token 是否属于同一应用，"
                "以及账号是否已开通对应的语音服务、配额是否充足。"
            )
        return ""

    def _set_busy(self, busy: bool):
        self.btn_connect.setEnabled(not busy)
        if busy:
            self._set_status("处理中，请稍候…")

    def _run_task(self, fn, on_done, text: str, on_failed=None):
        if self.worker and self.worker.isRunning():
            self._set_status("已有操作正在进行，请稍候…", False)
            return
        self._set_busy(True)
        self._set_status(text)
        worker = Worker(fn)
        worker.done.connect(lambda result: self._task_done(result, on_done))
        worker.failed.connect(lambda message: self._task_failed(message, on_failed))
        worker.finished.connect(lambda: setattr(self, "worker", None))
        self.worker = worker
        worker.start()

    def _task_done(self, result, on_done):
        self._set_busy(False)
        try:
            on_done(result)
        except Exception as exc:
            self._set_status(f"失败：{exc}", False)
            QMessageBox.warning(self, "操作失败", str(exc))

    def _task_failed(self, message: str, on_failed=None):
        self._set_busy(False)
        self._set_status(f"失败：{message}", False)
        if on_failed is not None:
            try:
                on_failed(message)
            except Exception:
                pass
        QMessageBox.warning(self, "操作失败", message)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        port = int(self.dashboard.get("port") or self.cfg.get("dashboard_port", 6185))
        self.url_edit = QLineEdit(f"http://127.0.0.1:{port}")
        self.user_edit = QLineEdit(str(self.dashboard.get("username") or "astrbot"))
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText("后台密码（不保存）")
        self.btn_connect = QPushButton("连接 AstrBot")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.clicked.connect(self.connect_backend)
        self.conn_label = QLabel("未连接")
        self.conn_label.setObjectName("muted")
        bar.addWidget(QLabel("后台"))
        bar.addWidget(self.url_edit, 1)
        bar.addWidget(QLabel("账号"))
        bar.addWidget(self.user_edit, 1)
        bar.addWidget(QLabel("密码"))
        bar.addWidget(self.pw_edit, 1)
        bar.addWidget(self.btn_connect)
        bar.addWidget(self.conn_label)
        outer.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(scroll_page(self._build_persona_tab(), 520), "人格")
        self.tabs.addTab(scroll_page(self._build_meme_tab(), 420), "表情包")
        self.tabs.addTab(scroll_page(self._build_voice_tab(), 460), "语音")
        self.tabs.addTab(scroll_page(self._build_memory_tab(), 400), "记忆")
        self.tabs.addTab(scroll_page(self._build_group_tab(), 460), "群聊")
        self.tabs.addTab(scroll_page(self._build_behavior_tab(), 460), "作息与接话")
        self.tabs.addTab(scroll_page(self._build_vision_tab(), 520), "视觉")
        self.tabs.addTab(scroll_page(self._build_search_tab(), 440), "搜索")
        self.tabs.addTab(scroll_page(self._build_storage_tab(), 500), "存储")
        self.tabs.addTab(scroll_page(self._build_extend_tab(), 420), "扩展插件")
        outer.addWidget(self.tabs, 1)

        self.status = QLabel("填写密码并连接 AstrBot 后使用；密码不会保存。")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    def connect_backend(self):
        url = self.url_edit.text().strip()
        user = self.user_edit.text().strip() or "astrbot"
        password = self.pw_edit.text()
        if not url or not password:
            QMessageBox.warning(self, "缺少信息", "请填写 AstrBot 后台地址和密码。")
            return
        if not url.startswith("http"):
            url = "http://" + url
        url = url.rstrip("/")
        host = urlsplit(url).hostname
        if host in ("127.0.0.1", "localhost"):
            port = urlsplit(url).port or int(self.cfg.get("dashboard_port", 6185))
            if not port_listening(port):
                QMessageBox.information(
                    self,
                    "AstrBot 未运行",
                    "AstrBot 面板端口还没有就绪。\n"
                    "请先在「控制台」页点击「一键启动全部」，等待约 20~30 秒后再连接。",
                )
                return

        def task():
            client = AstrBotClient(url)
            if not client.login(user, password):
                raise ApiError("登录失败：检查后台地址、账号和密码")
            config = client.get_profile()
            personas = client.list_personas()
            plugins = client.list_plugins()
            names = {p.get("name") for p in plugins if isinstance(p, dict)}
            meme_config = None
            living_config = None
            if "meme_manager" in names:
                try:
                    meme_config = client.get_plugin_config("meme_manager")
                except Exception:
                    pass
            if "astrbot_plugin_livingmemory" in names:
                try:
                    living_config = client.get_plugin_config("astrbot_plugin_livingmemory")
                except Exception:
                    pass
            return client, config, personas, plugins, meme_config, living_config

        def done(result):
            (
                self.client,
                self.config,
                self.personas,
                self.plugins,
                self.meme_config,
                self.living_config,
            ) = result
            platforms = [
                p.get("id")
                for p in self.config.get("platform", [])
                if isinstance(p, dict) and p.get("type") == "aiocqhttp"
            ]
            self.conn_label.setText("已连接")
            self.conn_label.setToolTip("平台：" + (platforms[0] if platforms else "未找到"))
            self.conn_label.setStyleSheet(f"color:{OK_COLOR};")
            self._sync_intro_code()
            self.pw_edit.clear()
            self._load_owner_from_profile()
            self._populate_personas()
            self._load_meme_ui()
            self._load_voice_ui()
            self._load_memory_ui()
            self._load_group_ui()
            self._load_behavior_ui()
            self._load_vision_ui()
            self._load_search_ui()
            self._load_storage_ui()
            self._load_extend_ui()
            self._set_status(
                "已连接 AstrBot，平台：" + (platforms[0] if platforms else "未找到"), True
            )

        self._run_task(task, done, "正在连接 AstrBot…")
