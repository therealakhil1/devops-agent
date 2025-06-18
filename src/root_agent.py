from google.adk.agents import Agent

from src.deployment_agent import deployment_agent

root_agent = Agent(
    name="root_agent",
    model="gemini-2.0-flash",
    description="""You are an expert DevOps engineer. You help the user to execute their devops tasks.
    Understand the user's request and properly invoke the sub-agents and tools to execute the task according to the
    following guidelines:
    1. If the user wants to deploy or rollback a branch, invoke the deployment agent.
    """,
    sub_agents=[deployment_agent],
    tools=[],
)

