from diskcache import Cache
from chat_wb.neo4j.neo4j import (
    get_node_names,
    get_node_labels,
    get_relationship_types,
    get_label_and_relationship_type_sets,
)


# diskcacheのインスタンスを作成
cache = Cache(directory="./cache")  # キャッシュファイルを保存するディレクトリを指定


def fetch_labels() -> list[str]:
    # キャッシュからラベルを取得
    labels = cache.get("labels")

    if labels is None:
        labels = get_node_labels()
        cache.set("labels", labels, expire=86400)  # 1日後に期限切れとなるようにTTLを設定

    return labels


def fetch_node_names(label: str) -> list[str]:
    # キャッシュからノード名を取得
    node_names = cache.get(f"node_names_{label}")

    if node_names is None:
        node_names = get_node_names(label)
        cache.set(
            f"node_names_{label}", node_names, expire=86400
        )  # 1日後に期限切れとなるようにTTLを設定

    return node_names


def fetch_relationships() -> list[str]:
    # キャッシュからリレーションシップタイプを取得
    relationship_types = cache.get("relationships_types")

    if relationship_types is None:
        relationship_types = get_relationship_types()
        cache.set("relationships_types", relationship_types, expire=86400)

    return relationship_types


def fetch_label_and_relationship_type_sets() -> dict:
    # キャッシュからラベルとリレーションシップタイプのセットを取得
    label_and_relationship_type_sets = cache.get("label_and_relationship_type_sets")

    if label_and_relationship_type_sets is None:
        label_and_relationship_type_sets = get_label_and_relationship_type_sets()
        # キャッシュに保存するために、キーを文字列に変換
        str_key_dict = {str(key): value for key, value in label_and_relationship_type_sets.items()}
        cache.set(
            "label_and_relationship_type_sets",
            str_key_dict,
            expire=86400,
        )

    return label_and_relationship_type_sets


# global変数の設定（1日に1回（キャッシュのTTLが過ぎるたびに）読み込む（# 初回のデータ取得））
# ラベルリスト
NODE_LABELS = fetch_labels()
RELATION_TYPES = fetch_relationships()
RELATION_SETS = fetch_label_and_relationship_type_sets()


# # ノード名リスト　データベースを作るなら、要る。
# global_vars = globals()
# for _label in NODE_LABELS:
#     global_vars[_label.upper()] = fetch_node_names(_label)
#     # PLANETSで呼び出せる。例 print(PLANETS)

# 　ノードに対して、特定のリレーションタイプを持つノードの名前をリストとして取得したい場合、
#  以下の関数から、nameだけ取り出す。
#  get_related_nodes_by_relation(label:str, name:str, relation_type:str) -> list[Node]: