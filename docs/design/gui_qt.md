# PySide6 Desktop GUI

## Migration Rationale

Windowsでの日本語font描画、高DPI、widget/style品質を改善するため、PySide6 / Qt 6のpresentation layerを追加する。変換backend、Controller、ViewModel、READY/BLOCK判定は既存実装を再利用し、Qt widgetへ会計ロジックを追加しない。

旧Tkinter GUIはWindows smoke test完了まで`accounting_converter.ui.app`にfallbackとして維持する。

## Architecture

```text
accounting_converter.ui.controllers / view_models
                    ^
                    |
accounting_converter.ui_qt
  app.py          QApplication entry point
  main_window.py  user actions and state rendering
  widgets.py      CSV drop zone
  drop_policy.py  framework-independent drop validation
  theme.py        QSS and presentation colors
```

Qt側はファイル選択、drop、dialog、backend呼出し、presentation state反映だけを担当する。

## UX

- CSVをdropまたは選択する。
- 既存Adapterで認識した形式、logical journal数、期間を表示する。
- 保存先を指定する。
- READYの場合だけ`JDL用に変換する`を有効にする。
- 設定不足、BLOCK、成功はbadgeと説明文で示す。
- Profile ID、Context ID、Registry、Evidence、internal enumは通常画面へ出さない。

## Drag And Drop

Qt標準のdrag/drop eventだけを利用する。local `.csv` exactly 1 fileのみ受け付け、複数file、directory、CSV以外、存在しないpathを明示的に拒否する。drop後はfile dialogと同じController flowを通し、自動変換やsource変更を行わない。

## High DPI And Typography

Qt 6のHigh DPIを利用し、scale factor rounding policyは`PassThrough`とする。absolute positioningを使わずlayout managerとscroll areaで100%/125%/150% scalingに対応する。fontは`Yu Gothic UI`、`Meiryo UI`、`Segoe UI`、Qt既定fontの順で選択する。

## Dependency And Local-Only Policy

runtime dependencyとして`PySide6>=6.8,<7`を追加する。network、telemetry、auto update、remote codeは追加しない。Qt runtime/DLL/pluginを同梱するため、Tkinter版よりdistribution sizeが大きくなる。

## Windows Packaging

`scripts/build_windows.ps1`の既定entry pointはQt GUIであり、PyInstallerの`--collect-all PySide6`でQt platform plugins、styles、DLLを収集する。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

旧Tkinter fallback build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -TkFallback
```

どちらもone-folder `dist\AccountingConverter\AccountingConverter.exe`を生成する。Qt版はWindows実機で起動、DPI、drop、選択、変換、設定、結果、platform plugin loadingを確認するまで正式配布しない。
