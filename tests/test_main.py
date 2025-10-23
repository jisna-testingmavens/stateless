import pytest
from fastapi.testclient import TestClient
from app.main import app

# --- MOCK Kubernetes API (so we don't call a real cluster) ---
@pytest.fixture(autouse=True)
def mock_k8s(monkeypatch):
    class MockPod:
        def __init__(self, name, labels, phase="Running", pod_ip="10.0.0.1"):
            self.metadata = type("meta", (), {"name": name, "labels": labels})
            self.status = type("status", (), {"phase": phase, "pod_ip": pod_ip})

    class MockK8sAPI:
        def __init__(self):
            self.created_pods = []

        def create_namespaced_pod(self, namespace, body):
            self.created_pods.append(body)
            return body

        def list_namespaced_pod(self, namespace, label_selector=None):
            mock_pod = MockPod("user-session-1", {"app": "user-pod", "user-id": "1"})
            return type("obj", (), {"items": [mock_pod]})

        def read_namespaced_pod(self, name, namespace):
            if name == "user-session-404":
                raise Exception("Pod not found")
            return MockPod(name, {"user-id": "1"})

    monkeypatch.setattr("app.main.k8s_api", MockK8sAPI())
    yield

# --- Setup test client ---
client = TestClient(app)

# --- Tests ---

def test_create_user_pod():
    response = client.post("/create_user_pod/123")
    assert response.status_code == 200
    assert "created successfully" in response.json()["message"]

def test_get_list_of_pods():
    response = client.get("/get_list_of_pods")
    assert response.status_code == 200
    pods = response.json()
    assert isinstance(pods, list)
    assert pods[0]["pod_name"].startswith("user-session-")
    assert pods[0]["status"] == "Running"

def test_get_pod_details_success():
    response = client.get("/get_pod_details/1")
    assert response.status_code == 200
    assert response.json()["pod_name"] == "user-session-1"

def test_get_pod_details_not_found():
    response = client.get("/get_pod_details/404")
    assert response.status_code == 200  # app returns {"error": "..."}
    assert "error" in response.json()
