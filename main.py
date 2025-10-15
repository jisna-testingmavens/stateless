from fastapi import FastAPI
from kubernetes import client, config
import os

app = FastAPI()

# Load Kubernetes config
if os.getenv("KUBERNETES_SERVICE_HOST"):
    config.load_incluster_config()
else:
    config.load_kube_config()

k8s_api = client.CoreV1Api()

USER_POD_IMAGE = "285982079759.dkr.ecr.us-east-1.amazonaws.com/statefull-repo:latest"
NAMESPACE = "default"


@app.post("/create_user_pod/{id}")
def create_user_pod(id: str):
    """Create a user-specific pod (no LoadBalancer)."""
    pod_name = f"user-session-{id}"

    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": pod_name, "labels": {"app": "user-pod", "user-id": id}},
        "spec": {
            "containers": [{
                "name": "user-session",
                "image": USER_POD_IMAGE,
                "ports": [{"containerPort": 5901}],
            }]
        },
    }

    try:
        k8s_api.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
        return {"message": f"Pod '{pod_name}' created successfully."}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.get("/get_pod_details/{id}")
def get_pod_details(id: str):
    """Get details for a specific user pod."""
    pod_name = f"user-session-{id}"
    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {
            "pod_name": pod.metadata.name,
            "status": pod.status.phase,
            "pod_ip": pod.status.pod_ip,
        }
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.get("/get_list_of_pods")
def get_list_of_pods():
    """Return a list of all user pods and their IPs."""
    pods = k8s_api.list_namespaced_pod(namespace=NAMESPACE, label_selector="app=user-pod")
    return [
        {
            "pod_name": pod.metadata.name,
            "user_id": pod.metadata.labels.get("user-id"),
            "status": pod.status.phase,
            "pod_ip": pod.status.pod_ip,
        }
        for pod in pods.items
    ]
