このフォルダ (project) は Discord Bot が作成するプログラム・ツールの保存先です。
作成したツール関係はすべてここ (project) に保存されます。

Bot はここに .py を保存し、run_script で実行。スキル登録は knowledge/、カスタムツールは tools/ に配置します。

保存場所: cursor-agent-main/project/
絶対パス: agent_bot.py と同じディレクトリの project フォルダ

--- フォルダ構成 ---
project/
  ├── README.txt          … この説明
  ├── knowledge/          … ナレッジ・スキル用（save_skill の保存先）
  │     ├── agent_profile.md  … 自分（Bot）に関する情報の専用ファイル
  │     ├── 自律開始_トリガープロンプト.md  … 自律開発モード用プロンプト
  │     └── （その他スキル .md）
  └── tools/              … カスタムツール用 .py（作成したツールもここに保存）
