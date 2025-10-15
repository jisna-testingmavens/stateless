from fastapi import FastAPI
from kubernetes import client, config
import os

app = FastAPI()

# --- Load Kubernetes Config ---
if os.getenv("KUBERNETES_SERVICE_HOST"):
    config.load_incluster_config()  # inside cluster
else:
    config.load_kube_config()       # for local testing

k8s_api = client.CoreV1Api()

# --- Constants ---
USER_POD_IMAGE = "285982079759.dkr.ecr.us-east-1.amazonaws.com/statefull-repo:latest"
NAMESPACE = "default"


#  Create a new user pod
@app.post("/create_user_pod/{id}")
def create_user_pod(id: str):
    """
    Create a new stateful user pod (no service).
    """
    pod_name = f"user-session-{id}"

    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "labels": {
                "app": "user-pod",
                "user-id": id
            }
        },
        "spec": {
            "containers": [{
                "name": "user-session",
                "image": USER_POD_IMAGE,
                "ports": [{"containerPort": 5901}],
                "resources": {
                    "requests": {"cpu": "250m", "memory": "256Mi"},
                    "limits": {"cpu": "500m", "memory": "512Mi"}
                }
            }]
        }
    }

    try:
        k8s_api.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
        return {
            "message": f" Pod '{pod_name}' created successfully.",
            "pod_name": pod_name
        }
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


#  Get details of a specific user pod
@app.get("/get_pod_details/{id}")
def get_pod_details(id: str):
    """
    Retrieve pod details for a given user ID.
    """
    pod_name = f"user-session-{id}"

    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {
            "pod_name": pod.metadata.name,
            "status": pod.status.phase,
            "pod_ip": pod.status.pod_ip,
            "labels": pod.metadata.labels,
            "node_name": pod.spec.node_name
        }
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


# Get running status
@app.get("/get_status/{id}")
def get_status(id: str):
    """
    Simple endpoint to check pod running status.
    """
    pod_name = f"user-session-{id}"
    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {"pod_name": pod_name, "status": pod.status.phase}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


#  List all active user pods
@app.get("/get_list_of_pods")
def get_list_of_pods():
    """
    List all pods created by this stateless service (filter by label 'app=user-pod').
    """
    try:
        pods = k8s_api.list_namespaced_pod(namespace=NAMESPACE, label_selector="app=user-pod")
        pod_list = []
        for pod in pods.items:
            pod_list.append({
                "pod_name": pod.metadata.name,
                "user_id": pod.metadata.labels.get("user-id"),
                "status": pod.status.phase,
                "pod_ip": pod.status.pod_ip
            })
        return {"count": len(pod_list), "pods": pod_list}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


#  Delete a user pod
@app.delete("/delete_user_pod/{id}")
def delete_user_pod(id: str):
    """
    Delete the specified user pod.
    """
    pod_name = f"user-session-{id}"

    try:
        k8s_api.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {"message": f"🗑️ Pod '{pod_name}' deleted successfully."}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}
