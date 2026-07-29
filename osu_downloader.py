#!/usr/bin/env python3
"""
osu! Beatmap Downloader — GUI 版
支持 URL、BID（谱面编号）、SID（谱集编号）三种模式
镜像源: sayobot.cn

打包: pyinstaller --onefile --windowed --name "osu_downloader" osu_downloader.py
"""

import os
import re
import time
import threading
from pathlib import Path

import requests
import customtkinter as ctk
from tkinter import filedialog, messagebox

# ── 常量 ──────────────────────────────────────────────
UA_DL = "osu-downloader/2.0"
UA_WEB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REFERER = "https://osu.sayobot.cn/"
VERSION = "2.0"

# ── 外观 ──────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class PlaceholderTextbox(ctk.CTkTextbox):
    """带 placeholder 的文本框"""
    def __init__(self, *args, placeholder="", **kwargs):
        super().__init__(*args, **kwargs)
        self._placeholder = placeholder
        self._placeholder_shown = False
        self._ph_color = ("gray50", "gray50")

        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self._show_placeholder()

    def _show_placeholder(self):
        if not self._placeholder:
            return
        if self.get("1.0", "end-1c").strip() == "":
            self._placeholder_shown = True
            self.configure(text_color=self._ph_color)
            self.insert("1.0", self._placeholder)

    def _on_focus_in(self, event):
        if self._placeholder_shown:
            self.delete("1.0", "end")
            self.configure(text_color=("white", "white"))
            self._placeholder_shown = False

    def _on_focus_out(self, event):
        if self.get("1.0", "end-1c").strip() == "":
            self._show_placeholder()

    def get_real_text(self):
        """获取实际内容（排除 placeholder）"""
        if self._placeholder_shown:
            return ""
        return self.get("1.0", "end-1c")

    def set_placeholder(self, text):
        self._placeholder = text
        if self._placeholder_shown:
            self.delete("1.0", "end")
            self._show_placeholder()


class OsuDownloader(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"osu! Beatmap Downloader v{VERSION}")
        self.geometry("820x700")
        self.minsize(700, 600)

        self.cancel_flag = False
        self.running = False
        self.session = requests.Session()

        self._build_ui()
        self._center_window()

    # ── UI 构建 ──────────────────────────────────────
    def _build_ui(self):
        # 顶部标题
        title = ctk.CTkLabel(
            self, text="osu! Beatmap Downloader",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title.pack(pady=(20, 5))

        subtitle = ctk.CTkLabel(
            self, text="镜像源: sayobot.cn  •  支持 URL / BID / SID，自动命名",
            font=ctk.CTkFont(size=12), text_color="gray"
        )
        subtitle.pack(pady=(0, 15))

        # ── 模式选择 ──
        mode_frame = ctk.CTkFrame(self)
        mode_frame.pack(fill="x", padx=30, pady=(0, 10))

        mode_label = ctk.CTkLabel(mode_frame, text="输入模式:", font=ctk.CTkFont(weight="bold"))
        mode_label.pack(side="left", padx=(15, 10), pady=12)

        self.mode_var = ctk.StringVar(value="url")
        self.btn_mode = ctk.CTkSegmentedButton(
            mode_frame,
            values=["url", "bid", "sid"],
            variable=self.mode_var,
            command=self._on_mode_change,
        )
        self.btn_mode.pack(side="left", padx=(0, 5), pady=12)

        self.mode_hint = ctk.CTkLabel(
            mode_frame,
            text="URL=贴链接  │  BID=谱面编号  │  SID=谱集编号",
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.mode_hint.pack(side="left", padx=10, pady=12)

        # ── ID 输入区 ──
        id_frame = ctk.CTkFrame(self)
        id_frame.pack(fill="both", expand=True, padx=30, pady=(0, 10))

        self.id_label = ctk.CTkLabel(
            id_frame, text="BID 列表（一行一个）:",
            font=ctk.CTkFont(weight="bold")
        )
        self.id_label.pack(anchor="w", padx=15, pady=(10, 0))

        self.id_text = PlaceholderTextbox(
            id_frame, height=140, font=("Consolas", 13),
            placeholder="每行一个 BID，如:\n724149\n1092805\n774837",
        )
        self.id_text.pack(fill="both", expand=True, padx=15, pady=(5, 5))

        # 快捷按钮行
        quick_frame = ctk.CTkFrame(id_frame, fg_color="transparent")
        quick_frame.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkButton(
            quick_frame, text="从文件读取...", width=110,
            command=self._load_from_file
        ).pack(side="left", padx=(0, 5))

        ctk.CTkButton(
            quick_frame, text="清空", width=70, fg_color="gray40",
            command=self._clear_ids
        ).pack(side="left")

        # ── 设置行（输出目录 + 下载类型） ──
        settings_frame = ctk.CTkFrame(self)
        settings_frame.pack(fill="x", padx=30, pady=(0, 10))

        # 输出目录
        dir_label = ctk.CTkLabel(settings_frame, text="输出目录:", font=ctk.CTkFont(weight="bold"))
        dir_label.grid(row=0, column=0, sticky="w", padx=15, pady=(12, 5))

        self.dir_var = ctk.StringVar(value=str(Path.home() / "osu_songs"))
        dir_entry = ctk.CTkEntry(settings_frame, textvariable=self.dir_var, width=420)
        dir_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5), pady=(12, 5))

        ctk.CTkButton(
            settings_frame, text="浏览...", width=70,
            command=self._browse_dir
        ).grid(row=0, column=2, sticky="e", padx=(0, 15), pady=(12, 5))

        # 下载类型
        type_label = ctk.CTkLabel(settings_frame, text="下载类型:", font=ctk.CTkFont(weight="bold"))
        type_label.grid(row=1, column=0, sticky="w", padx=15, pady=(5, 12))

        self.type_var = ctk.StringVar(value="full")
        type_menu = ctk.CTkOptionMenu(
            settings_frame,
            values=["full — 完整版（含视频）", "novideo — 无视频版", "mini — 精简版"],
            variable=self.type_var,
            width=280,
        )
        type_menu.grid(row=1, column=1, sticky="w", padx=(0, 5), pady=(5, 12))

        settings_frame.columnconfigure(1, weight=1)

        # ── 按钮 ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=(0, 5))

        self.start_btn = ctk.CTkButton(
            btn_frame, text="▶  开始下载", height=38,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_download
        )
        self.start_btn.pack(side="left", padx=(0, 10))

        self.cancel_btn = ctk.CTkButton(
            btn_frame, text="■ 停止", height=38,
            fg_color="#8B0000", hover_color="#A00000",
            state="disabled", command=self._cancel
        )
        self.cancel_btn.pack(side="left")

        # ── 进度条 ──
        self.progress = ctk.CTkProgressBar(self, height=16)
        self.progress.pack(fill="x", padx=30, pady=(5, 2))
        self.progress.set(0)

        self.progress_label = ctk.CTkLabel(self, text="就绪", font=ctk.CTkFont(size=11))
        self.progress_label.pack(pady=(0, 5))

        # ── 日志区 ──
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=True, padx=30, pady=(0, 20))

        log_label = ctk.CTkLabel(
            log_frame, text="日志:",
            font=ctk.CTkFont(weight="bold")
        )
        log_label.pack(anchor="w", padx=15, pady=(8, 0))

        self.log_text = ctk.CTkTextbox(log_frame, font=("Consolas", 12), state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=15, pady=(5, 10))

    # ── 窗口居中 ────────────────────────────────────
    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"+{x}+{y}")

    # ── 模式切换 ────────────────────────────────────
    def _on_mode_change(self, *args):
        mode = self.mode_var.get()
        if mode == "url":
            self.id_label.configure(text="URL 列表（一行一个）:")
            self.id_text.set_placeholder(
                "每行一个 osu! 链接，如:\n"
                "https://osu.ppy.sh/beatmapsets/2318291#mania/4965337\n"
                "https://osu.ppy.sh/b/724149\n"
                "https://osu.ppy.sh/beatmapsets/123"
            )
            self.mode_hint.configure(text="自动提取 SID + BID，SID 下载 + BID 命名")
        elif mode == "bid":
            self.id_label.configure(text="BID 列表（一行一个）:")
            self.id_text.set_placeholder("每行一个 BID，如:\n724149\n1092805\n774837")
            self.mode_hint.configure(text="BID=谱面编号 (/b/xxx)  →  自动解析 SID 后下载")
        else:
            self.id_label.configure(text="SID 列表（一行一个）:")
            self.id_text.set_placeholder("每行一个 SID，如:\n123\n456\n789")
            self.mode_hint.configure(text="SID=谱集编号 (/beatmapsets/xxx)  →  直接下载")

    # ── 浏览目录 ────────────────────────────────────
    def _browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.dir_var.get())
        if path:
            self.dir_var.set(path)

    # ── 从文件读取 ──────────────────────────────────
    def _load_from_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.id_text.delete("1.0", "end")
                self.id_text.insert("1.0", content)
                self.id_text.configure(text_color=("white", "white"))
                self._log(f"[INFO] 已加载: {path}")
            except Exception as e:
                messagebox.showerror("错误", f"读取文件失败:\n{e}")

    # ── 清空 ────────────────────────────────────────
    def _clear_ids(self):
        self.id_text.delete("1.0", "end")
        self.id_text._show_placeholder()

    # ── 日志 ────────────────────────────────────────
    def _log(self, msg):
        self.log_text.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ── 解析 ID ─────────────────────────────────────
    def _parse_ids(self, mode):
        """
        解析用户输入。
        返回 [(label, sid_or_none), ...]
          - label: 用于日志显示和文件名前缀 (BID 或 SID)
          - sid_or_none: 已知的 SID（URL 模式提取出 SID；SID 模式即输入值；BID 模式为 None）
        """
        raw = self.id_text.get_real_text()
        entries = []
        seen = set()

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            if mode == "url":
                # 从 URL 中提取 SID 和 BID
                entry = self._parse_url(line)
                if entry:
                    label, sid = entry
                    key = f"{label}|{sid}"
                    if key not in seen:
                        entries.append(entry)
                        seen.add(key)
            else:
                # BID / SID 模式：提取纯数字
                m = re.search(r'(\d{1,10})', line)
                if m:
                    num = m.group(1)
                    if num not in seen:
                        if mode == "sid":
                            entries.append((num, num))  # label=num, sid=num (已知)
                        else:
                            entries.append((num, None))  # label=num, sid 待解析
                        seen.add(num)

        return entries

    def _parse_url(self, url):
        """
        从 osu! URL 中提取 (label, sid)。
        支持的格式:
          - https://osu.ppy.sh/beatmapsets/{SID}#mode/{BID}  → (BID, SID)
          - https://osu.ppy.sh/b/{BID}                       → (BID, None)  需解析 SID
          - https://osu.ppy.sh/beatmaps/{BID}                → (BID, None)  需解析 SID
          - https://osu.ppy.sh/beatmapsets/{SID}             → (SID, SID)   BID 未知用 SID
          - https://osu.ppy.sh/s/{SID}                       → (SID, SID)
        """
        # 提取 SID: /beatmapsets/{SID} 或 /s/{SID}
        m_sid = re.search(r'/(?:beatmapsets|s)/(\d+)', url)
        sid = m_sid.group(1) if m_sid else None

        # 提取 BID: /b/{BID} 或 #mode/{BID}
        m_bid = re.search(r'/(?:b|beatmaps)/(\d+)', url)
        if not m_bid:
            m_bid = re.search(r'#\w+/(\d+)', url)
        bid = m_bid.group(1) if m_bid else None

        if bid and sid:
            # 完整 URL — BID 命名，SID 下载
            return (bid, sid)
        elif bid:
            # 只有 BID — 需解析 SID
            return (bid, None)
        elif sid:
            # 只有 SID — SID 命名 + 下载
            return (sid, sid)

        return None

    # ── BID → SID ────────────────────────────────────
    def _bid_to_sid(self, bid):
        """通过 HEAD 请求 osu.ppy.sh 获取重定向，从中提取 SID"""
        try:
            resp = self.session.head(
                f"https://osu.ppy.sh/b/{bid}",
                headers={"User-Agent": UA_WEB},
                timeout=15,
                allow_redirects=False,
            )
            location = resp.headers.get("Location", "")
            m = re.search(r'/beatmapsets/(\d+)', location)
            if m:
                return m.group(1)

            # fallback: 允许重定向
            resp2 = self.session.get(
                f"https://osu.ppy.sh/b/{bid}",
                headers={"User-Agent": UA_WEB},
                timeout=15,
                allow_redirects=True,
            )
            m = re.search(r'/beatmapsets/(\d+)', resp2.url)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    # ── 获取元数据 ──────────────────────────────────
    def _get_metadata(self, sid):
        """从 sayobot API 获取 artist + title"""
        try:
            resp = self.session.get(
                f"https://api.sayobot.cn/v2/beatmapinfo?0={sid}",
                headers={"User-Agent": UA_WEB},
                timeout=15,
            )
            data = resp.json()
            if data.get("status") == 0:
                info = data.get("data", {})
                return info.get("artist", ""), info.get("title", "")
            return "", ""
        except Exception:
            return "", ""

    # ── 安全文件名 ──────────────────────────────────
    @staticmethod
    def _safe_name(artist, title, sid):
        if artist and title:
            raw = f"{artist} - {title}"
        else:
            raw = sid
        return re.sub(r'[\\/:*?"<>|]', '_', raw).rstrip('. ')

    # ── 下载单个 ────────────────────────────────────
    def _download_one(self, sid, bid, output_dir, dl_type):
        """下载一个谱面，返回 (status, message)"""
        if self.cancel_flag:
            return "cancel", "已取消"

        # 查找已有文件
        existing = list(Path(output_dir).glob(f"{bid}*.osz"))
        if existing:
            return "skip", f"已存在 ({existing[0].name})"

        # BID 模式下需要解析 SID（传入 sid=None）
        if sid is None:
            sid = self._bid_to_sid(bid)
            if not sid:
                return "fail", "无法解析 SID（可能限流或 BID 无效）"

        # 获取元数据
        artist, title = self._get_metadata(sid)
        safe = self._safe_name(artist, title, sid)
        filename = f"{bid} {safe}.osz"
        base_type = dl_type.split(" ")[0]  # "full — ..." → "full"

        # 下载
        url = f"https://dl.sayobot.cn/beatmaps/download/{base_type}/{sid}"
        tmp = Path(output_dir) / f"_dl_{bid}.tmp"

        try:
            resp = self.session.get(
                url,
                headers={"User-Agent": UA_DL, "Referer": REFERER},
                timeout=180,
                stream=True,
            )

            if resp.status_code != 200:
                tmp.unlink(missing_ok=True)
                return "fail", f"HTTP {resp.status_code} (SID:{sid})"

            downloaded = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if self.cancel_flag:
                        f.close()
                        tmp.unlink(missing_ok=True)
                        return "cancel", "已取消"
                    f.write(chunk)
                    downloaded += len(chunk)

            if downloaded < 1024:
                tmp.unlink(missing_ok=True)
                return "fail", f"文件过小 ({downloaded} bytes, SID:{sid})"

            dest = Path(output_dir) / filename
            # 如果目标已存在（不同 bid 但同名），加序号
            if dest.exists():
                stem = f"{bid} {safe}"
                for n in range(2, 100):
                    dest = Path(output_dir) / f"{stem} ({n}).osz"
                    if not dest.exists():
                        break
            tmp.rename(dest)
            kb = downloaded // 1024
            return "ok", f"SID:{sid}, {kb}KB → {dest.name}"

        except requests.RequestException as e:
            tmp.unlink(missing_ok=True)
            return "fail", f"下载异常: {e} (SID:{sid})"

    # ── 开始下载 ────────────────────────────────────
    def _start_download(self):
        if self.running:
            return

        mode = self.mode_var.get()
        entries = self._parse_ids(mode)  # [(label, sid_or_none), ...]
        if not entries:
            hint = "请输入至少一个 URL / BID / SID。"
            messagebox.showwarning("无 ID", hint)
            return

        output_dir = self.dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("无目录", "请指定输出目录。")
            return

        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建输出目录:\n{e}")
            return

        self.cancel_flag = False
        self.running = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)

        # 清空日志
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        mode = self.mode_var.get()
        dl_type = self.type_var.get()

        self._log(f"{'='*50}")
        self._log(f" osu! Beatmap Downloader v{VERSION}")
        self._log(f"{'='*50}")
        self._log(f"模式:     {mode.upper()}")
        self._log(f"数量:     {len(entries)} 个")
        self._log(f"输出:     {output_dir}")
        self._log(f"类型:     {dl_type}")
        self._log(f"{'='*50}")

        thread = threading.Thread(
            target=self._download_loop,
            args=(entries, output_dir, dl_type),
            daemon=True,
        )
        thread.start()

    # ── 下载循环 ────────────────────────────────────
    def _download_loop(self, entries, output_dir, dl_type):
        """entries: [(label, sid_or_none), ...]"""
        total = len(entries)
        ok = fail = skip = cancel = 0
        fail_list = []
        start_time = time.time()

        for i, (label, sid) in enumerate(entries):
            if self.cancel_flag:
                cancel = total - i
                break

            progress_text = f"[{i+1}/{total}]"
            self.progress_label.configure(text=f"{progress_text} 处理中...")
            self.progress.set(i / total)

            self._log(f"{progress_text} {label} → 处理中...")

            result, msg = self._download_one(sid, label, output_dir, dl_type)

            if result == "ok":
                ok += 1
                self._log(f"  ✅ {msg}")
            elif result == "skip":
                skip += 1
                self._log(f"  ⏭ {msg}")
            elif result == "fail":
                fail += 1
                fail_list.append(f"  {label} → {msg}")
                self._log(f"  ❌ {msg}")
            elif result == "cancel":
                cancel = total - i
                break

            if i < total - 1 and not self.cancel_flag:
                time.sleep(2)  # 请求间隔

        elapsed = time.time() - start_time
        self.progress.set(1.0)

        # ── 总结 ──
        self._log("")
        self._log(f"{'='*50}")
        self._log(f" {'='*45}")
        self._log(f" 下载{'已停止' if self.cancel_flag else '完成'}: 成功 {ok}  /  跳过 {skip}  /  失败 {fail}")
        self._log(f" 耗时 {elapsed:.0f}s，文件保存在: {output_dir}")
        self._log(f"{'='*50}")
        if fail_list:
            self._log("")
            self._log("失败的 ID:")
            for line in fail_list:
                self._log(line)

        # 重置 UI
        self.progress_label.configure(text="完成" if not self.cancel_flag else "已停止")
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.running = False

        # 弹窗
        if not self.cancel_flag:
            self.after(100, lambda: messagebox.showinfo(
                "完成",
                f"下载完成！\n成功: {ok}  跳过: {skip}  失败: {fail}\n耗时: {elapsed:.0f}s"
            ))

    # ── 取消 ────────────────────────────────────────
    def _cancel(self):
        self.cancel_flag = True
        self._log("[WARN] 正在停止...")
        self.cancel_btn.configure(state="disabled")


# ── 入口 ──────────────────────────────────────────────
def main():
    app = OsuDownloader()
    app.mainloop()


if __name__ == "__main__":
    main()
