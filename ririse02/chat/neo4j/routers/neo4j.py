import json
from logging import getLogger

from fastapi import APIRouter, Body, Depends, HTTPException

from ...models import Node, Relationship
from ..driver import Neo4jCacheManager, Neo4jDataManager
from ..driver import Neo4jDriverManager as driver
from ..driver import Neo4jNodeIntegrator

logger = getLogger(__name__)

neo4j_router = APIRouter()


# Neo4jCacheManager
@neo4j_router.get("/node_labels", tags=["cache"])
def get_node_labels(cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager)) -> list[str]:
    """get all node labels"""
    return cache.get_node_labels()


@neo4j_router.get("/relationship_types", tags=["cache"])
def get_relationship_types(cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager)) -> list[str]:
    """get all relationship types"""
    return cache.get_relationship_types()


@neo4j_router.get("/label_and_relationship_type_sets", tags=["cache"])
def get_label_and_relationship_type_sets(
    cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager),
) -> dict | None:
    """get all pairs {(node1.label, node2.label) : relationship_type}"""
    return cache.get_label_and_relationship_type_sets()


@neo4j_router.get("/node_names/{label}", tags=["cache"])
def get_node_names(label: str, cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager)) -> list[str]:
    """get all node names in the label"""
    return cache.get_node_names(label)


@neo4j_router.get("/all_node_names", tags=["cache"])
def get_all_node_names(cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager)) -> list[Node]:
    """get all node names with label except Message and Scene."""
    return cache.get_all_nodes()


@neo4j_router.get("/all_relationships", tags=["cache"])
def get_all_relationships(cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager)) -> list[Relationship]:
    """get all relationships without properties."""
    return cache.get_all_relationships()


# Neo4jDataManager
# Node
@neo4j_router.get("/get_node/{label}/{name}", tags=["node"])
async def get_node(label: str, name: str, db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)):
    """get node by label and name"""
    node = Node(label=label, name=name, properties={})
    async with db.driver.session(database="neo4j") as session:
        # execute transaction
        result = await session.execute_read(db.get_node, node=node)
    return result


@neo4j_router.delete("/delete_node/{label}/{name}", tags=["node"])
async def delete_node(label: str, name: str, db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)):
    """delete node by label and name"""
    return await db.delete_node(node=Node(label=label, name=name, properties={}))


# create node
@neo4j_router.post("/create_update_node", tags=["node"])
async def create_update_node(node: Node = Body(...), db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)):
    """create or update node"""
    return await db.create_update_node(node=node)


# get node relationship
@neo4j_router.get("/get_node_relationships/{names}", tags=["relationship"])
async def get_node_relationships(names: str, db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)):
    """get node relationships by name list"""
    try:
        names = json.loads(names)
        match names:
            case list() as lst:
                triplets = await db.get_node_relationships(lst)
                return triplets.relationships
            case _:
                raise HTTPException(status_code=400, detail="List expected. Invalid JSON format.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")


# between node1 and node2
@neo4j_router.get("/get_node_relationships_between/{label1}/{name1}/{label2}/{name2}", tags=["relationship"])
async def get_node_relationships_between(
    label1: str, name1: str, label2: str, name2: str, db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)
):
    """get relationships between node1 and node2"""
    node1 = Node(label=label1, name=name1, properties={})
    node2 = Node(label=label2, name=name2, properties={})
    async with db.driver.session(database="neo4j") as session:
        # execute transaction
        relationships = await session.execute_read(db.get_node_relationships_between, node1=node1, node2=node2)
    return relationships


# update
@neo4j_router.put("/create_update_relationship", tags=["relationship"])
async def create_update_relationship(relationship: Relationship = Body(...), db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)):
    """create or update relationship"""
    return await db.create_update_relationship(relationship)


@neo4j_router.delete("/delete_relationship/{label1}/{name1}/{label2}/{name2}/{relationship_type}", tags=["relationship"])
async def delete_relationship(
    label1: str, name1: str, label2: str, name2: str, relationship_type: str, db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)
):
    """delete relationship"""
    return await db.delete_relationship(
        relationship=Relationship(
            type=relationship_type,
            start_node=name1,
            end_node=name2,
            start_node_label=label1,
            end_node_label=label2,
            properties={},
        )
    )


# integrate node
@neo4j_router.put("/integrate_nodes/{label1}/{name1}/{label2}/{name2}", tags=["node"])
async def integrate_nodes(
    label1: str, name1: str, label2: str, name2: str, db: Neo4jNodeIntegrator = Depends(driver.get_neo4j_node_integrator)
):
    """integrate nodes by name variations, properties, and relationships to node1. For secure, separate the delete node2 process."""
    node1 = Node(label=label1, name=name1, properties={})
    node2 = Node(label=label2, name=name2, properties={})
    return await db.integrate_nodes(node1, node2)
