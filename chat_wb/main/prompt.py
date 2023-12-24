from chat_wb.cache import (
    fetch_labels,
    fetch_relationships,
)

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
elif it is type of question: type is "question".
else: type is "chat".

Output json format is here.
{{"type": "chat" or "code" or "document" pr "question"}}
"""

# fetch_label_and_relationship_type_sets

NODE_LABELS = fetch_labels()
RELATION_TYPES = fetch_relationships()
RELATION_SETS = None  # fetch_label_and_relationship_type_sets()


# Iの変換は行う。Youの変換は行わない。このプロンプトだけでは不十分なので、後でI,Youの変換を直接行う。
# conference resolution, ellipsis resolution, contextual completionを用い、代名詞の補正等を行う。
# [OPTIMIZE] relatiohsips.properties key example
EXTRACT_TRIPLET_PROMPT = """
Output json format to neo4j without id.

Given a sentence, your task is to apply coreference resolution, ellipsis resolution, and contextual completion to the sentence.
Specifically, identify and resolve any instances where pronouns or demonstratives refer to specific nouns (coreference resolution),
fill in any missing elements implied by the context but not explicitly stated in the sentence (ellipsis resolution),
and enhance the overall understanding of the sentence by adding necessary contextual information (contextual completion).
If the sentence expressed with first person pronouns in any language (e.g. 'I', 'my', 'me' etc.), use "{user}".
If the sentence expressed with second person pronouns in any language (e.g. 'you', 'your', etc.), use "{ai}".

If len(Nodes) > 2, Relationship_types is required.
If there is no node and relationship, output is {{Nodes: [], Relationships: []}}.
Please avoid using abstract or non-specific terms.
{{Nodes: [{{"label", "name", "properties"}}],
Relationships: [{{"start_node": "", "end_node": "", "type": "", "properties": dict(detailed information(e.g., action, time, etc.))}}]}}
"""
