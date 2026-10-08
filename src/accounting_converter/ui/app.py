from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ModuleNotFoundError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import AppState, UserFacingStatus, present_main_screen


class AccountingConverterApp:
    def __init__(self, root: object) -> None:
        if tk is None or ttk is None or filedialog is None or messagebox is None:
            raise RuntimeError("tkinter is required to run the desktop GUI.")
        self.root = root
        self.controller = AccountingConverterController()
        self.profile_ids: list[str] = []
        self.settings_window = None
        self.root.title("会計データ変換")
        self.root.geometry("760x680")
        self.root.minsize(680, 600)

        self.file_var = tk.StringVar(value="ファイルはまだ選択されていません")
        self.recognition_var = tk.StringVar()
        self.output_var = tk.StringVar(value="保存先はまだ選択されていません")
        self.status_title_var = tk.StringVar(value="CSVを選択してください")
        self.status_detail_var = tk.StringVar(value="変換する仕訳CSVを選択してください。")
        self.result_var = tk.StringVar()
        self.profile_var = tk.StringVar()
        self.settings_context_var = tk.StringVar(value="未設定")
        self.settings_message_var = tk.StringVar()
        self._configure_styles()
        self._build()
        self._render(self.controller.load_profiles())

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("", 20, "bold"))
        style.configure("Section.TLabel", font=("", 12, "bold"))
        style.configure("Status.TLabel", font=("", 15, "bold"))
        style.configure("Primary.TButton", font=("", 12, "bold"), padding=(24, 12))
        style.configure("Ready.TLabel", foreground="#287a3d", font=("", 15, "bold"))
        style.configure("Confirm.TLabel", foreground="#946200", font=("", 15, "bold"))
        style.configure("Blocked.TLabel", foreground="#a32929", font=("", 15, "bold"))
        style.configure("Success.TLabel", foreground="#287a3d", font=("", 15, "bold"))

    def _build(self) -> None:
        container = ttk.Frame(self.root)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        main = ttk.Frame(self.canvas, padding=28)
        self._canvas_window = self.canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_scroll_content)
        self.root.bind_all("<MouseWheel>", self._on_mouse_wheel)
        main.columnconfigure(0, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="会計データ変換", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="設定", command=self._open_settings).grid(row=0, column=1, sticky="e")
        ttk.Label(main, text="仕訳データをJDL用CSVへ安全に変換します").grid(
            row=1, column=0, sticky="w", pady=(4, 28)
        )

        input_section = ttk.Frame(main)
        input_section.grid(row=2, column=0, sticky="ew")
        input_section.columnconfigure(0, weight=1)
        ttk.Label(input_section, text="1  変換するCSV", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(input_section, text="ファイルを選択", command=self._select_file).grid(row=0, column=1, sticky="e")
        ttk.Label(input_section, textvariable=self.file_var, wraplength=560).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Label(input_section, textvariable=self.recognition_var, wraplength=650).grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Separator(main).grid(row=3, column=0, sticky="ew", pady=22)
        output_section = ttk.Frame(main)
        output_section.grid(row=4, column=0, sticky="ew")
        output_section.columnconfigure(0, weight=1)
        ttk.Label(output_section, text="2  保存先", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(output_section, text="変更", command=self._select_output).grid(row=0, column=1, sticky="e")
        ttk.Label(output_section, textvariable=self.output_var, wraplength=650).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        ttk.Separator(main).grid(row=5, column=0, sticky="ew", pady=22)
        self.status_frame = ttk.Frame(main, padding=(16, 12))
        self.status_frame.grid(row=6, column=0, sticky="ew")
        self.status_frame.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(self.status_frame, textvariable=self.status_title_var, style="Status.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(self.status_frame, textvariable=self.status_detail_var, wraplength=620, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.settings_action = ttk.Button(self.status_frame, text="設定を確認する", command=self._open_settings)
        self.settings_action.grid(row=2, column=0, sticky="w", pady=(10, 0))

        self.convert_button = ttk.Button(main, text="変換する", style="Primary.TButton", state="disabled", command=self._convert)
        self.convert_button.grid(row=7, column=0, pady=(24, 8))

        self.result_frame = ttk.Frame(main, padding=(16, 12))
        self.result_frame.grid(row=8, column=0, sticky="ew", pady=(14, 0))
        self.result_frame.columnconfigure(0, weight=1)
        ttk.Label(self.result_frame, text="変換結果", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.result_frame, textvariable=self.result_var, justify="left", wraplength=620).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 10))
        ttk.Button(self.result_frame, text="保存先を開く", command=self._open_output_folder).grid(row=2, column=0, sticky="w")
        ttk.Button(self.result_frame, text="JDL取込手順を見る", command=self._show_jdl_help).grid(row=2, column=1, sticky="e")
        ttk.Button(self.result_frame, text="検証レポート", command=self._show_report).grid(row=3, column=1, sticky="e", pady=(8, 0))
        self.result_frame.grid_remove()

    def _update_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_scroll_content(self, event) -> None:
        self.canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_mouse_wheel(self, event) -> None:
        if event.delta:
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

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
        window.geometry("620x360")
        window.transient(self.root)
        body = ttk.Frame(window, padding=22)
        body.grid(row=0, column=0, sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="会社設定", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))
        ttk.Label(body, text="対応設定").grid(row=1, column=0, sticky="w")
        self.profile_combo = ttk.Combobox(body, textvariable=self.profile_var, state="readonly")
        self.profile_combo.grid(row=1, column=1, sticky="ew", padx=10)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(body, text="追加", command=self._import_profile).grid(row=1, column=2)
        ttk.Label(body, text="JDL設定").grid(row=2, column=0, sticky="w", pady=(18, 0))
        ttk.Label(body, textvariable=self.settings_context_var).grid(row=2, column=1, sticky="w", padx=10, pady=(18, 0))
        ttk.Button(body, text="選択", command=self._select_context).grid(row=2, column=2, pady=(18, 0))
        ttk.Label(body, text="初回設定で受け取った、会社専用の確認済みファイルを選択してください。", wraplength=500).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(body, textvariable=self.settings_message_var, wraplength=540).grid(row=4, column=0, columnspan=3, sticky="w", pady=(20, 0))
        ttk.Button(body, text="閉じる", command=window.destroy).grid(row=5, column=2, sticky="e", pady=(28, 0))
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
        self.status_title_var.set(self._status_prefix(presentation.status) + presentation.status_text)
        self.status_detail_var.set(presentation.guidance)
        self.status_label.configure(style=self._status_style(presentation.status))
        self.convert_button.configure(state="normal" if presentation.conversion_enabled else "disabled")
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

    @staticmethod
    def _status_prefix(status: UserFacingStatus) -> str:
        return {UserFacingStatus.READY: "OK  ", UserFacingStatus.CONFIRM: "!  ", UserFacingStatus.BLOCKED: "X  ", UserFacingStatus.SUCCESS: "OK  ", UserFacingStatus.NEEDS_INPUT: ""}[status]

    @staticmethod
    def _status_style(status: UserFacingStatus) -> str:
        return {UserFacingStatus.READY: "Ready.TLabel", UserFacingStatus.CONFIRM: "Confirm.TLabel", UserFacingStatus.BLOCKED: "Blocked.TLabel", UserFacingStatus.SUCCESS: "Success.TLabel", UserFacingStatus.NEEDS_INPUT: "Status.TLabel"}[status]


def main() -> None:
    if tk is None:
        raise RuntimeError("tkinter is required to run the desktop GUI.")
    root = tk.Tk()
    AccountingConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
