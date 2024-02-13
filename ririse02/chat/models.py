import json
import re
from datetime import datetime
from logging import getLogger
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator

# ロガー設定
logger = getLogger(__name__)


class Neo4jIndex(BaseModel):
    """Neo4j Show Index Response Schema"""

    name: str
    type: str
    labelsOrTypes: list[str] | None
    properties: list[str] | None
    options: dict | None


class Node(BaseModel):
    """primary key: label, name"""

    label: str
    name: str
    properties: dict[str, list[str]]

    @field_validator("name")
    def validate_name(cls, v):
        if v == "":
            raise ValueError("name is empty")
        return v

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
        """Convert LLM generated nodes to 'Node' object"""
        label = label.replace(" ", "_")  # Neo4j don't allow space in label
        name = remove_suffix(name)

        # convert LLM generated properties to dict[str|list[str]]
        for key, value in properties.items():
            if not isinstance(value, list):
                properties[key] = [str(value)]
            else:
                properties[key] = [str(v) for v in value]
        return cls(label=label, name=name, properties=properties)

    def to_cypher(self) -> str:
        """Cypherクエリを生成する"""
        props = ""
        if self.properties:
            # propertiesをstr | list[str]形式の文字列に変換
            props_list = []
            for key, value in self.properties.items():
                if isinstance(value, list):
                    if len(value) == 1:
                        value_str = str(value[0])
                    else:
                        value_str = "[" + ", ".join(map(str, value)) + "]"
                else:
                    value_str = str(value)
                props_list.append(f"{key}: {value_str}")
            props = ", ".join(props_list)
            props = f"{{ {props} }}" if props else ""
        return f"({self.name}: {self.label} {props})"


class Relationship(BaseModel):
    """primary key: type, start_node, end_node, start_node_label, end_node_label"""

    type: str
    start_node: str
    end_node: str
    properties: dict[str, list[str]]
    start_node_label: str | None
    end_node_label: str | None

    @field_validator("start_node", "end_node")
    def validate_name(cls, v):
        if v == "":
            raise ValueError("node name is empty")
        return v

    def __hash__(self):
        """long_memoryの重複排除に使用する。各属性を用いてハッシュ値を計算。"""
        return hash((self.type, self.start_node, self.end_node, self.start_node_label, self.end_node_label))

    def __eq__(self, other):
        """他の Relationship オブジェクトと比較（entityとmatchするために使う）"""
        if not isinstance(other, Relationship):
            return False
        return self.type == other.type and self.start_node == other.start_node and self.end_node == other.end_node

    @classmethod
    def create(
        cls,
        type: str,
        start_node: str,
        end_node: str,
        properties: dict,
        start_node_label: str | None,
        end_node_label: str | None,
    ):
        """Convert LLM generated relationships to 'Relationship' object"""
        type = type.replace(" ", "_")  # Neo4j don't allow space in type
        start_node = remove_suffix(start_node)
        end_node = remove_suffix(end_node)
        if not type or not start_node or not end_node:
            return None
        # convert LLM generated properties to dict[str|list[str]]
        for key, value in properties.items():
            if not isinstance(value, list):
                properties[key] = [str(value)]
            else:
                properties[key] = [str(v) for v in value]
        return cls(
            type=type,
            start_node=start_node,
            end_node=end_node,
            properties=properties,
            start_node_label=start_node_label,
            end_node_label=end_node_label,
        )

    # [TODO] 双方向クエリへの対応を検討
    def to_cypher(self) -> str:
        """Cypherクエリを生成する"""
        start_label = f":{self.start_node_label}" if self.start_node_label else ""
        end_label = f":{self.end_node_label}" if self.end_node_label else ""
        props = ""
        if self.properties:
            props = ", ".join([f"{key}: '{value}'" for key, value in self.properties.items()])
            props = f"{{{props}}}"
        return f"({self.start_node}{start_label})-[{self.type}{props}]->({self.end_node}{end_label})"


FIRST_PERSON_PRONOUNS = ["私", "i", "user", "me"]
SECOND_PERSON_PRONOUNS = ["you"]


class Triplets(BaseModel):
    nodes: list[Node] = []
    relationships: list[Relationship] = []

    @classmethod
    def create(cls, triplets_data, user_name: str, ai_name: str):
        """LLMで生成されたTripletsをTripletsオブジェクトに変換する。
        各propertiesのキーをlowercaseに、各typeをuppercaseにする。"""
        # [OPTIMIZE] user_name, ai_nameの置換は、プロンプトの向上で不要となった可能性あり。出力が安定するようなら省く。
        nodes = []
        if "Nodes" in triplets_data:
            for node in triplets_data["Nodes"]:
                # label と name のキーが存在することを確認
                if "label" in node and ("name" in node or ("properties" in node and "name" in node.get("properties"))):
                    name = node.get("name") if node.get("name") else node.get("properties").get("name")
                    # nameが"I","Me"或いは"User"、または"You"の場合、それぞれを"user_name"と"ai_name"に変換
                    if name.lower() in FIRST_PERSON_PRONOUNS:
                        name = user_name
                    elif name.lower() in SECOND_PERSON_PRONOUNS:
                        name = ai_name
                    # Nodeモデルに変換
                    properties = {
                        k.lower(): v for k, v in node.get("properties", {}).items()
                    }  # propertiesのキーを小文字に変換
                    try:
                        nodes.append(Node.create(label=node.get("label"), name=name, properties=properties))
                    except ValidationError as e:
                        logger.error(f"Validation error for node {node}: {e}")
            nodes = [node for node in nodes if node is not None]  # Noneを除外

        relationships = []
        if "Relationships" in triplets_data:
            for relationship in triplets_data["Relationships"]:
                if "type" in relationship and "start_node" in relationship and "end_node" in relationship:
                    # nameが"I","Me"或いは"User"、または"You"の場合、それぞれを"user_name"と"ai_name"に変換
                    start_node = relationship.get("start_node")
                    end_node = relationship.get("end_node")
                    if start_node.lower() in FIRST_PERSON_PRONOUNS:
                        start_node = user_name
                    elif start_node.lower() in SECOND_PERSON_PRONOUNS:
                        start_node = ai_name
                    if end_node.lower() in FIRST_PERSON_PRONOUNS:
                        end_node = user_name
                    elif end_node.lower() in SECOND_PERSON_PRONOUNS:
                        end_node = ai_name
                    # Relationshipモデルに変換
                    start_node_label = next((node.label for node in nodes if node.name == start_node), None)
                    end_node_label = next((node.label for node in nodes if node.name == end_node), None)
                    type = relationship.get("type").upper()  # typeを大文字に変換
                    properties = {
                        k.lower(): v for k, v in relationship.get("properties", {}).items()
                    }  # propertiesのキーを小文字に変換
                    try:
                        relationships.append(
                            Relationship.create(
                                type=type,
                                start_node=start_node,
                                end_node=end_node,
                                properties=properties,
                                start_node_label=start_node_label,
                                end_node_label=end_node_label,
                            )
                        )
                    except ValidationError as e:
                        logger.error(f"Validation error for relationship {relationship}: {e}")
            relationships = [relationship for relationship in relationships if relationship is not None]

        return cls(nodes=nodes, relationships=relationships)

    def to_cypher_json(self) -> str:
        """Cypherクエリを生成する"""
        cypher_nodes = [node.to_cypher() for node in self.nodes]
        cypher_relationships = [rel.to_cypher() for rel in self.relationships]

        if not cypher_nodes and not cypher_relationships:
            return ""

        cypher_data = {
            key: value for key, value in {"nodes": cypher_nodes, "relationships": cypher_relationships}.items() if value
        }
        return json.dumps(cypher_data, ensure_ascii=False)


class MessageNode(BaseModel):
    """(:Message)-[:RESPOND]->(:Message)の関係を作成することで、会話の流れを追跡する。(Read)"""

    timestamp: datetime  # primary key
    speaker: str
    listner: list[str]  # scene.participants - speaker
    message: str  # embedding target


class TopicNode(BaseModel):
    """(:Topic)-[:CONTAIN]->(:Message)  (Read/Write)"""

    timestamp: datetime  # primary key
    summary: str = ""  # embedding target
    messages: list[MessageNode]


class SceneNode(BaseModel):
    """(:Scene)-[:CONTAIN]->(:Topic)    (Read/Write)"""

    timestamp: datetime  # primary key
    properties: str  # [TODO] Sceneを示す情報（背景、場所等）要素が固定できれば展開。
    summary: str = ""  # embedding target
    topics: list[TopicNode]


class DocumentNode(BaseModel):
    """(:Document-[:CONTAIN]->(:Topic)    Document Load時に作成し、終了時にTopicNodeを要約して更新する。
    会話と同様の構造で、文書の内容を保持する。
    (:Person)-[:READ]->(:Message)で、読書の内容をPersonに紐づける。"""

    timestamp: datetime  # primary key
    properties: str
    summary: str  # embedding target
    topics: list[TopicNode]


class MessageEntityHolder(BaseModel):
    """Message履歴と、それに紐づくentityを保持するクラス"""

    message: MessageNode
    entities: list[Node]


class NodeHistory(BaseModel):
    """Nodeとそれに紐づくMessageNodeを保持するクラス"""

    node: Node
    relationships: list[Relationship] = []
    messages: list[MessageNode] = []


class Character(BaseModel):
    """場に入ったら、場に管理されよう。"""

    """会話の手番が回ってきたら、topicのentityうち、limitまでの分を、characterから3ホッブズまでのノード・パスから探索。
    Person -> Message -> Entity -> Entity"""

    """取り出し時、Scene / Documentごとに、Entityをリストし、pathの多さでScene / Documentを選択する。"""

    name: str
    description: str
    action_plan: list  # [Action plan]
    character_settings: dict  # Character settings class
    short_memory_limit = 7  # default
    short_memory_input_size = 4096  # default


class Player(BaseModel):
    name: str


class SceneManager(BaseModel):

    participants: list[Character | Player]  # 現時点の参加者のリスト
    all_participants: list[str]  # 全体の参加者の名前リスト
    # current_time = datetime.now(pytz.timezone(self.time_zone)).strftime("%Y-%m-%d %H:%M:%S")
    # location = "Yokohama"
    topics: list[TopicNode]
    current_topic: TopicNode
    message_history: list[MessageEntityHolder] | None = None


class FrontData(BaseModel):
    """ChatPlaceを作成、更新するためのinput data"""

    scene: SceneNode
    topic: TopicNode
    speaker: str
    add_listner: list[str]
    remove_listner: list[str]
    message: str
    with_voice: bool = True


# Use in Triplet
# [HACK] spaCy, LLM のStemming, Lemmatizationを検討。
def remove_suffix(name: str) -> str:
    """正規表現パターンで、接尾語を列挙し、それらを末尾から削除する"""
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
        "",
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
        "将軍" "海兵",
        "上級海兵",
        "提督",
        "指令官",
        "司令官",
        "大統領",
        "総統",
        "皇帝",
        "王",
        "女王",
    ]
    family_prefixes = ["姉", "兄", "じ", "ば", "じい", "ばあ", "母", "父"]
    suffixes = ["さん", "ちゃん", "さま", "様", "殿", "どの", "氏", "上"]
    family_suffixes = [f + s for f in family_prefixes for s in suffixes]
    family_suffixes_o = ["お" + fs for fs in family_suffixes]

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
        + family_suffixes
        + family_suffixes_o
    )
    pattern = r"(" + "|".join(all_suffixes) + ")$"
    return re.sub(pattern, "", name)
