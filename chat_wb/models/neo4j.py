import re
from logging import getLogger
from pydantic import BaseModel, validator

# ロガー設定
logger = getLogger(__name__)


class Node(BaseModel):
    label: str
    name: str
    properties: dict | None

    def __hash__(self):
        # 各属性を用いてハッシュ値を計算
        return hash((self.label, self.name))

    def __eq__(self, other):
        # 他の Node オブジェクトと比較
        if not isinstance(other, Node):
            return False
        return (self.label, self.name) == (other.label, other.name)

    @classmethod
    def create(cls, label: str, name: str, properties: dict):
        name = remove_suffix(name)
        return cls(label=label, name=name, properties=properties)


class Relationships(BaseModel):
    type: str
    start_node: str
    end_node: str
    properties: dict | None
    start_node_label: str | None
    end_node_label: str | None

    def __hash__(self):
        # 各属性を用いてハッシュ値を計算（long_memoryをSet重複排除するために使う）
        return hash((self.type, self.start_node, self.end_node, self.start_node_label, self.end_node_label))

    def __eq__(self, other):
        # 他の Relationships オブジェクトと比較（entityとmatchするために使う）
        if not isinstance(other, Relationships):
            return False
        return (
            self.type == other.type and
            self.start_node == other.start_node and
            self.end_node == other.end_node
        )

    @classmethod
    def create(cls, type: str, start_node: str, end_node: str, properties: dict, start_node_label: str | None, end_node_label: str | None):
        start_node = remove_suffix(start_node)
        end_node = remove_suffix(end_node)
        return cls(type=type, start_node=start_node, end_node=end_node, properties=properties, start_node_label=start_node_label, end_node_label=end_node_label)


class Triplets(BaseModel):
    nodes: list[Node] = []
    relationships: list[Relationships] = []

    @classmethod
    def create(cls, triplets_data):
        nodes = [
            Node.create(label=node.get('label'), name=node.get('name'), properties=node.get('properties'))
            for node in triplets_data['Nodes']
            if 'label' in node and 'name' in node  # label と name のキーが存在することを確認
        ]

        relationships = []
        if 'Relationships' in triplets_data:
            relationships = [
                Relationships.create(
                    type=relationship['type'],
                    start_node=relationship['start_node'],
                    end_node=relationship['end_node'],
                    properties=relationship['properties'],
                    start_node_label=next((node.label for node in nodes if node.name == relationship['start_node']), None),
                    end_node_label=next((node.label for node in nodes if node.name == relationship['end_node']), None)
                )
                for relationship in triplets_data['Relationships']
                if 'type' in relationship and 'start_node' in relationship and 'end_node' in relationship  # 必要なキーが存在することを確認
            ]

        return cls(nodes=nodes, relationships=relationships)


# Use in Triplet
def remove_suffix(name: str) -> str:
    # 正規表現パターンで、接尾語を列挙し、それらを末尾から削除する
    jk_suffixes = [
        "りん",
        "ぴ",
        "っぴ",
        "ゆん",
        "ぽん",
        "むー",
        "みー",
        "先生",
        "せんせえ",
        "せんせい",
        "先輩",
        "せんぱい",
        "後輩",
    ]
    otaku_suffixes = [
        "たん",
        "たそ",
        "ほん",
        "しぃ",
        "ちゃま",
        "りり",
        "氏",
        "師匠",
        "師",
        "老師",
        "殿",
        "どの",
        "姫",
        "ひめ",
        "殿下",
        "陛下",
        "閣下",
        "太郎",
        "たろー",
        "きち",
    ]  # prefix "同志",
    role_suffixes = [
        "組長",
        "会長",
        "社長",
        "副社長",
        "部長",
        "課長",
        "係長",
        "監督",
        "選手",
        "将軍",
        "博士",
        "教授",
        "マネージャー",
        "スタッフ",
        "メンバー",
        "オーナー",
        "リーダー",
        "ディレクター",
        "オフィサー",
        "一等兵",
        "上等兵",
        "伍長",
        "軍曹",
        "曹長",
        "少尉",
        "中尉",
        "大尉",
        "少佐",
        "中佐",
        "大佐",
        "准将",
        "少将",
        "中将",
        "大将",
        "元帥",
        "大元帥",
        "海兵",
        "上級海兵",
        "提督",
    ]
    all_suffixes = (
        [
            "さん",
            "くん",
            "君",
            "ちゃん",
            "さま",
            "様",
        ]
        + jk_suffixes
        + otaku_suffixes
        + role_suffixes
    )
    pattern = r"(" + "|".join(all_suffixes) + ")$"
    return re.sub(pattern, "", name)
