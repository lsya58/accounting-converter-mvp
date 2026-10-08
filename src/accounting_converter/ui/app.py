from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk
except ModuleNotFoundError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
    tkfont = None

from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import AppState, UserFacingStatus, present_main_screen


GUI_PALETTE = {
    "page": "#F3F5F7",
    "surface": "#FFFFFF",
    "border": "#D9E0E7",
    "text": "#1F2933",
    "muted": "#667481",
    "accent": "#1769AA",
    "accent_hover": "#0F578F",
    "ready": "#247A43",
    "ready_soft": "#E8F4EC",
    "confirm": "#996515",
    "confirm_soft": "#FFF4D8",
    "blocked": "#B33636",
    "blocked_soft": "#FBEAEA",
    "neutral_soft": "#EAF0F5",
}
WINDOWS_FONT_CANDIDATES = ("Yu Gothic UI", "Meiryo UI", "Segoe UI")


def status_visual(status: UserFacingStatus) -> tuple[str, str, str]:
    return {
        UserFacingStatus.READY: ("準備完了", GUI_PALETTE["ready"], GUI_PALETTE["ready_soft"]),
        UserFacingStatus.CONFIRM: ("要確認", GUI_PALETTE["confirm"], GUI_PALETTE["confirm_soft"]),
        UserFacingStatus.BLOCKED: ("停止", GUI_PALETTE["blocked"], GUI_PALETTE["blocked_soft"]),
        UserFacingStatus.SUCCESS: ("完了", GUI_PALETTE["ready"], GUI_PALETTE["ready_soft"]),
        UserFacingStatus.NEEDS_INPUT: ("未準備", GUI_PALETTE["muted"], GUI_PALETTE["neutral_soft"]),
    }[status]


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


class AccountingConverterApp:
    def __init__(self, root: object) -> None:
        if tk is None or ttk is None or filedialog is None or messagebox is None or tkfont is None:
            raise RuntimeError("tkinter is required to run the desktop GUI.")
        self.root = root
        self.controller = AccountingConverterController()
        self.profile_ids: list[str] = []
        self.settings_window = None
        self.root.title("会計データ変換")
        self.root.geometry("860x760")
        self.root.minsize(720, 620)

        self.file_var = tk.StringVar(value="ファイルはまだ選択されていません")
        self.recognition_var = tk.StringVar()
        self.output_var = tk.StringVar(value="保存先はまだ選択されていません")
        self.status_title_var = tk.StringVar(value="CSVを選択してください")
        self.status_detail_var = tk.StringVar(value="変換する仕訳CSVを選択してください。")
        self.result_var = tk.StringVar()
        self.profile_var = tk.StringVar()
        self.settings_context_var = tk.StringVar(value="未設定")
        self.settings_message_var = tk.StringVar()
        self.font_family = self._configure_fonts()
        self._configure_styles()
        self._build()
        self._render(self.controller.load_profiles())

    def _configure_fonts(self) -> str:
        available = set(tkfont.families(self.root))
        family = next(
            (candidate for candidate in WINDOWS_FONT_CANDIDATES if candidate in available),
            tkfont.nametofont("TkDefaultFont").actual("family"),
        )
        for name, size, weight in (
            ("TkDefaultFont", 10, "normal"),
            ("TkTextFont", 10, "normal"),
            ("TkMenuFont", 10, "normal"),
            ("TkHeadingFont", 10, "bold"),
        ):
            tkfont.nametofont(name).configure(family=family, size=size, weight=weight)
        return family

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if sys.platform == "win32" and "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Page.TFrame", background=GUI_PALETTE["page"])
        style.configure("Card.TFrame", background=GUI_PALETTE["surface"], relief="solid", borderwidth=1)
        style.configure("Header.TFrame", background=GUI_PALETTE["page"])
        style.configure("Title.TLabel", background=GUI_PALETTE["page"], foreground=GUI_PALETTE["text"], font=(self.font_family, 22, "bold"))
        style.configure("Subtitle.TLabel", background=GUI_PALETTE["page"], foreground=GUI_PALETTE["muted"], font=(self.font_family, 10))
        style.configure("Section.TLabel", background=GUI_PALETTE["surface"], foreground=GUI_PALETTE["text"], font=(self.font_family, 12, "bold"))
        style.configure("Body.TLabel", background=GUI_PALETTE["surface"], foreground=GUI_PALETTE["text"], font=(self.font_family, 10))
        style.configure("Muted.TLabel", background=GUI_PALETTE["surface"], foreground=GUI_PALETTE["muted"], font=(self.font_family, 9))
        style.configure("Secondary.TButton", font=(self.font_family, 10), padding=(14, 8))

    def _build(self) -> None:
        self.root.configure(background=GUI_PALETTE["page"])
        container = ttk.Frame(self.root, style="Page.TFrame")
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(container, highlightthickness=0, background=GUI_PALETTE["page"])
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        main = ttk.Frame(self.canvas, padding=(42, 30, 42, 40), style="Page.TFrame")
        self._canvas_window = self.canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_scroll_content)
        self.root.bind_all("<MouseWheel>", self._on_mouse_wheel)
        main.columnconfigure(0, weight=1)

        header = ttk.Frame(main, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="会計データ変換", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="設定", style="Secondary.TButton", command=self._open_settings).grid(row=0, column=1, sticky="e")
        ttk.Label(main, text="仕訳データをJDL用CSVへ安全に変換します", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(5, 26)
        )

        input_section = ttk.Frame(main, padding=(22, 20), style="Card.TFrame")
        input_section.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        input_section.columnconfigure(0, weight=1)
        self._step_heading(input_section, "1", "変換するCSV").grid(row=0, column=0, sticky="w")
        ttk.Button(input_section, text="ファイルを選択", style="Secondary.TButton", command=self._select_file).grid(row=0, column=1, sticky="e")
        ttk.Label(input_section, textvariable=self.file_var, style="Body.TLabel", wraplength=600).grid(row=1, column=0, columnspan=2, sticky="w", pady=(16, 3))
        ttk.Label(input_section, textvariable=self.recognition_var, style="Muted.TLabel", wraplength=680).grid(row=2, column=0, columnspan=2, sticky="w")

        output_section = ttk.Frame(main, padding=(22, 20), style="Card.TFrame")
        output_section.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        output_section.columnconfigure(0, weight=1)
        self._step_heading(output_section, "2", "保存先").grid(row=0, column=0, sticky="w")
        ttk.Button(output_section, text="変更", style="Secondary.TButton", command=self._select_output).grid(row=0, column=1, sticky="e")
        ttk.Label(output_section, textvariable=self.output_var, style="Body.TLabel", wraplength=680).grid(row=1, column=0, columnspan=2, sticky="w", pady=(16, 0))

        self.status_frame = ttk.Frame(main, padding=(22, 20), style="Card.TFrame")
        self.status_frame.grid(row=4, column=0, sticky="ew", pady=(0, 18))
        self.status_frame.columnconfigure(0, weight=1)
        heading = self._step_heading(self.status_frame, "3", "状態と実行")
        heading.grid(row=0, column=0, sticky="w")
        self.status_badge = tk.Label(
            self.status_frame,
            text="未準備",
            font=(self.font_family, 9, "bold"),
            padx=10,
            pady=4,
            borderwidth=0,
        )
        self.status_badge.grid(row=0, column=1, sticky="e")
        self.status_label = ttk.Label(self.status_frame, textvariable=self.status_title_var, style="Section.TLabel")
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(18, 0))
        ttk.Label(self.status_frame, textvariable=self.status_detail_var, style="Muted.TLabel", wraplength=680, justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.settings_action = ttk.Button(self.status_frame, text="設定を確認する", style="Secondary.TButton", command=self._open_settings)
        self.settings_action.grid(row=3, column=0, sticky="w", pady=(14, 0))

        self.convert_button = tk.Button(
            self.status_frame,
            text="変換する",
            font=(self.font_family, 12, "bold"),
            foreground="#FFFFFF",
            background=GUI_PALETTE["accent"],
            activeforeground="#FFFFFF",
            activebackground=GUI_PALETTE["accent_hover"],
            disabledforeground="#8A949E",
            relief="flat",
            borderwidth=0,
            padx=46,
            pady=13,
            cursor="hand2",
            command=self._convert,
            state="disabled",
        )
        self.convert_button.grid(row=3, column=1, sticky="e", pady=(14, 0))
        self.convert_button.bind("<Enter>", self._on_primary_enter)
        self.convert_button.bind("<Leave>", self._on_primary_leave)

        self.result_frame = ttk.Frame(main, padding=(22, 20), style="Card.TFrame")
        self.result_frame.grid(row=5, column=0, sticky="ew", pady=(0, 4))
        self.result_frame.columnconfigure(0, weight=1)
        ttk.Label(self.result_frame, text="変換結果", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.result_frame, textvariable=self.result_var, style="Body.TLabel", justify="left", wraplength=680).grid(row=1, column=0, columnspan=3, sticky="w", pady=(14, 16))
        ttk.Button(self.result_frame, text="保存先を開く", style="Secondary.TButton", command=self._open_output_folder).grid(row=2, column=0, sticky="w")
        ttk.Button(self.result_frame, text="JDL取込手順", style="Secondary.TButton", command=self._show_jdl_help).grid(row=2, column=1, sticky="e", padx=(8, 0))
        ttk.Button(self.result_frame, text="検証レポート", style="Secondary.TButton", command=self._show_report).grid(row=2, column=2, sticky="e", padx=(8, 0))
        self.result_frame.grid_remove()

    def _step_heading(self, parent, number: str, title: str):
        frame = ttk.Frame(parent, style="Card.TFrame")
        tk.Label(
            frame,
            text=number,
            width=2,
            font=(self.font_family, 9, "bold"),
            foreground="#FFFFFF",
            background=GUI_PALETTE["accent"],
            padx=2,
            pady=3,
            borderwidth=0,
        ).grid(row=0, column=0, padx=(0, 10))
        ttk.Label(frame, text=title, style="Section.TLabel").grid(row=0, column=1)
        return frame

    def _update_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_scroll_content(self, event) -> None:
        self.canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_mouse_wheel(self, event) -> None:
        if event.delta:
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _on_primary_enter(self, _event=None) -> None:
        if str(self.convert_button["state"]) != "disabled":
            self.convert_button.configure(background=GUI_PALETTE["accent_hover"])

    def _on_primary_leave(self, _event=None) -> None:
        if str(self.convert_button["state"]) != "disabled":
            self.convert_button.configure(background=GUI_PALETTE["accent"])

    def _select_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="変換する仕訳CSVを選択",
            filetypes=(("CSV/TXT", "*.csv *.txt"), ("すべてのファイル", "*.*")),
        )
        if filename:
            self._render(self.controller.select_file(Path(filename)))
            self._prepare_if_complete()

    def _select_output(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="JDL用CSVの保存先", defaultextension=".csv", filetypes=(("CSV", "*.csv"),)
        )
        if filename:
            self._render(self.controller.select_output_file(Path(filename)))
            self._prepare_if_complete()

    def _prepare_if_complete(self) -> None:
        state = self.controller.state
        if state.selected_file and state.selected_output_file and state.selected_profile_id and state.selected_context_file:
            self._render(self.controller.prepare_conversion())

    def _convert(self) -> None:
        summary = self.controller.state.conversion_summary
        if summary is None:
            return
        confirmed = messagebox.askyesno(
            "変換の確認",
            "JDL用CSVを作成します。\n\n"
            f"入力仕訳: {summary.simple_journal_count + summary.compound_journal_count}件\n"
            f"保存先: {summary.output_path}\n\n"
            "入力ファイルは変更せず、既存ファイルは上書きしません。",
        )
        self._render(self.controller.execute_conversion(confirmed))

    def _open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("会社設定")
        window.geometry("660x390")
        window.minsize(600, 350)
        window.configure(background=GUI_PALETTE["page"])
        window.transient(self.root)
        body = ttk.Frame(window, padding=28, style="Page.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="会社設定", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))
        settings_card = ttk.Frame(body, padding=(20, 18), style="Card.TFrame")
        settings_card.grid(row=1, column=0, columnspan=3, sticky="ew")
        settings_card.columnconfigure(1, weight=1)
        ttk.Label(settings_card, text="対応設定", style="Body.TLabel").grid(row=0, column=0, sticky="w")
        self.profile_combo = ttk.Combobox(settings_card, textvariable=self.profile_var, state="readonly")
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=10)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(settings_card, text="追加", style="Secondary.TButton", command=self._import_profile).grid(row=0, column=2)
        ttk.Label(settings_card, text="JDL設定", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(18, 0))
        ttk.Label(settings_card, textvariable=self.settings_context_var, style="Body.TLabel").grid(row=1, column=1, sticky="w", padx=10, pady=(18, 0))
        ttk.Button(settings_card, text="選択", style="Secondary.TButton", command=self._select_context).grid(row=1, column=2, pady=(18, 0))
        ttk.Label(settings_card, text="初回設定で受け取った、会社専用の確認済みファイルを選択してください。", style="Muted.TLabel", wraplength=500).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(body, textvariable=self.settings_message_var, style="Subtitle.TLabel", wraplength=560).grid(row=2, column=0, columnspan=3, sticky="w", pady=(18, 0))
        ttk.Button(body, text="閉じる", style="Secondary.TButton", command=window.destroy).grid(row=3, column=2, sticky="e", pady=(24, 0))
        self._render(self.controller.state)

    def _import_profile(self) -> None:
        filename = filedialog.askopenfilename(title="初期設定ファイルを追加", filetypes=(("JSON", "*.json"), ("すべてのファイル", "*.*")))
        if filename:
            self._render(self.controller.import_profile(Path(filename)))
            self._prepare_if_complete()

    def _on_profile_selected(self, _event=None) -> None:
        index = self.profile_combo.current()
        profile_id = self.profile_ids[index] if 0 <= index < len(self.profile_ids) else None
        self._render(self.controller.select_profile(profile_id))
        self._prepare_if_complete()

    def _select_context(self) -> None:
        filename = filedialog.askopenfilename(title="会社専用のJDL設定を選択", filetypes=(("JSON", "*.json"), ("すべてのファイル", "*.*")))
        if filename:
            self._render(self.controller.select_context_file(Path(filename)))
            self._prepare_if_complete()

    def _show_report(self) -> None:
        messagebox.showinfo("検証レポート", self.controller.state.verification_report or "検証レポートはまだありません。")

    def _show_jdl_help(self) -> None:
        messagebox.showinfo(
            "JDLへの取り込み",
            "1. JDLでCSV入力を開き、仕訳データを選択します。\n"
            "2. 必要に応じて出納帳ファイルを退避します。\n"
            "3. 対象期間と集計条件を確認してから実行します。\n\n"
            "画面や設定が異なる場合は、実行せず担当者へ確認してください。",
        )

    def _open_output_folder(self) -> None:
        result = self.controller.state.result_presentation
        if result is None or result.output_path is None:
            return
        folder = result.output_path.parent
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except OSError:
            messagebox.showinfo("保存先", str(folder))

    def _render(self, state: AppState) -> None:
        presentation = present_main_screen(state)
        self.profile_ids = [profile.profile_id for profile in state.profiles]
        if hasattr(self, "profile_combo"):
            self.profile_combo["values"] = [profile.profile_name for profile in state.profiles]
            if state.selected_profile_id in self.profile_ids:
                self.profile_combo.current(self.profile_ids.index(state.selected_profile_id))
            else:
                self.profile_combo.set("")
        self.file_var.set(state.selected_file.name if state.selected_file else "ファイルはまだ選択されていません")
        self.recognition_var.set(presentation.recognition_text if state.selected_file else "")
        self.output_var.set(str(state.selected_output_file) if state.selected_output_file else "保存先はまだ選択されていません")
        self.status_title_var.set(presentation.status_text)
        self.status_detail_var.set(presentation.guidance)
        badge_text, badge_foreground, badge_background = status_visual(presentation.status)
        self.status_badge.configure(
            text=badge_text,
            foreground=badge_foreground,
            background=badge_background,
        )
        if presentation.conversion_enabled:
            self.convert_button.configure(
                state="normal",
                background=GUI_PALETTE["accent"],
                cursor="hand2",
            )
        else:
            self.convert_button.configure(
                state="disabled",
                background="#D6DCE2",
                cursor="arrow",
            )
        self.settings_action.grid() if presentation.settings_action_visible else self.settings_action.grid_remove()
        self.settings_context_var.set("設定済み" if state.selected_context_file else "未設定")
        self.settings_message_var.set(state.user_message)
        result = state.result_presentation
        if result is not None:
            balance = "一致" if result.debit_total == result.credit_total else "不一致"
            self.result_var.set("\n".join((
                f"入力仕訳    {result.input_journal_count}件",
                f"出力仕訳    {result.output_journal_count}件",
                f"貸借合計    {balance}",
                f"エラー      {result.error_count}件",
                f"出力検証    {'成功' if result.output_validation_success else '未完了'}",
                f"保存先      {result.output_path or '生成されていません'}",
            )))
            self.result_frame.grid()
        else:
            self.result_frame.grid_remove()

def main() -> None:
    if tk is None:
        raise RuntimeError("tkinter is required to run the desktop GUI.")
    enable_windows_dpi_awareness()
    root = tk.Tk()
    AccountingConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
