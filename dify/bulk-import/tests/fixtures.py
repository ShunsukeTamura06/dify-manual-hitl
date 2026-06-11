"""複数種類のサンプル文書ビルダー（汎用性の制約の検証用）。

docs/splitter-design.md「汎用性の制約」に従い、特定文書（金融検査マニュアル別冊）の
構造に過学習していないことを、性質の異なる文書で確認するためのフィクスチャ。
手順書 / 規程 / FAQ / 表主体 / 箇条書き主体 を生成する。

いずれも「見出しの語」や「番号付けの形式」は文書ごとにわざと変え、
スプリッターがそれらに依存していないことをテストで担保する。
"""


def procedure_doc(sections: int = 40) -> str:
    """手順書（ステップ列挙型）。見出し記法は「■ 手順N」。"""
    blocks = ["# 業務システム操作手順書\n\nこの文書はシステムの操作手順をまとめたものです。"]
    for n in range(1, sections + 1):
        blocks.append(
            f"■ 手順{n}: 画面Aから登録する\n"
            f"まず画面Aを開きます。次に項目を入力し、保存ボタンを押します。"
            f"確認ダイアログが出るので内容を確認してから確定します。"
            f"（手順{n}の補足: 入力規則は別紙を参照のこと）" * 3
        )
    return "\n\n".join(blocks)


def regulation_doc(articles: int = 50) -> str:
    """規程（条文型）。見出し記法は「第N条」。"""
    blocks = ["就業規則\n\n本規則は従業員の労働条件を定めるものである。"]
    for n in range(1, articles + 1):
        blocks.append(
            f"第{n}条（勤務時間）\n"
            f"従業員の所定労働時間は1日8時間とする。"
            f"始業および終業の時刻は別に定める。"
            f"前項の規定にかかわらず、業務の都合により変更することがある。" * 2
        )
    return "\n\n".join(blocks)


def faq_doc(items: int = 60) -> str:
    """FAQ（Q&A 型）。見出し記法は「Q.」「A.」。"""
    blocks = ["# よくある質問\n\n本ページは利用者からの問い合わせをまとめたものです。"]
    for n in range(1, items + 1):
        blocks.append(
            f"Q. 機能{n}はどう使いますか？\n"
            f"A. 設定画面から機能{n}を有効化してください。"
            f"有効化後に再読み込みすると反映されます。詳細はマニュアルを参照。"
        )
    return "\n\n".join(blocks)


def table_heavy_doc(rows: int = 200) -> str:
    """表主体（Markdown テーブル）。長い行を含む。"""
    header = "# 料金表\n\n各プランの料金を以下に示す。"
    table_head = "| 項目 | 内容 | 金額 | 備考 |\n| --- | --- | --- | --- |"
    lines = [
        f"| 項目{n} | サービス内容の説明がここに入る | {n * 100}円 | 月額・税抜の価格設定 |"
        for n in range(1, rows + 1)
    ]
    # 表は 1 つの大きな段落（空行なし）になる → ハードスプリット経路を踏む。
    return f"{header}\n\n{table_head}\n" + "\n".join(lines)


def bullet_doc(bullets: int = 150) -> str:
    """箇条書き主体。空行が少なく塊になりやすい。"""
    head = "# チェックリスト\n\n出荷前に以下を確認する。"
    items = [
        f"- 確認項目{n}: 該当箇所を目視で点検し、異常がないことを記録する。"
        for n in range(1, bullets + 1)
    ]
    return f"{head}\n\n" + "\n".join(items)


def single_giant_paragraph(chars: int = 30000) -> str:
    """改行のない巨大な 1 段落（最悪ケース）。"""
    return "あ" * chars


ALL_DOC_BUILDERS = {
    "procedure": procedure_doc,
    "regulation": regulation_doc,
    "faq": faq_doc,
    "table_heavy": table_heavy_doc,
    "bullet": bullet_doc,
}
