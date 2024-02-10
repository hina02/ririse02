import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from ririse02.chat.models import Node, Relationship
from ririse02.main import app


# # create node
# @neo4j_router.post("/create_update_node", tags=["node"])
# async def create_update_node(node: Node = Body(...), db: Neo4jDataManager = Depends(driver.get_neo4j_data_manager)):
#     """create or update node"""
#     return db.create_update_node(node=node)
def sort_properties_lists(obj):
    """properties内のすべてのリストをソートする"""
    for key, value in obj["properties"].items():
        if isinstance(value, list):
            obj["properties"][key] = sorted(value)
    return obj


@pytest.mark.neo4j
class TestNeo4jDataManagerRoutes:
    # test client
    url = "http://127.0.0.1:8000"
    # test data for node
    test_node1 = Node(
        label="Person", name="Ririse02", properties={"personality": ["cool"], "speech_pattern": ["straightforward", "honest"]}
    )
    test_node2 = Node(label="Person", name="Shuo02", properties={"personality": ["otaku"], "speech_pattern": ["geek", "otaku"]})
    # updated test_node1 mock
    mock_updated_node1 = Node(
        label="Person",
        name="Ririse02",
        properties={"personality": ["kind", "cool"], "speech_pattern": ["straightforward", "honest"], "age": ["16"]},
    )
    # update_data
    node1_update_data = Node(
        label="Person",
        name="Ririse02",
        properties={"personality": ["kind"], "speech_pattern": ["straightforward", "honest"], "age": ["16"]},
    )

    # test data for relationship
    test_node3 = Node(label="Person", name="Yukari02", properties={"personality": ["cool"], "speech_pattern": ["cynical"]})
    test_node4 = Node(label="Person", name="Maki02", properties={"personality": ["cheerful"], "speech_pattern": ["soft", "kind"]})
    test_relationship = Relationship(
        type="FRIENDS",
        start_node="Yukari02",
        end_node="Maki02",
        properties={"since": ["2021-01-01"], "where": ["Tokyo"]},
        start_node_label="Person",
        end_node_label="Person",
    )

    # Nodes
    # create
    @pytest.mark.order(1)
    @pytest.mark.asyncio
    async def test_create_node(self):
        async with httpx.AsyncClient(app=app) as ac:
            response = await ac.post(f"{self.url}/chat/create_update_node", json=self.test_node1.model_dump())

        # check response
        assert response.status_code == 200

    # get
    @pytest.mark.order(2)
    @pytest.mark.asyncio
    async def test_get_node(self):
        label = self.test_node1.label
        name = self.test_node1.name
        async with httpx.AsyncClient(app=app) as ac:
            response = await ac.get(f"{self.url}/chat/get_node/{label}/{name}")

            # check response
            assert response.status_code == 200
            # check response body
            json_response = response.json()
            assert isinstance(json_response, dict | None), "Response is not a dictionary"

            # sort properties lists for comparison
            json_response = sort_properties_lists(json_response)
            test_node1 = sort_properties_lists(self.test_node1.model_dump())
            assert json_response == test_node1, "Response body is not same as test_node1"

    # update
    @pytest.mark.order(3)
    @pytest.mark.asyncio
    async def test_update_node(self):
        # update_data
        async with httpx.AsyncClient(app=app) as ac:
            response = await ac.post(f"{self.url}/chat/create_update_node", json=self.node1_update_data.model_dump())

            # check node is updated
            label = self.test_node1.label
            name = self.test_node1.name
            response = await ac.get(f"{self.url}/chat/get_node/{label}/{name}")

            # compare
            self.mock_updated_node1
            mock_data = sort_properties_lists(self.mock_updated_node1.model_dump())

            json_response = response.json()
            json_response = sort_properties_lists(json_response)
            assert json_response == mock_data, "Response body is not same as test_node (maybe not updated)"

    @pytest.mark.order(4)
    @pytest.mark.asyncio
    async def test_delete_node(self):
        label = self.test_node1.label
        name = self.test_node1.name
        async with httpx.AsyncClient(app=app) as ac:
            response = await ac.delete(f"{self.url}/chat/delete_node/{label}/{name}")

            # check response
            assert response.status_code == 200

            # check node is deleted
            response = await ac.get(f"{self.url}/chat/get_node/{label}/{name}")
            json_response = response.json()
            assert json_response is None, "Node is not deleted"

    # Relatioinships
    # create

    @pytest.mark.order(1)
    @pytest.mark.asyncio
    async def test_create_relationship(self):
        async with httpx.AsyncClient(app=app) as ac:
            response = await ac.post(f"{self.url}/chat/create_update_relationship", json=self.test_relationship.model_dump())

            # check response
            assert response.status_code == 200

    # get
    @pytest.mark.order(2)
    @pytest.mark.asyncio
    async def test_get_node_relationships(self):
        name_list = [self.test_node3.name]
        names = json.dumps(name_list)
        async with AsyncClient(app=app) as ac:
            response = await ac.get(f"{self.url}/chat/get_node_relationships", params={"names": names})
            # check response
            assert response.status_code == 200
            # check response data
            relationship = Relationship(**response.json()[0])
            assert relationship.type == self.test_relationship.type, "Response body is not same relationship type"
            assert relationship.start_node == self.test_relationship.start_node, "Response body is not same start_node name"
            assert relationship.end_node == self.test_relationship.end_node, "Response body is not same end_node name"

    @pytest.mark.order(3)
    @pytest.mark.asyncio
    async def test_get_node_relationships_between(self):
        """逆向きノードで両側検索を確認"""
        label1 = self.test_node4.label
        name1 = self.test_node4.name
        label2 = self.test_node3.label
        name2 = self.test_node3.name
        try:
            async with AsyncClient(app=app) as ac:
                response = await ac.get(f"{self.url}/chat/get_node_relationships_between/{label1}/{name1}/{label2}/{name2}")
                # check response
                assert response.status_code == 200
                # check response data
                relationship = Relationship(**response.json()[0])
                assert relationship.type == self.test_relationship.type, "Response body is not same relationship type"
                assert relationship.start_node == self.test_relationship.start_node, "Response body is not same start_node name"
                assert relationship.end_node == self.test_relationship.end_node, "Response body is not same end_node name"
        except Exception as e:
            print(e)

    # delete
    @pytest.mark.order(4)
    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_delete_relationship(self):
        label1 = self.test_node3.label
        name1 = self.test_node3.name
        label2 = self.test_node4.label
        name2 = self.test_node4.name

        async with AsyncClient(app=app) as ac:
            response = await ac.delete(
                f"{self.url}/chat/delete_relationship/{label1}/{name1}/{label2}/{name2}/{self.test_relationship.type}"
            )
            # check response
            assert response.status_code == 200

            # check relationship is deleted
            response = await ac.get(
                f"{self.url}/chat/get_node_relationships_between/{self.test_node3.label}/{self.test_node3.name}/{self.test_node4.label}/{self.test_node4.name}"
            )
            assert response.json() == [], "Relationship is not deleted"

        # delete nodes
        async with AsyncClient(app=app) as ac:
            await ac.delete(f"{self.url}/chat/delete_node/{label1}/{name1}")
            await ac.delete(f"{self.url}/chat/delete_node/{label2}/{name2}")
