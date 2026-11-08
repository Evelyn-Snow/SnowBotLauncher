"""增强配置页分栏。"""

from __future__ import annotations

from .common import (
    ApiError,
    MEME_EXT,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
    _list_from,
    get_path,
    set_path,
)


class MemeMixin:
    def _build_meme_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.meme_plugin_label = QLabel("插件状态：未连接")
        self.meme_plugin_label.setObjectName("muted")
        layout.addWidget(self.meme_plugin_label)

        accel = QHBoxLayout()
        accel.addWidget(QLabel("GitHub 加速地址"))
        self.meme_accel = QLineEdit()
        self.meme_accel.setPlaceholderText("例如 https://gh-proxy.org/，留空表示直连")
        accel.addWidget(self.meme_accel, 1)
        save_accel = QPushButton("保存加速地址")
        save_accel.clicked.connect(self.save_meme_accel)
        accel.addWidget(save_accel)
        layout.addLayout(accel)

        actions = QHBoxLayout()
        fetch = QPushButton("拉取资源广场索引")
        fetch.clicked.connect(self.fetch_meme_index)
        refresh = QPushButton("刷新已安装")
        refresh.setObjectName("ghost")
        refresh.clicked.connect(self.refresh_meme_packs)
        actions.addWidget(fetch)
        actions.addWidget(refresh)
        actions.addStretch(1)
        layout.addLayout(actions)

        install_row = QHBoxLayout()
        install_row.addWidget(QLabel("套装 ID"))
        self.meme_pack_id = QLineEdit()
        self.meme_pack_id.setPlaceholderText("从资源广场复制的 pack_id，例如 blue-fat-fish-meme-pack")
        install_row.addWidget(self.meme_pack_id, 1)
        self.meme_set_default = QCheckBox("安装后设为默认")
        install_row.addWidget(self.meme_set_default)
        install = QPushButton("下载并安装")
        install.setObjectName("primary")
        install.clicked.connect(self.install_meme_pack)
        install_row.addWidget(install)
        layout.addLayout(install_row)

        self.meme_list = QListWidget()
        layout.addWidget(self.meme_list, 1)

        bottom = QHBoxLayout()
        set_default = QPushButton("设为默认")
        set_default.clicked.connect(self.set_selected_meme_default)
        multi = QPushButton("保存使用列表（勾选=启用）")
        multi.setToolTip("勾选的套装参与表情选取；取消勾选并保存即停用该套装")
        multi.clicked.connect(self.apply_meme_multi)
        uninstall = QPushButton("卸载所选")
        uninstall.setObjectName("danger")
        uninstall.clicked.connect(self.uninstall_selected_meme)
        bottom.addWidget(set_default)
        bottom.addWidget(multi)
        bottom.addWidget(uninstall)
        bottom.addStretch(1)
        layout.addLayout(bottom)

        self.meme_status = QLabel(
            "表情包功能依赖 meme_manager 插件。勾选=参与使用；卸载会删除该套装的全部图片文件。"
        )
        self.meme_status.setObjectName("muted")
        self.meme_status.setWordWrap(True)
        layout.addWidget(self.meme_status)
        return page

    def _load_meme_ui(self):
        names = self._plugin_names()
        installed = "meme_manager" in names
        self.meme_plugin_label.setText(
            "插件状态：已安装" if installed else "插件状态：未安装（请先在 AstrBot 插件市场安装 meme_manager）"
        )
        if installed and self.meme_config:
            self.meme_accel.setText(
                str(get_path(self.meme_config, "community.github_accelerator_url") or "")
            )
        if installed:
            QTimer.singleShot(300, self.refresh_meme_packs)

    def _meme_data(self, key: str) -> list:
        result = self.client.request("GET", f"{MEME_EXT}/{key}")
        if not self.client.ok(result):
            raise ApiError(self.client.message(result))
        return _list_from(result, key, "packs", "rules", "items")

    def refresh_meme_packs(self):
        if not self._need_meme():
            return

        def task():
            packs = self._meme_data("packs")
            rules = self._meme_data("settings/rules")
            return packs, rules

        def done(result):
            packs, rules = result
            default = next(
                (r for r in rules if isinstance(r, dict) and r.get("scope") == "default"), {}
            )
            ids = default.get("pack_ids") or (
                [default.get("pack_id")] if default.get("pack_id") else []
            )
            self.meme_list.clear()
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                pid = str(pack.get("pack_id") or pack.get("id") or pack.get("name") or "")
                if not pid:
                    continue
                name = str(pack.get("name") or pack.get("title") or pid)
                count = pack.get("count") or pack.get("image_count")
                label = f"{name}    ({pid})"
                if count:
                    label += f"    {count} 张"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, pid)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(
                    Qt.CheckState.Checked if pid in ids else Qt.CheckState.Unchecked
                )
                self.meme_list.addItem(item)
            self.meme_status.setText(
                f"已安装 {self.meme_list.count()} 套表情包；勾选=启用，取消勾选并点「保存使用列表」=停用。"
            )
            self._set_status(f"表情包：已安装 {self.meme_list.count()} 套", True)

        self._run_task(task, done, "正在读取表情包列表…")

    def fetch_meme_index(self):
        if not self._need_meme():
            return

        def task():
            result = self.client.request(
                "POST", f"{MEME_EXT}/community/index/fetch", body={}, timeout=120
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))
            return self._meme_data("packs"), self._meme_data("settings/rules")

        def done(result):
            packs, rules = result
            self.meme_status.setText(f"资源广场索引已刷新，已安装 {len(packs)} 套。")
            self.refresh_meme_packs()

        self._run_task(task, done, "正在拉取表情包资源广场索引…")

    def save_meme_accel(self):
        if not self._need_meme():
            return
        url = self.meme_accel.text().strip()

        def task():
            config = self.meme_config or self.client.get_plugin_config("meme_manager")
            set_path(config, "community.github_accelerator_url", url)
            self.client.put_plugin_config("meme_manager", config)
            return config

        def done(config):
            self.meme_config = config
            self._set_status("表情包 GitHub 加速地址已保存", True)

        self._run_task(task, done, "正在保存加速地址…")

    def install_meme_pack(self):
        if not self._need_meme():
            return
        pack_id = self.meme_pack_id.text().strip()
        if not pack_id:
            QMessageBox.warning(self, "缺少套装 ID", "请填写要安装的 pack_id。")
            return
        set_default = self.meme_set_default.isChecked()

        def task():
            result = self.client.request(
                "POST",
                f"{MEME_EXT}/community/install",
                body={"pack_id": pack_id, "set_as_default": set_default},
                timeout=900,
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))
            return pack_id

        def done(result):
            self._set_status(f"表情包「{result}」安装完成", True)
            self.refresh_meme_packs()

        self._run_task(task, done, f"正在下载表情包「{pack_id}」…")

    def set_selected_meme_default(self):
        if not self._need_meme():
            return
        item = self.meme_list.currentItem()
        if not item:
            QMessageBox.information(self, "未选择", "请先选中一套表情包。")
            return
        pid = item.data(Qt.ItemDataRole.UserRole)

        def task():
            result = self.client.request(
                "POST", f"{MEME_EXT}/packs/default", body={"pack_id": pid}
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))

        def done(_result):
            self._set_status(f"已把「{pid}」设为默认表情包", True)
            self.refresh_meme_packs()

        self._run_task(task, done, f"正在设置默认表情包「{pid}」…")

    def uninstall_selected_meme(self):
        if not self._need_meme():
            return
        item = self.meme_list.currentItem()
        if not item:
            QMessageBox.information(self, "未选择", "请先选中要卸载的表情包。")
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self,
            "确认卸载",
            f"确定卸载表情包「{item.text()}」？\n该操作会删除这套表情包的全部图片文件，不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def task():
            result = self.client.request(
                "POST", f"{MEME_EXT}/packs/uninstall", body={"pack_id": pid}
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))

        def done(_result):
            self._set_status(f"已卸载表情包「{pid}」", True)
            self.refresh_meme_packs()

        self._run_task(task, done, f"正在卸载表情包「{pid}」…")

    def apply_meme_multi(self):
        if not self._need_meme():
            return
        ids = []
        for row in range(self.meme_list.count()):
            item = self.meme_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        if not ids:
            QMessageBox.information(self, "未勾选", "请至少勾选一套表情包。")
            return

        def task():
            result = self.client.request("GET", f"{MEME_EXT}/settings/rules")
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))
            rules = _list_from(result, "rules", "items")
            keep = [r for r in rules if isinstance(r, dict) and r.get("scope") != "default"]
            current = next(
                (r for r in rules if isinstance(r, dict) and r.get("scope") == "default"), {}
            )
            rule = {
                "id": current.get("id") or "default",
                "scope": "default",
                "pack_id": ids[0],
                "pack_ids": ids,
            }
            saved = self.client.request(
                "POST", f"{MEME_EXT}/settings/rules", body={"rules": keep + [rule]}
            )
            if not self.client.ok(saved):
                raise ApiError(self.client.message(saved))

        def done(_result):
            self._set_status(f"已设置为同时使用 {len(ids)} 套表情包", True)
            self.refresh_meme_packs()

        self._run_task(task, done, "正在应用表情包规则…")
