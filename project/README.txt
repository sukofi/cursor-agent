このフォルダ (project) は Discord Bot が作成するプログラムの保存先です。
Bot はここに .py ファイルを保存し、run_script でこのフォルダ内のスクリプトを実行します。

保存場所: cursor-agent-main/project/
絶対パス: agent_bot.py と同じディレクトリの project フォルダ

--- フォルダ構成 ---
project/
  ├── README.txt          … この説明
  ├── knowledge/          … ナレッジ・スキル用
  │     ├── agent_profile.md  … 自分（Bot）に関する情報の専用ファイル
  │     ├── 自律開始_トリガープロンプト.md  … 自律開発モード用プロンプト
  │     └── （その他スキル .md）
  └── tools/              … カスタムツール用 .py
