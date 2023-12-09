from pydantic import BaseModel
from logging import getLogger
from chat_wb.models.neo4j import Triplets


# WebScoketで受け取るデータのモデル
class WebSocketInputData(BaseModel):
    user: str
    AI: str
    source: str     # user_id or assistant_id(asst_) # user_id作成時にasst_の使用を禁止する
    input_text: str
    title: str | None = None
    former_node_id: int | None = None   # node_idを渡すことで、途中のメッセージに新しいメッセージを追加することができる。
                                        # 使用する場合、フロントで枝分かれの表示方法の実装が必要。


logger = getLogger(__name__)


class TempMemory(BaseModel):
    user_input: str
    ai_response: str
    triplets: Triplets | None = None         # 長期記憶(from neo4j)


class ShortMemory(BaseModel):
    short_memory: list[TempMemory] = []
    memory_limit: int = 7

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

    # 入力されたuser_inputのentityに関連する情報を取得する。
    # 優先順位（1. start_node, end_nodeの一致、2. node.nameの一致、3. relationの片方のnodeの一致）
    # Background information from your memory:として、system_promptに追加するのが適当。
    async def activate_memory(self, user_input_entity: Triplets):
        # user_input_entityを取得
        nodes = user_input_entity.nodes if user_input_entity.nodes else []
        relationships = user_input_entity.relationships if user_input_entity.relationships else []

        # 全てのtripletsを集め、セットに変換（重複を削除）
        memory_nodes_set = set()
        memory_relationships_set = set()

        for temp_memory in self.short_memory:
            if temp_memory.triplets:
                memory_nodes_set.update(temp_memory.triplets.nodes)
                memory_relationships_set.update(temp_memory.triplets.relationships)

        # setと一致するnodes, relationshipsを取得
        matching_nodes = []
        matching_relationships = []

        # 1. Node(label, name)が一致するものを取得（propertiesを取得する目的）
        for node in nodes:
            # memory_nodes_set から一致するノードを検索
            matching_node = next((mn for mn in memory_nodes_set if mn == node), None)
            if matching_node:
                matching_nodes.append(matching_node)

        # 2. Relationship(start_node, end_node)が一致するものを取得（propertiesを取得する目的）
        for relationship in relationships:
            matching_relationship = next((mr for mr in memory_relationships_set if mr == relationship), None)
            if matching_relationship:
                matching_relationships.append(matching_relationship)

        # 3. end_node, start_nodeのいずれかに合致するrelationを検索して追加（relationを渡す目的）
        for node in nodes:
            matching_relationship = next((mr for mr in memory_relationships_set
                                        if (mr.start_node == node.name or mr.end_node == node.name)), None)
            if matching_relationship is not None:
                matching_relationships.append(matching_relationship)

        # 4. end_node <-[type="CONTAIN"]- Messageのrelationを検索して追加（relationを渡す目的）
        for node in nodes:
            matching_relationship = next((mr for mr in memory_relationships_set
                                        if (mr.end_node == node.name) and mr.type == "CONTAIN"), None)
            if matching_relationship is not None:
                matching_relationships.append(matching_relationship)

        logger.info(f"matching_nodes: {matching_nodes}")
        logger.info(f"matching_relationships: {matching_relationships}")
        # いずれも一致しない場合は、Noneを返す。
        if not matching_nodes and not matching_relationships:
            return None
        return Triplets(nodes=matching_nodes, relationships=matching_relationships)
