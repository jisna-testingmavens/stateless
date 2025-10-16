# main.py
import os
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from kubernetes import client, config
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stateless-api")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# K8s config
if os.getenv("KUBERNETES_SERVICE_HOST"):
    config.load_incluster_config()
else:
    config.load_kube_config()

k8s_api = client.CoreV1Api()
USER_POD_IMAGE = os.getenv("USER_POD_IMAGE", "285982079759.dkr.ecr.us-east-1.amazonaws.com/statefull-repo:latest")
NAMESPACE = os.getenv("NAMESPACE", "default")


@app.post("/create_user_pod/{id}")
def create_user_pod(id: str):
    pod_name = f"user-session-{id}"
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": pod_name, "labels": {"app": "user-pod", "user-id": id}},
        "spec": {"containers": [{"name": "user-session", "image": USER_POD_IMAGE, "ports": [{"containerPort": 5901}]}]},
    }
    try:
        k8s_api.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
        log.info(f"Created pod {pod_name}")
        return {"message": f"Pod '{pod_name}' created successfully."}
    except client.exceptions.ApiException as e:
        log.error("K8s create pod error: %s", e)
        return {"error": str(e)}


@app.get("/get_list_of_pods")
def get_list_of_pods():
    pods = k8s_api.list_namespaced_pod(namespace=NAMESPACE, label_selector="app=user-pod")
    out = []
    for pod in pods.items:
        out.append({
            "pod_name": pod.metadata.name,
            "user_id": pod.metadata.labels.get("user-id"),
            "status": pod.status.phase,
            "pod_ip": pod.status.pod_ip,
        })
    log.info("Listing pods: %d", len(out))
    return out


@app.get("/get_pod_details/{id}")
def get_pod_details(id: str):
    pod_name = f"user-session-{id}"
    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {"pod_name": pod.metadata.name, "status": pod.status.phase, "pod_ip": pod.status.pod_ip}
    except client.exceptions.ApiException as e:
        log.error("Error getting pod details: %s", e)
        return {"error": str(e)}


async def _bridge_ws(ws_from, ws_to, direction: str):
    """
    Bridge binary / text frames from ws_from to ws_to.
    ws_from: FastAPI WebSocket (browser) or websockets client
    ws_to: opposite endpoint
    direction: debug label
    """
    try:
        while True:
            # try binary first
            try:
                data = await ws_from.receive_bytes()
                await ws_to.send(data)
                log.debug("Bridged %d bytes %s", len(data), direction)
            except Exception:
                # maybe text
                try:
                    text = await ws_from.receive_text()
                    await ws_to.send(text)
                    log.debug("Bridged text %s", direction)
                except Exception:
                    # If neither works, break
                    break
    except Exception as e:
        log.info("_bridge_ws exception (%s): %s", direction, e)


@app.websocket("/proxy/{id}")
async def websocket_proxy(websocket: WebSocket, id: str):
    await websocket.accept()
    pod_name = f"user-session-{id}"
    log.info("Incoming WS from browser for pod %s", pod_name)

    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        pod_ip = pod.status.pod_ip
    except Exception as e:
        log.error("Failed to read pod %s: %s", pod_name, e)
        await websocket.send_text(f"Error: pod not found: {str(e)}")
        await websocket.close()
        return

    if not pod_ip:
        await websocket.send_text("Pod not ready (no IP)")
        await websocket.close()
        return

    target_ws_url = f"ws://{pod_ip}:5901"
    log.info("Proxying browser -> %s", target_ws_url)

    try:
        # connect from stateless pod to stateful pod's websocket
        async with websockets.connect(target_ws_url) as pod_ws:
            log.info("Connected to pod websocket %s", target_ws_url)

            # create tasks bridging both directions
            async def b_to_p():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await pod_ws.send(data)
                except WebSocketDisconnect:
                    log.info("Browser disconnected")
                except Exception as e:
                    log.info("b_to_p exception: %s", e)

            async def p_to_b():
                try:
                    while True:
                        data = await pod_ws.recv()
                        # websockets library returns bytes for binary frames, str for text
                        if isinstance(data, bytes):
                            await websocket.send_bytes(data)
                        else:
                            await websocket.send_text(data)
                except Exception as e:
                    log.info("p_to_b exception: %s", e)

            t1 = asyncio.create_task(b_to_p())
            t2 = asyncio.create_task(p_to_b())
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
    except Exception as e:
        log.error("Error connecting to pod websocket %s: %s", target_ws_url, e)
        try:
            await websocket.send_text(f"Error connecting to pod: {e}")
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass
        log.info("Closed proxy for pod %s", pod_name)
