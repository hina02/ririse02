import re
from logging import getLogger
from pydantic import BaseModel

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
        # neo4jでlabel,nameを空文字にしないため、空文字の場合はNoneを返す。
        # if not label or not name:
        #     return None
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
        start_node = remove_suffix(start_node)
        end_node = remove_suffix(end_node)
        if not type or not start_node or not end_node:
            return None
        return cls(type=type, start_node=start_node, end_node=end_node, properties=properties,
                   start_node_label=start_node_label, end_node_label=end_node_label)


FIRST_PERSON_PRONOUNS = ["私", "i", "user", "me"]
SECOND_PERSON_PRONOUNS = ["you"]


class Triplets(BaseModel):
    nodes: list[Node] = []
    relationships: list[Relationships] = []

    @classmethod
    def create(cls, triplets_data, user_name: str, ai_name: str):
        """LLMで生成されたTripletsをTripletsオブジェクトに変換する"""

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
            relationships = [
                Relationships.create(
                    type=relationship['type'],
                    # start_node, end_nodeが"I","Me"或いは"User"、または"You"の場合、それぞれを"user_name"と"ai_name"に変換
                    start_node=relationship['start_node'] if relationship['start_node'].lower() not in FIRST_PERSON_PRONOUNS +
                    SECOND_PERSON_PRONOUNS else user_name if relationship['start_node'].lower() in FIRST_PERSON_PRONOUNS else ai_name,
                    end_node=relationship['end_node'] if relationship['end_node'].lower() not in FIRST_PERSON_PRONOUNS +
                    SECOND_PERSON_PRONOUNS else user_name if relationship['end_node'].lower() in FIRST_PERSON_PRONOUNS else ai_name,
                    properties=relationship['properties'],
                    start_node_label=next((node.label for node in nodes if node.name == relationship['start_node']), None),
                    end_node_label=next((node.label for node in nodes if node.name == relationship['end_node']), None)
                )
                for relationship in triplets_data['Relationships']
                if 'type' in relationship and 'start_node' in relationship and 'end_node' in relationship  # 必要なキーが存在することを確認
            ]
            relationships = [relationship for relationship in relationships if relationship is not None]

        return cls(nodes=nodes, relationships=relationships)


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
        "大尉", "少佐", "中佐", "大佐", "准将", "少将", "中将", "大将", "元帥", "大元帥",
        "海兵", "上級海兵", "提督",
    ]
    family_prefixes = ["姉", "兄", "じ", "ば", "じい", "ばあ", "母", "父"]
    suffixes = ["さん", "ちゃん", "さま", "様", "殿", "どの", "氏", "上"]
    family_suffixes = [f + s for f in family_prefixes for s in suffixes]
    family_suffixes_o = ["お" + fs for fs in family_suffixes]

    all_suffixes = (
        ["さん", "くん", "君", "ちゃん", "さま", "様"]
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


class TempMemory(BaseModel):
    user_input: str
    ai_response: str
    triplets: Triplets | None = None         # 長期記憶(from neo4j)


class ShortMemory(BaseModel):
    short_memory: list[TempMemory] = []
    memory_limit: int = 7
    memory_nodes_set: set[Node] = set()
    memory_relationships_set: set[Relationships] = set()

    def memory_turn_over(self, user_input: str, ai_response: str, long_memory: Triplets | None = None):
        temp_memory = TempMemory(
            user_input=user_input,
            ai_response=ai_response,
            triplets=long_memory,
        )
        # short_memoryに追加
        self.short_memory.append(temp_memory)

        # short_memoryがmemory_limit(default = 7)個を超えたら、古いものから削除
        while len(self.short_memory) > self.memory_limit:
            self.short_memory.pop(0)

        # セットに変換（重複を削除）
        for temp_memory in self.short_memory:
            if temp_memory.triplets:
                self.memory_nodes_set.update(temp_memory.triplets.nodes)
                self.memory_relationships_set.update(temp_memory.triplets.relationships)


    # 入力されたuser_inputのentityに関連する情報を取得する。
    # 優先順位（1. start_node, end_nodeの一致、2. node.nameの一致、3. relationの片方のnodeの一致）
    # Background information from your memory:として、system_promptに追加するのが適当。
    async def activate_memory(self, user_input_entity: Triplets):
        # user_input_entityを取得
        nodes = user_input_entity.nodes if user_input_entity.nodes else []
        relationships = user_input_entity.relationships if user_input_entity.relationships else []

        # setと一致するnodes, relationshipsを取得
        matching_nodes = []
        matching_relationships = []

        # 1. Node(label, name)が一致するものを取得（propertiesを取得する目的）
        for node in nodes:
            # memory_nodes_set から一致するノードを検索
            matching_node = next((mn for mn in self.memory_nodes_set if mn == node), None)
            if matching_node:
                matching_nodes.append(matching_node)

        # 2. Relationship(start_node, end_node)が一致するものを取得（propertiesを取得する目的）
        for relationship in relationships:
            matching_relationship = next((mr for mr in self.memory_relationships_set if mr == relationship), None)
            if matching_relationship:
                matching_relationships.append(matching_relationship)

        # 3. end_node, start_nodeのいずれかに合致するrelationを検索して追加（relationを渡す目的）
        for node in nodes:
            matching_relationship = next((mr for mr in self.memory_relationships_set
                                          if (mr.start_node == node.name or mr.end_node == node.name)), None)
            if matching_relationship is not None:
                matching_relationships.append(matching_relationship)

        # 4. end_node <-[type="CONTAIN"]- Messageのrelationを検索して追加（relationを渡す目的）
        for node in nodes:
            matching_relationship = next((mr for mr in self.memory_relationships_set
                                          if (mr.end_node == node.name) and mr.type == "CONTAIN"), None)
            if matching_relationship is not None:
                matching_relationships.append(matching_relationship)

        logger.info(f"matching_nodes: {matching_nodes}")
        logger.info(f"matching_relationships: {matching_relationships}")
        # いずれも一致しない場合は、Noneを返す。
        if not matching_nodes and not matching_relationships:
            return None
        return Triplets(nodes=matching_nodes, relationships=matching_relationships)
