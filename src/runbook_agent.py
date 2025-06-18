from google.adk.agents import Agent
import os

def get_runbook(failure_summary: str):
    """
    Get the runbook for the failure.
    """
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    runbook_path = os.path.join(PROJECT_ROOT, "runbooks", "image_pull_error.json")
    with open(runbook_path, "r") as f:
        return f.read()

runbook_agent = Agent(
    name="runbook_agent",
    model="gemini-2.0-flash",
    description="""You are a kubernetes expert and an expert at debugging kubernetes deployments and 
    executing runbooks to fix the deployment.
    You need to do the following:
    1. Understand the kubernetes deployment failure.
    2. Summarize the failure in a concise manner, do not include any other information, do not hallucinate,
    only draw conclusions from the error message.
    3. Use the get_runbook tool to get the runbook for the failure.
    4. Follow the runbook step by step to fix the deployment.
    5. If the deployment is now fixed, report the status to the user.
    6. If the deployment is still failing, tell the deployment agent that the deployment is still failing and ask them to try again.
    """,
    tools=[get_runbook],
)