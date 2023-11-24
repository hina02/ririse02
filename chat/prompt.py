from cache import (
    fetch_labels,
    fetch_relationships,
)

# langchain prompt
# QueryがContext関係するか判定する
BOOLEAN_IS_QUERY_IN_CONTEXT_PROMPT = """
Given the following question and context, return YES if the context is relevant to the question and NO if it isn't.

> Question: {question}
> Context:
>>>
{context}
>>>
> Relevant (YES / NO):
"""


# memoryを要約するプロンプト
SUMMARIZER_TEMPLATE = """Progressively summarize the lines of current conversation provided, returning a Summary.

EXAMPLE
Current conversation:
Human: Why do you think artificial intelligence is a force for good?
AI: Because artificial intelligence will help humans reach their full potential.

Summary:
The human asks what the AI thinks of artificial intelligence. The AI thinks artificial intelligence is a force for good because it will help humans reach their full potential.
END OF EXAMPLE

Current conversation:
{memory}

Summary:"""



# fetch_label_and_relationship_type_sets

NODE_LABELS = fetch_labels()
RELATION_TYPES = fetch_relationships()
RELATION_SETS = None  # fetch_label_and_relationship_type_sets()


# 代名詞を補正するプロンプト
# 全文からの出力だと3秒～かかる。tripletからだともっとかかる。ある程度、一文からの出力を安定させた。
COREFERENCE_RESOLUTION_PROMPT = """
Given a sentence, your task is to identify and replace pronouns in each sentence with the proper noun they refer to in the original context if pronouns in a sentence.

Use coreference resolution to make these replacements accurate and contextually correct.
The goal is to maintain the original meaning of a sentence.
For example, if the input sentence is 'That movie was very fantastic!' and reference is ['Did you watch RRR?', 'That movie was very fantastic!'], the response should be 'RRR was very fantastic!'.

The output should be a single sentence in which any pronouns have been accurately replaced with their respective referents from the context.
If a sentence does not contain any pronouns, it should be included in the output unchanged sentence.

output_format is {{output sentence}}
"""


# tripletを抽出し、grpheのtypeを判定するプロンプト
# ●●をどう思いますか？等の質問文に対しては、出力なしの傾向。
# subject,objectをsubject_nameから、proper nounに指定したことで、嫁等よりも、人名が優先されるようになった。
EXTRACT_MULTITEMPORALTRIPLET_PROMPT_FW = """
Based on the context in your text, please extract all the 'TemporalTriplets' which includes "subject", "predicate", "object", and, if present, 'time'.
Your output should conform to the Pydantic model, TemporalTriplet, with the following structure:

{{{{"subject":['proper noun','NodeLabel'],
"predicate":["predicate", 'RelationType'],
"object":['proper noun', 'NodeLabel'],
'time': 'time_information|None'
}}}}
"""

EXTRACT_MULTITEMPORALTRIPLET_PROMPT_BW = f"""
In addition, please resolve any coreferences found in the context.
Coreferences are when a word or phrase in the text refers to another proper noun mentioned earlier in the text.
For instance, in the sentence "John said he would go to the store", "he" is a coreference to "John".
After resolving coreferences, your extracted triplets should use the actual proper nouns instead of pronouns.

where 'subject', "predicate", and 'object' are derived from the context in the text,
'label' in Node corresponds to NodeLabel which should be one of the following: {NODE_LABELS}
and
'relation' in Relation corresponds to RelationType which should be one of the following: {RELATION_TYPES}

Please note that the order matters. The relationship should be interpreted in the direction from the subject to the object. Here are the valid combinations:
{RELATION_SETS}

Please return a list of TemporalTriplets extracted from the context. Each sentence or clause in the context might result in one or more TemporalTriplets.
Your output should capture all relevant information in the context.
"""

EXTRACT_MULTITEMPORALTRIPLET_PROMPT = (
    EXTRACT_MULTITEMPORALTRIPLET_PROMPT_FW + EXTRACT_MULTITEMPORALTRIPLET_PROMPT_BW
)
