from chat_wb.neo4j.driver import Neo4jDriverManager as manager

cache_manager = manager.get_neo4j_cache_manager()
# global変数の設定（1日に1回（キャッシュのTTLが過ぎるたびに）読み込む（# 初回のデータ取得））
NODE_LABELS = cache_manager.fetch_labels()
RELATION_TYPES = cache_manager.fetch_relationships()
RELATION_SETS = None  # fetch_label_and_relationship_type_sets()


# code blockを要約するプロンプト
CODE_SUMMARIZER_PROMPT = """
Provide a summary of the code blocks and logs in a few sentences.
Output json format to single neo4j node without id.
{{Nodes: [{{"label":"Code" or "ErrorLog", "name", "properties":dict}}],
"""

# manual documentを要約するプロンプト
DOCS_SUMMARIZER_PROMPT = """
Summarize this text in one sentence.
Output json format to single neo4j node without id.
{{Nodes: [{{"label":document type like manual, tutorial, article, news, report, journal, blog, code documentation, etc, "name":document name, "properties":dict}}],
"""

# 与えられたtextの種類をchat, code, documentに分類し、triageする。
TEXT_TRIAGER_PROMPT = """
Given a text, your task is to identify the type of text and return the type of text.
If it is constructed from "code blocks" or "error logs": type is "code".
elif it is long documents like manual, tutorial, journal, report, API document, etc: type is "document".
else: type is "chat".

Output json format is here.
{{"type": "chat" or "code" or "document"}}
"""

# I,Youを固有名詞に変換する。
# conference resolution, ellipsis resolution, contextual completionを用い、代名詞の補正等を行う。
# 質問文の箇所を除外する。抽象的な情報はノードのプロパティとして扱う。
# Relationship typeはACTIONとSTATICの2種類に分類し、STATICはそのままtypeとする。Actionは通常時間情報を含む。
# このプロンプトを入れると、ユーザー主体のリレーションシップになりやすくなる。"This is a line spoken by {user} during a chat between {user} and {ai}."
EXTRACT_TRIPLET_PROMPT = """
Output JSON format to neo4j without id.

Your task is to apply coreference resolution, ellipsis resolution,
and contextual completion to the sentence for the correct nodes and relationships to be extracted.
Exclude sentences that are questions from the nodes and relationships extraction process.
Specifically, identify and resolve any instances where pronouns or demonstratives refer to specific nouns (coreference resolution),
fill in any missing elements implied by the context but not explicitly stated in the sentence (ellipsis resolution),
and enhance the overall understanding of the sentence by adding necessary contextual information (contextual completion).
In any text, replace first person pronouns (e.g., 'I', 'my', 'me', etc.) with '{user}'.
In any text, replace second person pronouns (e.g., 'you', 'your', etc.) with '{ai}'.

Nodes are entity-like.
Abstract concepts should be treated as properties of the nodes.
Relationship types should explicitly describe the relationship between the nodes.
If relationship type is action-like, consider that this text is a line spoken by {user} during a chat between {user} and {ai}.
If time is mentioned, time is treated as the properties of relationships (Current Time: {current_time}).

If there is no node and relationship, output is {{Nodes: [], Relationships: []}}.
Output JSON format is {{Nodes: [{{"label", "name", "properties"}}],
Relationships: [{{"start_node", "end_node", "type", "properties"}}]}}.
"""

EXTRACT_ENTITY_PROMPT = """
Output all entities in JSON format using a single key 'Entity'.
Entities should be Stemmed and Lemmatized.
In any text, replace first person pronouns (e.g., 'I', 'my', 'me', etc.) with '{user}'.
In any text, replace second person pronouns (e.g., 'you', 'your', etc.) with '{ai}'.

If there are no entity, output is {{'Entity': []}}.
Output JSON format is {{'Entity': list(str)}}.
"""
