from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from kubernetes import client, config
import os
import asyncio
import websockets

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


@app.websocket("/proxy/{id}")
async def websocket_proxy(websocket: WebSocket, id: str):
    """
    Proxy VNC WebSocket traffic between browser and pod.
    """
    await websocket.accept()
    pod_name = f"user-session-{id}"

    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        pod_ip = pod.status.pod_ip

        if not pod_ip:
            await websocket.send_text(" Pod not ready yet.")
            await websocket.close()
            return

        # Connect to pod's VNC server (port 5901)
        target_url = f"ws://{pod_ip}:5901"
        async with websockets.connect(target_url) as pod_ws:
            async def browser_to_pod():
                try:
                    while True:
                        msg = await websocket.receive_bytes()
                        await pod_ws.send(msg)
                except WebSocketDisconnect:
                    await pod_ws.close()

            async def pod_to_browser():
                try:
                    while True:
                        msg = await pod_ws.recv()
                        await websocket.send_bytes(msg)
                except:
                    await websocket.close()

            await asyncio.gather(browser_to_pod(), pod_to_browser())

    except Exception as e:
        await websocket.send_text(f"Error: {str(e)}")
        await websocket.close()
