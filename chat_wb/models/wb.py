from pydantic import BaseModel
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




class Memory(BaseModel):
    user_input: str
    ai_response: str
    from_long_memory: Triplets | None = None         # 長期記憶(from neo4j)


class ShortMemory(BaseModel):
    short_memory: list[Memory] = []

    @classmethod
    def memory_turn_over(self):
        latest_memory = Memory(
            user_input=self.temp_memory_user_input,
            ai_response="".join(self.temp_memory),
            long_memory=self.long_memory,
        )
        # short_memoryに追加
        short_memory.append(latest_memory)

        # short_memoryが7個を超えたら、古いものから削除
        while len(self.short_memory) > 7:
            self.short_memory.pop(0)

        # temp_memoryとlong_memoryをリセット
        self.temp_memory = []
        self.long_memory = None
        logger.info(f"client title: {self.title}")
        logger.info(f"short_memory: {self.short_memory}")


    # 入力されたuser_inputのentityに関連する情報を取得する。
    # Background information from your memory:として、system_promptに追加するのが適当か。
    def activate_memory(self):
        # self.user_input_entityを取得
        nodes = self.user_input_entity.nodes if self.user_input_entity.nodes else []
        relationships = self.user_input_entity.relationships if self.user_input_entity.relationships else []

        # long_memoryをセットに変換（重複を削除）
        memory_nodes_set = set(node for triplet in self.long_memory for node in triplet.nodes)
        memory_relationships_set = set(relationship for triplet in self.long_memory for relationship in triplet.relationships)

        # Node(label, name), Relationship(start_node, end_node)が一致するものをlong_memoryから取得（propertiesを取得する目的）
        for node in nodes:
            # memory_nodes_set から一致するノードを検索
            matching_node = next((mn for mn in memory_nodes_set if mn == node), None)
            if matching_node:
                # 一致するノードが見つかった場合、コピー
                node = matching_node

        for relationship in relationships:
            # memory_relationships_set から一致する関係を検索
            matching_relationship = next((mr for mr in memory_relationships_set if mr == relationship), None)
            if matching_relationship:
                # 一致する関係が見つかった場合、コピー
                relationship = matching_relationship

        return Triplets(nodes=nodes, relationships=relationships)
