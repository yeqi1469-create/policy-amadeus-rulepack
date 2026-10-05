from __future__ import annotations

import ctypes
import json
import queue
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageTk
from knowledge_update import get_status, start_startup_check
from update_progress import progress_caption
from policy_generator import extract_license_data, generate_translated_bundle


def group_market_values(markets, value_for_market):
    """Group markets only when the rendered platform value is identical."""
    groups: list[dict[str, object]] = []
    for market in markets:
        value = str(value_for_market(market))
        group = next((item for item in groups if item["value"] == value), None)
        if group:
            group["markets"].append(market)
        else:
            groups.append({"value": value, "markets": [market]})
    return groups


def compact_market_scope(all_markets, matching_markets) -> str:
    """Describe a rule's scope without overflowing the two-column result view."""
    all_names = [str(item["country"]) for item in all_markets]
    matching_names = [str(item["country"]) for item in matching_markets]
    if len(matching_names) == len(all_names):
        return "全部适配"
    if len(matching_names) > len(all_names) / 2:
        excluded = [name for name in all_names if name not in matching_names]
        excluded_cn = "、".join(MARKET_NAMES_CN.get(name, name) for name in excluded)
        return f"除{excluded_cn}外均适配"
    return "、".join(MARKET_NAMES_CN.get(name, name) for name in matching_names)

APP_TITLE = "Policy Amadeus"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
BLACK, PANEL, EDGE = "#000000", "#10141c", "#46505e"
WHITE, MUTED, ORANGE = "#ffffff", "#d9dee7", "#e46f2b"
EUROPE_MARKETS = (
    "Germany", "United Kingdom", "France", "Italy", "Russia", "Spain", "Turkey", "Netherlands",
    "Switzerland", "Poland", "Belgium", "Sweden", "Austria", "Norway", "Denmark", "Ireland",
    "Finland", "Romania", "Czechia", "Portugal", "Greece", "Hungary", "Ukraine", "Slovakia",
    "Bulgaria", "Croatia", "Serbia", "Lithuania", "Slovenia", "Latvia", "Estonia", "Cyprus",
    "Iceland", "Bosnia and Herzegovina", "Albania", "North Macedonia", "Moldova", "Georgia",
    "Armenia", "Belarus", "Azerbaijan", "Montenegro", "Luxembourg", "Malta", "Kosovo",
    "Liechtenstein", "Monaco", "Andorra", "San Marino", "Vatican City",
)
VERIFIED_MARKETS = {
    "Germany", "Austria", "France", "Italy", "Spain", "Portugal", "Netherlands", "Belgium",
    "Denmark", "Sweden", "Finland", "Poland", "Czechia", "Hungary", "Romania", "Bulgaria",
    "Greece", "Croatia", "Slovakia", "Slovenia", "Estonia", "Latvia", "Lithuania", "Ireland",
    "Luxembourg", "Malta", "Cyprus", "Norway", "Iceland", "Liechtenstein", "United Kingdom",
    "Switzerland", "Turkey",
}
MARKET_NAMES_CN = dict(zip(EUROPE_MARKETS, (
    "德国", "英国", "法国", "意大利", "俄罗斯", "西班牙", "土耳其", "荷兰", "瑞士", "波兰",
    "比利时", "瑞典", "奥地利", "挪威", "丹麦", "爱尔兰", "芬兰", "罗马尼亚", "捷克",
    "葡萄牙", "希腊", "匈牙利", "乌克兰", "斯洛伐克", "保加利亚", "克罗地亚", "塞尔维亚",
    "立陶宛", "斯洛文尼亚", "拉脱维亚", "爱沙尼亚", "塞浦路斯", "冰岛", "波斯尼亚和黑塞哥维那",
    "阿尔巴尼亚", "北马其顿", "摩尔多瓦", "格鲁吉亚", "亚美尼亚", "白俄罗斯", "阿塞拜疆",
    "黑山", "卢森堡", "马耳他", "科索沃", "列支敦士登", "摩纳哥", "安道尔", "圣马力诺", "梵蒂冈",
)))
OUTPUT_LANGUAGES = (
    "英语", "俄语", "德语", "法语", "意大利语", "西班牙语", "波兰语", "乌克兰语", "罗马尼亚语",
    "荷兰语", "土耳其语", "希腊语", "捷克语", "葡萄牙语", "瑞典语", "匈牙利语", "塞尔维亚语",
    "保加利亚语", "丹麦语", "芬兰语", "斯洛伐克语", "挪威语", "克罗地亚语", "波斯尼亚语",
    "阿尔巴尼亚语", "立陶宛语", "斯洛文尼亚语", "拉脱维亚语", "爱沙尼亚语", "马其顿语",
    "白俄罗斯语", "加泰罗尼亚语", "爱尔兰语", "格鲁吉亚语", "亚美尼亚语", "阿塞拜疆语",
    "卢森堡语", "马耳他语", "冰岛语", "威尔士语", "苏格兰盖尔语", "巴斯克语", "加利西亚语",
    "罗曼什语", "黑山语", "拉丁语",
)


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


class PolicyStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x620")
        self.minsize(820, 520)
        self.configure(bg=BLACK)
        if sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PolicyAmadeus.Desktop.2")

        self._icon_photo = None
        if sys.platform == "win32":
            # Keep the embedded multi-resolution ICO on Windows. Calling
            # iconphoto with the large PNG makes the taskbar downscale one
            # oversized bitmap and produces a visibly blurred small icon.
            try:
                self.iconbitmap(resource_path("app_icon.ico"))
            except tk.TclError:
                pass
        else:
            self._icon_photo = ImageTk.PhotoImage(Image.open(resource_path("app_icon.png")))
            self.iconphoto(True, self._icon_photo)

        self.country = tk.StringVar()
        self.country_display = tk.StringVar(value="点击此处选择销售国家")
        self.output_language = tk.StringVar()
        self.language_display = tk.StringVar(value="点击此处选择输出语言")
        self._country_choices = {name: tk.BooleanVar(value=False) for name in EUROPE_MARKETS}
        self.email, self.phone, self.pdf_path = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.store_name, self.website = tk.StringVar(), tk.StringVar()
        self.customs_mode = tk.StringVar(value="卖家承担（客户收货时不另付）")
        self.policies: list[tuple[str, str]] = []
        self.settings: dict[str, object] = {}
        self.copy_status = tk.StringVar(value="请选择要复制的政策")
        self.knowledge_status = tk.StringVar(value="正在检查政策知识库更新……")
        self._generation_queue: queue.Queue = queue.Queue()
        self.step = 0
        self._resize_job = None
        self._background_photo = None
        self._result_scroll_canvas = None
        self._country_popup = None
        self._language_popup = None
        self._source_image = Image.open(resource_path("ui_background.jpg")).convert("RGB")
        self._load_config()

        self.canvas = tk.Canvas(self, bg=BLACK, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.background_id = self.canvas.create_image(0, 0, anchor="nw")
        self.card = tk.Frame(self.canvas, bg=PANEL, highlightbackground=EDGE, highlightthickness=2)
        self.card_window = self.canvas.create_window(0, 0, window=self.card, width=640, height=400)
        self._build_card()
        start_startup_check()
        self.after(200, self._poll_knowledge_check)
        if sys.platform == "win32":
            self.after_idle(self._apply_windows_icons)
        self.after_idle(lambda: self._set_card_transparency(True))
        self.bind("<Configure>", self._schedule_render)
        self.after(30, self._render_background)
        self.show_step(0)

    def _config_path(self) -> Path:
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        return base / "policy_studio_config.json"

    def _load_config(self) -> None:
        try:
            data = json.loads(self._config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        self.store_name.set(str(data.get("store_name", "")))
        self.website.set(str(data.get("website", "")))
        self.email.set(str(data.get("email", "")))
        self.phone.set(str(data.get("phone", "")))
        saved_customs = str(data.get("customs_mode", "")).strip()
        if saved_customs in ("卖家承担（客户收货时不另付）", "消费者承担（结账前明确披露）", "不适用（境内或关税同盟内配送）"):
            self.customs_mode.set(saved_customs)
        self.pdf_path.set(str(data.get("license_pdf", "")))
        saved_language = str(data.get("output_language", "")).strip()
        if saved_language in OUTPUT_LANGUAGES:
            self.output_language.set(saved_language)
            self.language_display.set(saved_language)
        saved_countries = [item.strip() for item in re.split(r"[,，、;；\n]+", str(data.get("country", ""))) if item.strip()]
        selected = [name for name in saved_countries if name in self._country_choices and name in VERIFIED_MARKETS]
        for name in selected:
            self._country_choices[name].set(True)
        if selected:
            self.country.set("，".join(selected))
            self.country_display.set("、".join(MARKET_NAMES_CN.get(name, name) for name in selected))

    def _poll_knowledge_check(self) -> None:
        status = get_status()
        self.knowledge_status.set(str(status.get("message", "正在检查政策知识库更新……")))
        self.progress_status = status
        self._update_progress()
        self.after(300 if status.get("state") == "checking" else 5000, self._poll_knowledge_check)

    def _apply_windows_icons(self) -> None:
        """Force native small/large icons so Windows cannot reuse a stale taskbar bitmap."""
        try:
            self.update_idletasks()
            user32 = ctypes.windll.user32
            icon_path = str(resource_path("app_icon.ico"))
            load_from_file, image_icon = 0x0010, 1
            small = user32.LoadImageW(None, icon_path, image_icon, 32, 32, load_from_file)
            large = user32.LoadImageW(None, icon_path, image_icon, 48, 48, load_from_file)
            hwnd = self.winfo_id()
            user32.SendMessageW(hwnd, 0x0080, 0, small)  # WM_SETICON / ICON_SMALL
            user32.SendMessageW(hwnd, 0x0080, 1, large)  # WM_SETICON / ICON_BIG
            self._native_icons = (small, large)
        except Exception:
            self._native_icons = ()

    def _build_card(self) -> None:
        header = tk.Frame(self.card, bg=PANEL, padx=30, pady=9)
        header.pack(fill="x")
        tk.Label(header, text=APP_TITLE, bg=PANEL, fg=WHITE, font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="三步完成店铺基础资料设置", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(5, 0))
        tk.Label(header, textvariable=self.knowledge_status, bg=PANEL, fg=ORANGE,
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(1, 0))
        self.progress_text = tk.StringVar(value="0% · 预计剩余：正在估算")
        tk.Label(self.card, textvariable=self.progress_text, bg=PANEL, fg=ORANGE,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=30, pady=(2, 3))
        self.progress = tk.Canvas(self.card, height=8, bg="#303640", highlightthickness=0)
        self.progress.pack(fill="x", padx=30)
        self.progress_fill = self.progress.create_rectangle(0, 0, 0, 8, fill=ORANGE, outline="")
        self.progress.bind("<Configure>", lambda _: self._update_progress())
        self.footer = tk.Frame(self.card, bg=PANEL, padx=30, pady=10)
        self.footer.pack(side="bottom", fill="x")
        self.content = tk.Frame(self.card, bg=PANEL, padx=30, pady=14)
        self.content.pack(side="top", fill="both", expand=True)

    def _set_card_transparency(self, enabled: bool) -> None:
        """Apply/reset the single-window panel layer and its Windows paint cache."""
        if sys.platform != "win32" or not self.card.winfo_exists():
            return
        try:
            self.card.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = self.card.winfo_id()
            style = user32.GetWindowLongPtrW(hwnd, -20)
            layered = 0x00080000
            user32.SetWindowLongPtrW(hwnd, -20, (style | layered) if enabled else (style & ~layered))
            if enabled:
                user32.SetLayeredWindowAttributes(hwnd, 0, 184, 0x00000002)
            # Force Tk and Windows to discard stale child-control images.
            user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)
        except Exception:
            pass

    def _schedule_render(self, _event=None) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, self._render_background)

    def _render_background(self) -> None:
        """Fit the whole image inside the window. Never crop any image content."""
        self._resize_job = None
        if not self.winfo_ismapped():
            self.after(80, self._render_background)
            return
        self.update_idletasks()
        width, height = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        iw, ih = self._source_image.size
        scale = min(width / iw, height / ih)
        rw, rh = max(int(iw * scale), 1), max(int(ih * scale), 1)
        fitted = self._source_image.resize((rw, rh), Image.Resampling.LANCZOS)
        self._background_photo = ImageTk.PhotoImage(fitted)
        self.canvas.itemconfigure(self.background_id, image=self._background_photo)
        self.canvas.coords(self.background_id, (width - rw) // 2, (height - rh) // 2)
        # Keep as much of the artwork visible as possible.  The result page needs
        # a little more room; the three input pages deliberately use a small card.
        if self.step == 3:
            card_width = min(720, max(width - 150, 640))
            card_height = min(470, max(height - 100, 440))
        else:
            card_width = min(640, max(width - 220, 540))
            card_height = min(500, max(height - 55, 440))
        self.canvas.coords(self.card_window, width // 2, height // 2)
        self.canvas.itemconfigure(self.card_window, width=card_width, height=card_height)

    def _clear(self, widget: tk.Widget) -> None:
        for child in widget.winfo_children():
            child.destroy()

    def _update_progress(self) -> None:
        status = getattr(self, "progress_status", {"state": "checking", "progress_percent": 0})
        ratio = max(0, min(100, int(status.get("progress_percent", 100 if status.get("checked_at") else 0)))) / 100
        self.progress_text.set(progress_caption(status))
        self.progress.coords(self.progress_fill, 0, 0, self.progress.winfo_width() * ratio, 8)

    def show_step(self, step: int) -> None:
        self.step = step
        self._set_card_transparency(False)
        if self._country_popup is not None and self._country_popup.winfo_exists():
            self._country_popup.destroy()
        self._country_popup = None
        if self._language_popup is not None and self._language_popup.winfo_exists():
            self._language_popup.destroy()
        self._language_popup = None
        self.unbind_all("<MouseWheel>")
        self._result_scroll_canvas = None
        self._clear(self.content)
        self._clear(self.footer)
        self.content.configure(padx=30, pady=14)
        self._update_progress()
        (self._country_step, self._email_step, self._pdf_step, self._complete_step)[step]()
        self.after_idle(lambda: self._set_card_transparency(True))
        self.after_idle(self._render_background)

    def _heading(self, number: str, title: str, description: str, compact: bool = False) -> None:
        tk.Label(self.content, text=number, bg=PANEL, fg=ORANGE, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        tk.Label(self.content, text=title, bg=PANEL, fg=WHITE, font=("Microsoft YaHei UI", 17 if compact else 19, "bold")).pack(anchor="w", pady=(3 if compact else 7, 2 if compact else 4))
        tk.Label(self.content, text=description, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9 if compact else 10)).pack(anchor="w", pady=(0, 7 if compact else 19))

    def _entry(self, variable: tk.StringVar, show: str = "") -> tk.Entry:
        entry = tk.Entry(self.content, textvariable=variable, bg="#f8fafc", fg="#101827", insertbackground="#101827",
                         relief="flat", highlightthickness=2, highlightbackground="#d1d7e0", highlightcolor=ORANGE,
                         font=("Microsoft YaHei UI", 11), show=show)
        entry.pack(fill="x", ipady=9)
        return entry

    def _field_label(self, text: str) -> None:
        tk.Label(self.content, text=text, bg=PANEL, fg=WHITE, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 7))

    def _button(self, parent, text, command, primary=False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=ORANGE if primary else "#343b47", fg=WHITE,
                         activebackground="#f28542" if primary else "#4b5565", activeforeground=WHITE,
                         relief="flat", cursor="hand2", padx=22, pady=9,
                         font=("Microsoft YaHei UI", 10, "bold" if primary else "normal"))

    def _app_dialog(self, title: str, message: str, input_value: str | None = None) -> str | None:
        """Single-window translucent replacement for native white message boxes."""
        result = tk.StringVar(value="__WAITING__")
        overlay = tk.Frame(self.card, bg="#080c12")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        panel = tk.Frame(overlay, bg="#151d28", highlightbackground=ORANGE, highlightthickness=1,
                         padx=18, pady=14)
        panel.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.72)
        tk.Label(panel, text=title, bg="#151d28", fg=ORANGE,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        tk.Label(panel, text=message, bg="#151d28", fg=WHITE, justify="left", wraplength=410,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", fill="x", pady=(7, 10))
        entry = None
        if input_value is not None:
            entry = tk.Entry(panel, bg="#f5f7fa", fg="#101827", insertbackground="#101827",
                             relief="flat", font=("Microsoft YaHei UI", 10))
            entry.insert(0, input_value); entry.pack(fill="x", ipady=7, pady=(0, 10)); entry.focus_set()
        actions = tk.Frame(panel, bg="#151d28"); actions.pack(fill="x")

        def confirm() -> None:
            result.set(entry.get().strip() if entry is not None else "__OK__")

        if entry is not None:
            self._button(actions, "取消", lambda: result.set("__CANCEL__")).pack(side="right", padx=(7, 0))
            entry.bind("<Return>", lambda _e: confirm())
        self._button(actions, "确定", confirm, True).pack(side="right")
        overlay.lift(); self.wait_variable(result); value = result.get(); overlay.destroy()
        return None if value == "__CANCEL__" else value

    def _country_step(self) -> None:
        self._heading("步骤 1 / 3", "选择销售国家和输出语言", "销售国家支持多选；政策覆盖全部所选国家，并统一翻译成指定语言。")
        self._field_label("销售国家（点击展开，可多选）")
        market_button = tk.Button(
            self.content, textvariable=self.country_display, anchor="w", bg="#1d2430", fg=WHITE,
            activebackground="#293342", activeforeground=WHITE, relief="flat", cursor="hand2",
            font=("Microsoft YaHei UI", 10), padx=10, pady=9, command=self._toggle_country_popup,
        )
        market_button.pack(fill="x")
        self._field_label("输出政策语言（点击展开，单选）")
        language_entry = tk.Button(
            self.content, textvariable=self.language_display, anchor="w", bg="#1d2430", fg=WHITE,
            activebackground="#293342", activeforeground=WHITE, relief="flat", cursor="hand2",
            font=("Microsoft YaHei UI", 10), padx=10, pady=9, command=self._toggle_language_popup,
        )
        language_entry.pack(fill="x")
        self._button(self.footer, "下一步", self._next_country, True).pack(side="right")

    def _update_country_selection(self) -> None:
        selected = [name for name in EUROPE_MARKETS if name in VERIFIED_MARKETS and self._country_choices[name].get()]
        self.country.set("，".join(selected))
        selected_cn = [MARKET_NAMES_CN[name] for name in selected]
        self.country_display.set(
            f"已选择 {len(selected_cn)} 个：" + "、".join(selected_cn)
            if selected_cn else "点击此处选择销售国家"
        )

    def _toggle_country_popup(self) -> None:
        if self._language_popup is not None and self._language_popup.winfo_exists():
            self._language_popup.destroy(); self._language_popup = None
        if self._country_popup is not None and self._country_popup.winfo_exists():
            self._country_popup.destroy()
            self._country_popup = None
            return
        popup = tk.Frame(self.card, bg="#111823", highlightbackground=ORANGE, highlightthickness=1)
        popup.place(relx=0.5, rely=0.53, anchor="center", relwidth=0.88, relheight=0.72)
        self._country_popup = popup
        tk.Label(popup, text="选择销售国家（可多选）", bg="#111823", fg=WHITE,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
        list_row = tk.Frame(popup, bg="#111823")
        list_row.pack(fill="both", expand=True, padx=9)
        scrollbar = ttk.Scrollbar(list_row, orient="vertical")
        country_list = tk.Listbox(
            list_row, selectmode="multiple", exportselection=False, yscrollcommand=scrollbar.set,
            bg="#18212d", fg=WHITE, selectbackground=ORANGE, selectforeground=WHITE,
            relief="flat", highlightthickness=0, font=("Microsoft YaHei UI", 9), activestyle="none",
        )
        scrollbar.configure(command=country_list.yview)
        scrollbar.pack(side="right", fill="y")
        country_list.pack(side="left", fill="both", expand=True)
        selectable_markets = [market for market in EUROPE_MARKETS if market in VERIFIED_MARKETS]
        for index, market in enumerate(selectable_markets):
            country_list.insert("end", MARKET_NAMES_CN[market])
            if self._country_choices[market].get():
                country_list.selection_set(index)

        def commit_selection(_event=None) -> None:
            selected_indices = set(country_list.curselection())
            for index, market in enumerate(selectable_markets):
                self._country_choices[market].set(index in selected_indices)
            self._update_country_selection()

        country_list.bind("<<ListboxSelect>>", commit_selection)
        self._button(popup, "完成选择", self._toggle_country_popup, True).pack(anchor="e", padx=9, pady=7)
        popup.lift()

    def _toggle_language_popup(self) -> None:
        if self._country_popup is not None and self._country_popup.winfo_exists():
            self._country_popup.destroy(); self._country_popup = None
        if self._language_popup is not None and self._language_popup.winfo_exists():
            self._language_popup.destroy(); self._language_popup = None
            return
        popup = tk.Frame(self.card, bg="#111823", highlightbackground=ORANGE, highlightthickness=1)
        popup.place(relx=0.5, rely=0.53, anchor="center", relwidth=0.78, relheight=0.70)
        self._language_popup = popup
        tk.Label(popup, text="选择政策输出语言（单选）", bg="#111823", fg=WHITE,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
        list_row = tk.Frame(popup, bg="#111823"); list_row.pack(fill="both", expand=True, padx=9)
        scrollbar = ttk.Scrollbar(list_row, orient="vertical")
        language_list = tk.Listbox(
            list_row, selectmode="browse", exportselection=False, yscrollcommand=scrollbar.set,
            bg="#18212d", fg=WHITE, selectbackground=ORANGE, selectforeground=WHITE,
            relief="flat", highlightthickness=0, font=("Microsoft YaHei UI", 9), activestyle="none",
        )
        scrollbar.configure(command=language_list.yview)
        scrollbar.pack(side="right", fill="y"); language_list.pack(side="left", fill="both", expand=True)
        for index, language in enumerate(OUTPUT_LANGUAGES):
            language_list.insert("end", language)
            if language == self.output_language.get():
                language_list.selection_set(index); language_list.see(index)

        def choose(_event=None) -> None:
            selection = language_list.curselection()
            if selection:
                value = OUTPUT_LANGUAGES[selection[0]]
                self.output_language.set(value); self.language_display.set(value)

        language_list.bind("<<ListboxSelect>>", choose)
        language_list.bind("<Double-Button-1>", lambda _e: self._toggle_language_popup())
        self._button(popup, "完成选择", self._toggle_language_popup, True).pack(anchor="e", padx=9, pady=7)
        popup.lift()

    def _email_step(self) -> None:
        self.content.configure(pady=7)
        self._heading("步骤 2 / 3", "输入店铺与客服资料", "这些资料用于明确网站运营者、卖家和客户联系方式。", compact=True)

        def compact_field(label: str, variable: tk.StringVar, parent=None) -> tk.Entry:
            parent = parent or self.content
            tk.Label(parent, text=label, bg=PANEL, fg=WHITE,
                     font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(3, 2))
            item = tk.Entry(parent, textvariable=variable, bg="#f8fafc", fg="#101827",
                            insertbackground="#101827", relief="flat", highlightthickness=2,
                            highlightbackground="#d1d7e0", highlightcolor=ORANGE,
                            font=("Microsoft YaHei UI", 10))
            item.pack(fill="x", ipady=6)
            return item

        compact_field("店铺名称 / 品牌名", self.store_name)
        compact_field("网站域名（例如 https://example.com）", self.website)
        contacts = tk.Frame(self.content, bg=PANEL)
        contacts.pack(fill="x", pady=(1, 0))
        email_box, phone_box = tk.Frame(contacts, bg=PANEL), tk.Frame(contacts, bg=PANEL)
        email_box.pack(side="left", fill="x", expand=True, padx=(0, 5))
        phone_box.pack(side="left", fill="x", expand=True, padx=(5, 0))
        compact_field("客服邮箱", self.email, email_box)
        entry = compact_field("客服电话", self.phone, phone_box)
        tk.Label(self.content, text="关税及进口税承担方式", bg=PANEL, fg=WHITE,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(4, 2))
        customs_box = ttk.Combobox(
            self.content, textvariable=self.customs_mode, state="readonly",
            values=("卖家承担（客户收货时不另付）", "消费者承担（结账前明确披露）", "不适用（境内或关税同盟内配送）"),
            font=("Microsoft YaHei UI", 10),
        )
        customs_box.pack(fill="x", ipady=3)
        entry.focus_set(); entry.bind("<Return>", lambda _: self._next_email())
        self._button(self.footer, "上一步", lambda: self.show_step(0)).pack(side="left")
        self._button(self.footer, "下一步", self._next_email, True).pack(side="right")

    def _pdf_step(self) -> None:
        self._heading("步骤 3 / 3", "导入公司执照", "请选择 PDF 格式的公司注册文件或营业执照。")
        self._field_label("执照 PDF")
        row = tk.Frame(self.content, bg=PANEL); row.pack(fill="x")
        tk.Entry(row, textvariable=self.pdf_path, state="readonly", readonlybackground="#f8fafc", fg="#101827",
                 relief="flat", font=("Microsoft YaHei UI", 10)).pack(side="left", fill="x", expand=True, ipady=10)
        self._button(row, "选择 PDF", self._choose_pdf).pack(side="left", padx=(10, 0))
        phone_text = f"客服电话：{self.phone.get()}"
        tk.Label(self.content, text=phone_text, bg=PANEL, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(9, 0))
        self._button(self.footer, "上一步", lambda: self.show_step(1)).pack(side="left")
        self._button(self.footer, "完成", self._finish, True).pack(side="right")

    def _complete_step(self) -> None:
        self.content.configure(padx=18, pady=5)
        viewport = tk.Frame(self.content, bg=PANEL)
        viewport.pack(fill="both", expand=True)
        scroll_canvas = tk.Canvas(viewport, bg=PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(scroll_canvas, bg=PANEL, padx=6, pady=2)
        body_window = scroll_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.bind("<Configure>", lambda e: scroll_canvas.itemconfigure(body_window, width=e.width))
        self._result_scroll_canvas = scroll_canvas
        self.bind_all("<MouseWheel>", self._scroll_result)

        title_row = tk.Frame(body, bg=PANEL)
        title_row.pack(fill="x", pady=(0, 4))
        tk.Label(title_row, text="政策与填写信息", bg=PANEL, fg=WHITE,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        tk.Label(title_row, text=f"  {self.country.get()} · 已生成",
                 bg=PANEL, fg=ORANGE, font=("Microsoft YaHei UI", 8, "bold")).pack(side="left", pady=(4, 0))
        labels = (
            "复制退款政策", "复制隐私政策", "复制服务条款",
            "复制物流政策", "复制联系信息", "复制法律声明",
        )
        grid = tk.Frame(body, bg=PANEL)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        for index, label in enumerate(labels):
            button = self._button(grid, label, lambda i=index: self._copy_policy(i), primary=True)
            button.configure(pady=3, font=("Microsoft YaHei UI", 8, "bold"))
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 4) if index % 2 == 0 else (4, 0), pady=2)

        tk.Label(body, text="后台填写信息", bg=PANEL, fg=ORANGE,
                 font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w", pady=(4, 2))
        form = tk.Frame(body, bg="#171c24", padx=7, pady=3,
                        highlightbackground="#313945", highlightthickness=1)
        form.pack(fill="x")

        def numbers(value: str, fallback: tuple[str, str]) -> tuple[str, str]:
            found = re.findall(r"\d+", value)
            return (found[0], found[1] if len(found) > 1 else found[0]) if found else fallback

        markets = self.settings.get("markets") or [self.settings]
        extracted = []
        licence_fields = self.settings.get("license_fields") or markets[0].get("license_fields", {})
        licence_labels = (
            ("资料类型", "profile_type"), ("组织名称", "organization_name"),
            ("法定名称", "legal_name"), ("公司注册号", "registration_number"),
            ("企业/法人形式", "legal_form"), ("法定代表人/董事", "authorized_representative"),
            ("登记机关", "register_name"), ("VAT ID（仅执照明确记载时）", "vat_id"),
            ("街道地址", "street_address"), ("公寓/套房/门牌号", "unit"),
            ("邮政编码", "postal_code"), ("城市/区", "city"),
            ("国家/地区", "country"), ("D-U-N-S 编码", "duns_number"),
            ("名字", "first_name"), ("姓氏", "last_name"),
        )
        for label, key in licence_labels:
            value = str(licence_fields.get(key, "")).strip()
            extracted.append((f"执照 · {label}", value or "未识别（请对照执照手动确认）"))
        def country_names(items) -> str:
            return compact_market_scope(markets, items)

        def add_grouped(title: str, value_for_market, add_destinations: bool = False) -> None:
            groups = group_market_values(markets, value_for_market)
            for group in groups:
                members = group["markets"]
                country = country_names(members)
                value = str(group["value"])
                if add_destinations:
                    value += f"；目的地选择：{country}"
                extracted.append((f"适用地区：{country} · {title}", value))

        legal_names = {
            "EU": "欧盟统一消费者规则", "UK": "英国消费者规则", "EEA": "欧洲经济区消费者规则",
            "CH": "瑞士消费者规则", "TR": "土耳其消费者规则",
        }
        add_grouped("法律分组", lambda m: f"共同适用：{legal_names.get(str(m['jurisdiction_group']), str(m['country']) + '当地消费者规则')}")
        add_grouped("订单处理", lambda m: (lambda n: f"最短填写：{n[0]}；最长填写：{n[1]}；履单日选择：{m['processing_days']}")(numbers(str(m["processing_time"]), ("1", "3"))))
        add_grouped("运输时间", lambda m: (lambda n: f"运输时间选择：自定义；最短填写：{n[0]}；最长填写：{n[1]}；运输日选择：{m['shipping_days']}")(numbers(str(m["shipping_time"]), ("3", "7"))), True)
        add_grouped("标准配送费用", lambda m: m.get("shipping_cost", "未明确"))
        add_grouped("关税及进口税承担", lambda m: m.get("customs_responsibility", "未明确"))
        add_grouped("退货", lambda m: "退货选择：是，我接受有缺陷和无缺陷商品的退货" if "非瑕疵" in str(m["returns"]) else "退货选择：我只接受有缺陷商品的退货")
        add_grouped("换货", lambda m: "换货选择：是，我接受换货" if "接受换货" in str(m["exchanges"]) else "换货选择：否，我不接受换货")
        add_grouped("退款处理时间（天）", lambda m: f"在“天数”输入框填写：{m.get('refund_days_value') or (re.findall(r'\d+', str(m['refund_time'])) or ['14'])[0]}\n对应政策：{m['refund_time']}")
        add_grouped("商品状况", lambda m: "商品状况选择：全新和略微使用过的商品" if "检查性质" in str(m["condition"]) else "商品状况选择：仅限新商品")
        add_grouped("退货期限", lambda m: f"退货期限选择：在特定天数内；天数填写：{(re.findall(r'\d+', str(m['return_window'])) or ['14'])[0]}")
        add_grouped("退货方式", lambda m: f"退货方式选择：{m['return_method']}")
        add_grouped("退货运费选择", lambda m: (
            "平台选项填写：免费退货\n补充说明：使用购买前指定的承运人退货，客户不承担退货运费；瑕疵、损坏或错发同样由商家承担。"
            if str(m.get("return_shipping_mode")) == "free_designated_carrier" else
            "平台选项填写：客户负责退货运费\n补充说明：无理由退货由客户承担直接退货运费（须在购买前告知）；瑕疵、损坏或错发由商家承担退货运费。"
        ))
        add_grouped("重新入库费", lambda m: m["restocking_fee"])
        add_grouped("法定撤回权", lambda m: f"法定期限：{m['statutory_withdrawal']}；如另有自愿商业退货承诺，必须与法定权利分别说明")
        add_grouped("法定质量保证", lambda m: m.get("legal_guarantee_cn", m["legal_guarantee"]))
        add_grouped("电子撤回功能", lambda m: m["withdrawal_function"])
        add_grouped("GMC语言一致性", lambda m: m["language_consistency"])
        add_grouped("一致性检查", lambda m: f"状态：{m.get('validation_status', '未执行')}\n已检查：{'、'.join(str(x) for x in m.get('validation_checks', []))}")
        add_grouped("检查警告", lambda m: "\n".join(str(x) for x in m.get("validation_warnings", [])) or "无")
        add_grouped("知识库更新检查", lambda m: m.get("knowledge_update_status", "未执行"))
        add_grouped("AI辅助审阅", lambda m: f"{m.get('ai_audit_status', '未启用')}\n" + ("\n".join(str(x) for x in m.get("ai_audit_findings", [])) or "无额外发现"))
        add_grouped("官方核验状态", lambda m: f"{m['coverage_status']}；核验日期：{m['verified_on']}")
        add_grouped("官方依据", lambda m: "\n".join(str(item) for item in m["official_sources"]))
        for index, (name, value) in enumerate(extracted):
            row, column = divmod(index, 2)
            box = tk.Frame(form, bg="#1d2430", padx=7, pady=4)
            box.grid(row=row, column=column, sticky="nsew", padx=3, pady=3)
            heading = tk.Frame(box, bg="#1d2430")
            heading.pack(fill="x")
            tk.Label(heading, text=name, bg="#1d2430", fg=ORANGE,
                     font=("Microsoft YaHei UI", 8, "bold")).pack(side="left")

            def copy_field(v=value, n=name) -> None:
                self.clipboard_clear(); self.clipboard_append(v); self.update()
                self.copy_status.set(f"已复制：{n}")

            tk.Button(heading, text="复制", command=copy_field, bg="#343b47", fg=WHITE,
                      activebackground=ORANGE, activeforeground=WHITE, relief="flat",
                      padx=5, pady=0, font=("Microsoft YaHei UI", 7)).pack(side="right")
            line_count = max(1, min(5, value.count("\n") + (len(value) // 48) + 1))
            text_box = tk.Text(box, height=line_count, bg="#1d2430", fg=WHITE,
                               selectbackground=ORANGE, selectforeground=WHITE, relief="flat",
                               wrap="word", font=("Microsoft YaHei UI", 8), padx=0, pady=1)
            text_box.insert("1.0", value)
            text_box.configure(state="disabled")
            text_box.pack(fill="x", pady=(1, 0))
        form.grid_columnconfigure(0, weight=1, uniform="result")
        form.grid_columnconfigure(1, weight=1, uniform="result")

        tk.Label(body, textvariable=self.copy_status, bg=PANEL, fg=MUTED,
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(2, 0))
        self._button(self.footer, "重新编辑", lambda: self.show_step(0)).pack(side="left")
        self._button(self.footer, "关闭", self.destroy).pack(side="right")

    def _scroll_result(self, event) -> None:
        canvas = self._result_scroll_canvas
        if canvas is not None and canvas.winfo_exists():
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _copy_policy(self, index: int) -> None:
        title, policy = self.policies[index]
        self.clipboard_clear()
        self.clipboard_append(policy)
        self.update()
        self.copy_status.set(f"已复制：{title}")

    def _next_country(self) -> None:
        selected = [name for name in EUROPE_MARKETS if self._country_choices[name].get()]
        if not selected:
            self._app_dialog("请填写国家", "请至少选择一个销售国家后再继续。"); return
        value = "，".join(selected)
        language = self.output_language.get().strip()
        if not language:
            self._app_dialog("请选择输出语言", "请选择六份政策统一使用的输出语言。"); return
        self.country.set(value); self.show_step(1)

    def _next_email(self) -> None:
        if not self.store_name.get().strip():
            self._app_dialog("请输入店铺名称", "请输入网站对外显示的店铺或品牌全称。"); return
        website = self.website.get().strip()
        if not re.match(r"^https?://", website, re.I):
            website = f"https://{website}"
        if not re.fullmatch(r"https?://(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}(?::\d{1,5})?(?:/[^\s]*)?", website, re.I):
            self._app_dialog("网站格式不正确", "请输入有效域名，例如 example.com 或 https://example.com。"); return
        self.website.set(website)
        value = self.email.get().strip()
        if not EMAIL_PATTERN.match(value):
            self._app_dialog("邮箱格式不正确", "请输入有效邮箱，例如 support@example.com。"); return
        phone = self.phone.get().strip()
        if len(re.sub(r"\D", "", phone)) < 7:
            self._app_dialog("电话格式不正确", "请输入政策中统一使用的客服电话，至少包含 7 位数字。"); return
        self.phone.set(phone)
        self.email.set(value); self.show_step(2)

    def _choose_pdf(self) -> None:
        selected = filedialog.askopenfilename(parent=self, title="选择公司执照 PDF", filetypes=(("PDF 文件", "*.pdf"),))
        if not selected:
            return
        self.pdf_path.set(selected)
        self.show_step(2)

    def _ask_for_phone(self) -> bool:
        value = self._app_dialog("请输入客服电话", "请输入所有政策中统一使用的客服电话：", self.phone.get())
        if value and len(re.sub(r"\D", "", value)) >= 7:
            self.phone.set(value.strip())
            return True
        self.phone.set("")
        if value is not None:
            self._app_dialog("电话格式不正确", "客服电话至少应包含 7 位数字。")
        return False

    def _finish(self) -> None:
        path = Path(self.pdf_path.get())
        if not path.is_file() or path.suffix.lower() != ".pdf":
            self._app_dialog("请选择 PDF", "请导入一个有效的执照 PDF 文件。"); return
        if len(re.sub(r"\D", "", self.phone.get())) < 7:
            self._app_dialog("客服电话缺失", "请返回上一步填写有效客服电话。"); return
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        data = {"country": self.country.get(), "output_language": self.output_language.get(), "store_name": self.store_name.get(), "website": self.website.get(), "email": self.email.get(), "phone": self.phone.get(), "customs_mode": self.customs_mode.get(), "license_pdf": self.pdf_path.get()}
        try:
            self._config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self._app_dialog("保存失败", f"无法保存配置：\n{exc}"); return
        self._show_generating()
        worker = threading.Thread(target=self._generate_worker, daemon=True)
        worker.start()
        self.after(100, self._poll_generation)

    def _show_generating(self) -> None:
        self._clear(self.content)
        self._clear(self.footer)
        self._heading("正在生成", "正在生成并翻译六份政策", "网络翻译可能需要几十秒。窗口可以正常移动，请不要重复点击。")
        bar = ttk.Progressbar(self.content, mode="indeterminate", length=420)
        bar.pack(fill="x", pady=(20, 12))
        bar.start(12)
        tk.Label(self.content, text="正在整理国家规则、执照资料并翻译政策……",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        self._button(self.footer, "关闭", self.destroy).pack(side="right")

    def _generate_worker(self) -> None:
        try:
            result = generate_translated_bundle(
                self.country.get(), self.email.get(), self.phone.get(), self.pdf_path.get(), self.output_language.get(),
                self.store_name.get(), self.website.get(), self.customs_mode.get()
            )
            self._generation_queue.put(("ok", result))
        except Exception as exc:
            self._generation_queue.put(("error", str(exc)))

    def _poll_generation(self) -> None:
        try:
            status, payload = self._generation_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_generation)
            return
        if status == "error":
            self._app_dialog("无法生成政策", payload)
            self.show_step(2)
            return
        self.policies, self.settings = payload
        self.copy_status.set("请选择要复制的政策")
        self.show_step(3)


if __name__ == "__main__":
    if "--auto-update" in sys.argv:
        from app_updater import run_auto_update

        run_auto_update()
    else:
        from app_updater import start_app_update_check, start_schedule_registration

        start_schedule_registration()
        start_app_update_check()
        PolicyStudio().mainloop()
