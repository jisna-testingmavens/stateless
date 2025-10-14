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
    """
    Create a new pod and a dedicated LoadBalancer service for this user.
    """
    pod_name = f"user-session-{id}"
    service_name = f"user-service-{id}"

    # --- Pod definition ---
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
                "ports": [{"containerPort": 5901}]
            }]
        }
    }

    # --- Service definition (unique per user) ---
    service_manifest = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "labels": {
                "user-id": id
            }
        },
        "spec": {
            "selector": {
                "user-id": id
            },
            "ports": [{
                "protocol": "TCP",
                "port": 5901,
                "targetPort": 5901
            }],
            "type": "LoadBalancer"  # Change to NodePort if your cluster has no LB
        }
    }

    try:
        # Create Pod
        k8s_api.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
        # Create Service
        k8s_api.create_namespaced_service(namespace=NAMESPACE, body=service_manifest)

        return {
            "message": f"✅ Pod '{pod_name}' and Service '{service_name}' created successfully.",
            "pod_name": pod_name,
            "service_name": service_name
        }
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.get("/get_pod_details/{id}")
def get_pod_details(id: str):
    """
    Retrieve pod and service details for a given user ID.
    """
    pod_name = f"user-session-{id}"
    service_name = f"user-service-{id}"

    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        svc = k8s_api.read_namespaced_service(name=service_name, namespace=NAMESPACE)

        # Try to extract LoadBalancer IP or hostname
        external_ip = None
        if svc.status.load_balancer and svc.status.load_balancer.ingress:
            ingress = svc.status.load_balancer.ingress[0]
            external_ip = ingress.hostname or ingress.ip

        return {
            "pod_name": pod.metadata.name,
            "status": pod.status.phase,
            "pod_ip": pod.status.pod_ip,
            "service_name": service_name,
            "external_ip": external_ip,
            "labels": pod.metadata.labels
        }
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.get("/get_status/{id}")
def get_status(id: str):
    """
    Simple endpoint to check pod running status.
    """
    pod_name = f"user-session-{id}"
    try:
        pod = k8s_api.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        return {"status": pod.status.phase}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}


@app.delete("/delete_user_pod/{id}")
def delete_user_pod(id: str):
    """
    Delete both the user pod and its associated service.
    """
    pod_name = f"user-session-{id}"
    service_name = f"user-service-{id}"

    try:
        k8s_api.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        k8s_api.delete_namespaced_service(name=service_name, namespace=NAMESPACE)
        return {"message": f"🗑️ Pod '{pod_name}' and Service '{service_name}' deleted."}
    except client.exceptions.ApiException as e:
        return {"error": str(e)}
