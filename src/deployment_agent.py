from google.adk.agents import Agent
import tempfile
import subprocess
import shutil
import os
import yaml
from kubernetes import client, config
import time
from .runbook_agent import runbook_agent

class CheckoutException(Exception):
    pass

class DeploymentException(Exception):
    pass

class BuildException(Exception):
    pass

class RollbackException(Exception):
    pass

class MonitorException(Exception):
    pass

def clone_repository_to_temp_dir(repository_url: str):
    """
    Clone the repository to a temporary directory.
    Args:
        repository_url: The url of the repository to clone.
    Returns:
        The path to the temporary directory.
    """
    temp_dir = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "clone", repository_url], cwd=temp_dir, check=True)
    except Exception as e:
        shutil.rmtree(temp_dir)
    return os.path.join(temp_dir, "agenticaitraining")

def clean_up_temp_dir(temp_dir: str):
    """
    Clean up the temporary directory.
    Args:
        temp_dir: The path to the temporary directory.
    """
    shutil.rmtree(temp_dir)

def checkout_branch(branch_name: str):
    """
    Checkout the git branch.
    Args:
        branch_name: The name of the branch to checkout.
    """
    try:
        subprocess.run(["git", "checkout", branch_name], check=True)
    except Exception as e:
        raise CheckoutException(f'Failed to checkout to the branch {branch_name}.')


def deploy_branch(deployment_file: str, environment: str, branch_name: str):
    """
    Deploy the git branch to the local cluster using the Kubernetes Python client.
    Args:
        branch_name: The name of the branch to deploy.
        environment: The environment to deploy to.
    """
    try:
        config.load_kube_config()
        with open(deployment_file) as f:
            dep = yaml.safe_load(f)
        k8s_apps_v1 = client.AppsV1Api()
        namespace = environment
        # Create or replace deployment
        try:
            k8s_apps_v1.create_namespaced_deployment(
                body=dep, namespace=namespace
            )
        except client.exceptions.ApiException as e:
            if e.status == 409:  # Already exists, replace
                k8s_apps_v1.replace_namespaced_deployment(
                    name=dep['metadata']['name'],
                    namespace=namespace,
                    body=dep
                )
            else:
                raise
    except Exception as e:
        raise DeploymentException(f'Failed to deploy the branch {branch_name}: {e}')

def rollback_branch(deployment_file: str, branch_name: str, environment: str, deployment_name: str):
    """
    Rollback the git branch to the previous version using the Kubernetes Python client.
    Args:
        branch_name: The name of the branch to rollback.
        environment: The environment to rollback from.
    """
    try:
        config.load_kube_config()
        k8s_apps_v1 = client.AppsV1Api()
        namespace = environment
        # Rollout undo is not directly supported, so you may need to patch to previous revision if available
        # Here, we simply delete the deployment as a placeholder
        k8s_apps_v1.delete_namespaced_deployment(name=deployment_name, namespace=namespace)
    except Exception as e:
        raise RollbackException(f'Failed to rollback the branch {branch_name}: {e}')
    try:
        os.remove(deployment_file)
    except Exception as e:
        raise Exception(f'Failed to delete the deployment file for the branch {branch_name}.')

def monitor_deployment(branch_name: str, environment: str, deployment_name: str, timeout: int = 120, interval: int = 5):
    """
    Monitor the deployment of the git branch using the Kubernetes Python client.
    Args:
        branch_name: The name of the branch to monitor.
        environment: The environment to monitor.
    """
    try:
        config.load_kube_config()
        k8s_apps_v1 = client.AppsV1Api()
        namespace = environment
        start = time.time()
        while time.time() - start < timeout:
            resp = k8s_apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            status = resp.status
            if status.conditions:
                for cond in status.conditions:
                    if cond.type == "Available" and cond.status == "True":
                        return True
            time.sleep(interval)
        return False
    except Exception as e:
        raise MonitorException(f'Failed to monitor the deployment of the branch {branch_name}: {e}')

def build_docker_image(branch_name: str, temp_dir: str):
    try:
        subprocess.run(["docker", "build", "-t", f"akhilspalli/agenticaitraining-{branch_name}:latest", "."],cwd=f"{temp_dir}", check=True)
    except Exception as e:
        raise BuildException(f'Failed to build the docker image for the branch {branch_name}.')

def push_docker_image(branch_name: str):
    image_tag = f"akhilspalli/agenticaitraining-{branch_name}:latest"
    try:
        subprocess.run(["docker", "push", image_tag], check=True)
    except Exception as e:
        raise BuildException(f'Failed to push the docker image for the branch {branch_name}: {e}')

def create_deployment_file(deployment_content: str, branch_name: str, environment: str, deployment_name: str):
    """
    Create a deployment file for the docker image.
    Args:
        deployment_content: The content of the deployment file in yaml format, inputted by the agent.
        branch_name: The name of the branch to deploy.
        environment: The environment to deploy to.
        deployment_name: The name of the deployment.
    Returns:
        The string path to the deployment file and the name of the deployment.
    """
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    deployment_file = os.path.join(PROJECT_ROOT, f"deployments-{branch_name}-{environment}.yaml")
    with open(deployment_file, "w") as f:
        f.write(deployment_content)
    return str(deployment_file), deployment_name


deployment_agent = Agent(
    name="deployment_agent",
    model="gemini-2.0-flash",
    description="""You are an expert DevOps engineer. You help the user to deploy a git branch to a 
    local cluster running with kubectl.
    The repository is hosted on github and is called agenticaitraining. 
    The clone url is: https://github.com/therealakhil1/agenticaitraining.git

    You will be called by either the root_agent or the runbook_agent.
    If the root agent calls you, continue following the steps below. Otherwise skip the below steps and goto step 2.
    1. The user will provide the git branch name and the environment they wish to deploy to, they will also specify any specifications for the deployment. 
        You will need to:
        1. Create a temporary directory to clone the repository.
        2. Clone the repository.
        3. Checkout the git branch.
        4. Build the docker image.
        5. Push the docker image to the local registry.
        6. Write a deployment file for the docker image, the image name must follow the format "akhilspalli/agenticaitraining-{branch_name}:latest", use the create_deployment_file tool to create the deployment file.
        6. Deploy the docker image to the local cluster called "local-cluster" in the namespace "<environment>".
        7. Clean up the temporary directory.
        8. Monitor the deployment and report the status to the user. If the 
        9. If the deployment fails, invoke the runbook agent.
        10. If the deployment succeeds, report the status to the user.
    2. If the runbook agent calls you, follow the following steps:
        1. Deploy the available deployment file to the local cluster called "local-cluster" in the namespace "<environment>".
        2. Clean up the temporary directory.
        3. Monitor the deployment and report the status to the user. If the 
        4. If the deployment has failed 3 times already, tell the user that the deployment cannot be fixed and give them the summary of the failure.
        5. If the deployment fails, invoke the runbook agent.
        6. If the deployment succeeds, report the status to the user.

    If any error occurs, use the clean_up_temp_dir tool to clean up the temporary directory.

    Here are a few errors and how to handle them:-
    1. If a tool raises a CheckoutException, you should tell the user that the checkout failed and ask them to try again after creating the branch.
    """,
    tools=[clone_repository_to_temp_dir, clean_up_temp_dir, checkout_branch, deploy_branch, rollback_branch, monitor_deployment, build_docker_image, push_docker_image, create_deployment_file],
    sub_agents=[runbook_agent]
)

# deployment_agent = Agent(
#     name="deployment_agent",
#     model="gemini-2.0-flash",
#     description="""You are an expert DevOps engineer. You help the user to deploy a git branch to a 
#     local cluster running with kubectl.
#     The repository is hosted on github and is called agenticaitraining. 
#     The clone url is: https://github.com/therealakhil1/agenticaitraining.git

#     You will be called by either the root_agent or the runbook_agent.
#     If the root agent calls you, continue following the steps below. Otherwise skip the below steps and goto step 2.
#     1. The user will provide the git branch name and the environment they wish to deploy to, they will also specify any specifications for the deployment. 
#         You will need to:
#         1. Write a deployment file for the docker image, the image name must follow the format "akhilspalli/agenticaitraining-{branch_name}:latest", use the create_deployment_file tool to create the deployment file.
#         2. Deploy the docker image to the local cluster called "local-cluster" in the namespace "<environment>".
#         3. Clean up the temporary directory.
#         4. Monitor the deployment and report the status to the user. If the 
#         5. If the deployment fails, invoke the runbook agent.
#         6. If the deployment succeeds, report the status to the user.
#     2. If the runbook agent calls you, follow the following steps:
#         1. Deploy the available deployment file to the local cluster called "local-cluster" in the namespace "<environment>".
#         2. Clean up the temporary directory.
#         3. Monitor the deployment and report the status to the user. If the 
#         4. If the deployment has failed 3 times already, tell the user that the deployment cannot be fixed and give them the summary of the failure.
#         5. If the deployment fails, invoke the runbook agent.
#         6. If the deployment succeeds, report the status to the user.

#     If any error occurs, use the clean_up_temp_dir tool to clean up the temporary directory.

#     Here are a few errors and how to handle them:-
#     1. If a tool raises a CheckoutException, you should tell the user that the checkout failed and ask them to try again after creating the branch.
#     """,
#     tools=[clone_repository_to_temp_dir, clean_up_temp_dir, checkout_branch, deploy_branch, rollback_branch, monitor_deployment, build_docker_image, push_docker_image, create_deployment_file],
#     sub_agents=[runbook_agent]
# )