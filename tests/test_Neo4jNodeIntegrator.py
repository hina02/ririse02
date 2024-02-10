import httpx
import pytest
from httpx import AsyncClient

from ririse02.chat.models import Node, Relationship
from ririse02.main import app


@pytest.mark.test
class TestNeo4jNodeIntegratorRoutes:
    # test client
    url = "http://127.0.0.1:8000"

    # test data for integration
    test_node1 = Node(label="Person", name="Yuduki02", properties={"personality": ["shy"]})
    test_node2 = Node(label="Person", name="Yukari02", properties={"personality": ["cool"], "speech_pattern": ["cynical"]})
    test_relationship = Relationship(
        type="FRIENDS",
        start_node="Yukari02",
        end_node="Maki02",
        properties={"since": ["2021-01-01"], "where": ["Tokyo"]},
        start_node_label="Person",
        end_node_label="Person",
    )

    @pytest.mark.asyncio
    async def test_integrate_nodes(self):
        async with httpx.AsyncClient(app=app) as ac:
            label1 = self.test_node1.label
            name1 = self.test_node1.name
            label2 = self.test_node2.label
            name2 = self.test_node2.name
            # ready test data
            await ac.post(f"{self.url}/chat/create_update_node", json=self.test_node1.model_dump())
            await ac.post(f"{self.url}/chat/create_update_node", json=self.test_node2.model_dump())
            await ac.post(f"{self.url}/chat/create_update_relationship", json=self.test_relationship.model_dump())

            # main process
            response = await ac.put(f"{self.url}/chat/integrate_nodes/{label1}/{name1}/{label2}/{name2}")

            # check response
            assert response.status_code == 200

            # check node is integrated
            node_response = await ac.get(f"{self.url}/chat/get_node/{label1}/{name1}")
            node = node_response.json()
            assert node["properties"]["name_variation"] == [name2], "Node name is not integrated"
            assert node["properties"]["speech_pattern"] == ["cynical"], "Node properties is not integrated"

            # check relationship is integrated
            label3 = self.test_relationship.end_node_label
            name3 = self.test_relationship.end_node
            rel_response = await ac.get(f"{self.url}/chat/get_node_relationships_between/{label1}/{name1}/{label3}/{name3}")
            relationships = rel_response.json()
            assert relationships, "Relationship is not integrated"
            if relationships:
                relationship = Relationship(**relationships[0])
                assert relationship.type == self.test_relationship.type, "Relationship type is not correctly integrated"

        # delete mock data
        async with AsyncClient(app=app) as ac:
            await ac.delete(f"{self.url}/chat/delete_node/{label1}/{name1}")
            await ac.delete(f"{self.url}/chat/delete_node/{label2}/{name2}")
