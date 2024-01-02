import re
import json
from logging import getLogger
from pydantic import BaseModel
from datetime import datetime

# ロガー設定
logger = getLogger(__name__)


class Node(BaseModel):
    label: str
    name: str
    properties: dict | None

    def __hash__(self):
        """long_memoryの重複排除に使用する。各属性を用いてハッシュ値を計算。"""
        return hash((self.label, self.name))

    def __eq__(self, other):
        """entityとmatchするために使用する。"""
        if not isinstance(other, Node):
            return False
        return (self.label, self.name) == (other.label, other.name)

    @classmethod
    def create(cls, label: str, name: str, properties: dict):
        """LLMで生成されたノードを Node オブジェクトに変換する"""
        label = label.replace(" ", "_")  # Neo4j don't allow space in label
        name = remove_suffix(name)
        return cls(label=label, name=name, properties=properties)

    def to_cypher(self) -> str:
        """Cypherクエリを生成する"""
        props = ""
        if self.properties:
            props = ', '.join([f"{key}: '{value}'" for key, value in self.properties.items()])
            props = f"{{ {props} }}" if props else ""
        return f"({self.name}:{self.label} {props})"


class Relationships(BaseModel):
    type: str
    start_node: str
    end_node: str
    properties: dict | None
    start_node_label: str | None
    end_node_label: str | None

    def __hash__(self):
        """long_memoryの重複排除に使用する。各属性を用いてハッシュ値を計算。"""
        return hash((self.type, self.start_node, self.end_node, self.start_node_label, self.end_node_label))

    def __eq__(self, other):
        """他の Relationships オブジェクトと比較（entityとmatchするために使う）"""
        if not isinstance(other, Relationships):
            return False
        return (
            self.type == other.type and
            self.start_node == other.start_node and
            self.end_node == other.end_node
        )

    @classmethod
    def create(cls, type: str, start_node: str, end_node: str, properties: dict, start_node_label: str | None, end_node_label: str | None):
        """LLMで生成された関係を Relationships オブジェクトに変換する"""
        type = type.replace(" ", "_")  # Neo4j don't allow space in type
        start_node = remove_suffix(start_node)
        end_node = remove_suffix(end_node)
        if not type or not start_node or not end_node:
            return None
        return cls(type=type, start_node=start_node, end_node=end_node, properties=properties,
                   start_node_label=start_node_label, end_node_label=end_node_label)

    def to_cypher(self) -> str:
        """Cypherクエリを生成する"""
        start_label = f":{self.start_node_label}" if self.start_node_label else ""
        end_label = f":{self.end_node_label}" if self.end_node_label else ""
        props = ""
        if self.properties:
            props = ', '.join([f"{key}: '{value}'" for key, value in self.properties.items()])
            props = f"{{{props}}}"
        return f"({self.start_node}{start_label})-[r:{self.type} {props}]->({self.end_node}{end_label})"


FIRST_PERSON_PRONOUNS = ["私", "i", "user", "me"]
SECOND_PERSON_PRONOUNS = ["you"]


class Triplets(BaseModel):
    nodes: list[Node] = []
    relationships: list[Relationships] = []

    @classmethod
    def create(cls, triplets_data, user_name: str, ai_name: str):
        """LLMで生成されたTripletsをTripletsオブジェクトに変換する"""
        # [OPTIMIZE] user_name, ai_nameの置換は、プロンプトの向上で不要となった可能性あり。出力が安定するようなら省く。
        nodes = []
        if 'Nodes' in triplets_data:
            for node in triplets_data['Nodes']:
                # label と name のキーが存在することを確認
                if 'label' in node and ('name' in node or ('properties' in node and 'name' in node.get('properties'))):
                    name = node.get('name') if node.get('name') else node.get('properties').get('name')
                    # nameが"I","Me"或いは"User"、または"You"の場合、それぞれを"user_name"と"ai_name"に変換
                    if name.lower() in FIRST_PERSON_PRONOUNS:
                        name = user_name
                    elif name.lower() in SECOND_PERSON_PRONOUNS:
                        name = ai_name
                    nodes.append(Node.create(label=node.get('label'), name=name, properties=node.get('properties')))
            nodes = [node for node in nodes if node is not None]    # Noneを除外

        relationships = []
        if 'Relationships' in triplets_data:
            for relationship in triplets_data['Relationships']:
                if 'type' in relationship and 'start_node' in relationship and 'end_node' in relationship:
                    start_node = relationship.get('start_node')
                    end_node = relationship.get('end_node')
                    if start_node.lower() in FIRST_PERSON_PRONOUNS:
                        start_node = user_name
                    elif start_node.lower() in SECOND_PERSON_PRONOUNS:
                        start_node = ai_name
                    if end_node.lower() in FIRST_PERSON_PRONOUNS:
                        end_node = user_name
                    elif end_node.lower() in SECOND_PERSON_PRONOUNS:
                        end_node = ai_name
                    start_node_label = next((node.label for node in nodes if node.name == start_node), None)
                    end_node_label = next((node.label for node in nodes if node.name == end_node), None)
                    relationships.append(
                        Relationships.create(
                            type=relationship.get('type'),
                            start_node=start_node,
                            end_node=end_node,
                            properties=relationship.get('properties'),
                            start_node_label=start_node_label,
                            end_node_label=end_node_label
                        )
                    )
            relationships = [relationship for relationship in relationships if relationship is not None]

        return cls(nodes=nodes, relationships=relationships)

    def to_cypher_json(self) -> str:
        """Cypherクエリを生成する"""
        cypher_nodes = [node.to_cypher() for node in self.nodes]
        cypher_relationships = [rel.to_cypher() for rel in self.relationships]

        if not cypher_nodes and not cypher_relationships:
            return ""

        cypher_data = {
            key: value
            for key, value in {
                "nodes": cypher_nodes,
                "relationships": cypher_relationships
            }.items()
            if value
        }
        return json.dumps(cypher_data, ensure_ascii=False)


# Use in Triplet
def remove_suffix(name: str) -> str:
    """正規表現パターンで、接尾語を列挙し、それらを末尾から削除する"""
    jk_suffixes = [
        "りん", "ぴ", "っぴ", "ゆん", "ぽん", "むー", "みー",
        "先生", "せんせえ", "せんせい", "先輩", "せんぱい", "後輩",
    ]
    otaku_suffixes = [
        "たん", "たそ", "ほん", "しぃ", "ちゃま", "りり", "氏", "師匠", "師", "老師",
        "殿", "どの", "姫", "ひめ", "殿下", "陛下", "閣下", "太郎", "たろー", "きち",
    ]  # prefix "同志",
    role_suffixes = [
        "組長", "会長", "社長", "副社長", "部長", "課長", "係長", "監督", "選手",
        "", "博士", "教授", "マネージャー", "スタッフ", "メンバー", "オーナー", "リーダー",
        "ディレクター", "オフィサー", "一等兵", "上等兵", "伍長", "軍曹", "曹長", "少尉", "中尉",
        "大尉", "少佐", "中佐", "大佐", "准将", "少将", "中将", "大将", "元帥", "大元帥", "将軍"
        "海兵", "上級海兵", "提督", "指令官", "司令官", "大統領", "総統", "皇帝", "王", "女王",
    ]
    family_prefixes = ["姉", "兄", "じ", "ば", "じい", "ばあ", "母", "父"]
    suffixes = ["さん", "ちゃん", "さま", "様", "殿", "どの", "氏", "上"]
    family_suffixes = [f + s for f in family_prefixes for s in suffixes]
    family_suffixes_o = ["お" + fs for fs in family_suffixes]

    all_suffixes = (
        [
            "さん", "くん", "君", "ちゃん", "さま", "様",
        ]
        + jk_suffixes
        + otaku_suffixes
        + role_suffixes
        + family_suffixes
        + family_suffixes_o
    )
    pattern = r"(" + "|".join(all_suffixes) + ")$"
    return re.sub(pattern, "", name)


# WebScoketで受け取るデータのモデル
class WebSocketInputData(BaseModel):
    user: str
    AI: str
    source: str     # user_id or assistant_id(asst_) # user_id作成時にasst_の使用を禁止する
    input_text: str
    title: str
    former_node_id: int | None = None   # node_idを渡すことで、途中のメッセージに新しいメッセージを追加することができる。使用する場合、フロントで枝分かれの表示方法の実装が必要。
    with_voice: bool = True


class TempMemory(BaseModel):
    user_input: str
    ai_response: str
    triplets: Triplets | None = None         # 長期記憶(from neo4j)
    time: datetime | None = None             # メッセージの時刻 (古いメッセージの時刻を示すために使用)


class ShortMemory(BaseModel):
    short_memory: list[TempMemory] = []
    limit: int = 7
    nodes_set: set[Node] = set()
    relationships_set: set[Relationships] = set()
    triplets: Triplets | None = None

    def convert_to_tripltets(self):
        # セットに変換（重複を削除）
        for temp_memory in self.short_memory:
            if temp_memory.triplets:
                self.nodes_set.update(temp_memory.triplets.nodes)
                self.relationships_set.update(temp_memory.triplets.relationships)
        # Tripletsに変換
        self.triplets = Triplets(nodes=list(self.nodes_set), relationships=list(self.relationships_set))

    def memory_turn_over(self, user_input: str, ai_response: str, retrieved_memory: Triplets | None = None):
        temp_memory = TempMemory(
            user_input=user_input,
            ai_response=ai_response,
            triplets=retrieved_memory,
        )
        logger.info(f"short_memory: {self.short_memory}")
        # short_memoryに追加
        self.short_memory.append(temp_memory)

        # short_memoryがlimit(default = 7)個を超えたら、古いものから削除
        while len(self.short_memory) > self.limit:
            self.short_memory.pop(0)

        # セットに変換（重複を削除）し、Tripletsに変換
        self.convert_to_tripltets()
