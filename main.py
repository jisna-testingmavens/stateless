from fastapi import FastAPI
from kubernetes import client, config
import os

app = FastAPI()

# Load Kubernetes config (works both inside and outside the cluster)
if os.getenv("KUBERNETES_SERVICE_HOST"):
    config.load_incluster_config()
else:
    config.load_kube_config()

k8s_api = client.CoreV1Api()

USER_POD_IMAGE = "285982079759.dkr.ecr.us-east-1.amazonaws.com/statefull-repo:latest"
NAMESPACE = "default"


@app.post("/create_user_pod/{id}")
def create_user_pod(id: str):
    # ✅ Use a different prefix to avoid StatefulSet conflict
    pod_name = f"user-session-{id}"

    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "labels": {
                "app": "user-pod",   # Keep this label for Service matching
                "user-id": id
            }
        },
        "spec": {
            "containers": [{
                "name": "user-session",
                "image": USER_POD_IMAGE,
                "ports": [{"containerPort": 5901}]  # VNC port
            }]
        }
    }

    try:
        k8s_api.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
        return {"message": f"Pod {pod_name} created with labels."}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.get("/get_pod_details/{id}")
def get_pod_details(id: str):
    pod_name = f"user-session-{id}"
    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {
            "pod_name": pod.metadata.name,
            "status": pod.status.phase,
            "ip": pod.status.pod_ip,
            "labels": pod.metadata.labels
        }
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.get("/get_status/{id}")
def get_status(id: str):
    pod_name = f"user-session-{id}"
    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {"status": pod.status.phase}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.delete("/delete_user_pod/{id}")
def delete_user_pod(id: str):
    pod_name = f"user-session-{id}"
    try:
        k8s_api.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {"message": f"Pod {pod_name} deleted."}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}
