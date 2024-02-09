from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from ririse02.main import app


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.mark.done
class TestNeo4jCacheManagerRoutes:
    # テストクライアントを使用するためのfixtureをクラススコープで適用します
    @pytest.fixture(autouse=True)
    def _test_client_fixture(self, test_client):
        self.client = test_client

    @patch("ririse02.chat.neo4j.routers.neo4j.driver.get_neo4j_cache_manager", new_callable=Mock)
    def test_get_all_node_names(self, mock):

        response = self.client.get("/chat/all_node_names")

        # check response
        assert response.status_code == 200
        # check response body
        json_response = response.json()
        assert isinstance(json_response, list), "Response is not a list"
        assert all(isinstance(name, dict) for name in json_response), "Not all items in the response are dictionaries"

    @patch("ririse02.chat.neo4j.routers.neo4j.driver.get_neo4j_cache_manager", new_callable=Mock)
    def test_get_all_relationships(self, mock):

        response = self.client.get("/chat/all_relationships")

        # check response
        assert response.status_code == 200
        # check response body
        json_response = response.json()
        assert isinstance(json_response, list), "Response is not a list"

    @patch("ririse02.chat.neo4j.routers.neo4j.driver.get_neo4j_cache_manager", new_callable=Mock)
    def test_get_label_and_relationship_type_sets(self, mock):

        minimum_types = {"Scene,Message": ["CONTAIN"]}

        response = self.client.get("/chat/label_and_relationship_type_sets")

        # check response
        assert response.status_code == 200
        # check response body
        json_response = response.json()
        assert isinstance(json_response, dict), "Response is not a dictionary"
        assert all(isinstance(key, tuple | str) for key in json_response), "Not all keys in the response are tuples or strings"
        assert all(isinstance(value, list) for value in json_response.values()), "Not all values in the response are lists"

        for key in minimum_types:
            assert key in json_response, f"Key {key} is not in response"
            assert json_response[key] == minimum_types[key], f"Value for key {key} is not as expected"

    @patch("ririse02.chat.neo4j.routers.neo4j.driver.get_neo4j_cache_manager", new_callable=Mock)
    def test_get_node_labels(self, mock):
        minimum_labels = ["Message", "Scene"]

        response = self.client.get("/chat/node_labels")

        # check response
        assert response.status_code == 200
        # check response body
        json_response = response.json()
        assert isinstance(json_response, list), "Response is not a list"
        assert all(isinstance(item, str) for item in json_response), "Not all items in response are strings"
        assert all(label in json_response for label in minimum_labels), "Not all minimum labels are in response"

    @patch("ririse02.chat.neo4j.routers.neo4j.driver.get_neo4j_cache_manager", new_callable=Mock)
    def test_get_node_names(self, mock):
        test_names = ["彩澄しゅお", "彩澄りりせ"]

        label = "Person"
        response = self.client.get(f"/chat/node_names/{label}")

        # check response
        assert response.status_code == 200
        # check response body
        json_response = response.json()
        assert isinstance(json_response, list), "Response is not a list"
        assert all(name in json_response for name in test_names), "Not all minimum names are in response"

    @patch("ririse02.chat.neo4j.routers.neo4j.driver.get_neo4j_cache_manager", new_callable=Mock)
    def test_get_relationship_types(self, mock):

        minimum_types = ["CONTAIN", "FOLLOW", "PRECEDES"]

        response = self.client.get("/chat/relationship_types")

        # check response
        assert response.status_code == 200
        # check response body
        json_response = response.json()
        assert isinstance(json_response, list), "Response is not a list"
        assert all(isinstance(item, str) for item in json_response), "Not all items in response are strings"
        assert all(label in json_response for label in minimum_types), "Not all minimum labels are in response"
