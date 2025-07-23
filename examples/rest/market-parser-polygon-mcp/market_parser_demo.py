import os
import asyncio
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStdio

load_dotenv()

# ------------- MCP Server Factory -------------
def create_polygon_mcp_server():
    polygon_api_key = os.getenv("POLYGON_API_KEY")
    if not polygon_api_key:
      raise Exception("POLYGON_API_KEY is not set in the environment or .env file.")
    env = os.environ.copy()
    env["POLYGON_API_KEY"] = polygon_api_key
    return MCPServerStdio(
        command="uvx",
        args=[
            "--from",
            "git+https://github.com/polygon-io/mcp_polygon@v0.1.0",
            "mcp_polygon"
        ],
        env=env
    )

# ------------- CLI Logic -------------
console = Console()

def print_agent_response(response):
    console.print("\n[bold green]✔ Query processed successfully![/bold green]")
    console.print("[bold]Agent Response:[/bold]")
    output = getattr(response, "output", None)
    if output is not None:
        # Try to render as Markdown if it looks like Markdown
        if any(tag in output for tag in ["#", "*", "`", "-", ">"]):
            console.print(Markdown(output))
        else:
            console.print(output.strip())
    elif isinstance(response, str):
        console.print(response.strip())
    else:
        console.print(str(response))
    console.print("---------------------\n")

def print_agent_error(error):
    console.print("\n[bold red]!!! Error !!![/bold red]")
    if isinstance(error, Exception):
        console.print(str(error).strip())
    elif isinstance(error, dict):
        import json
        console.print(json.dumps(error, indent=2))
    else:
        console.print(str(error).strip())
    console.print("------------------\n")

def print_tools_used(response):
    tools = set()
    for msg in response.all_messages():
        if hasattr(msg, "parts"):
            for part in msg.parts:
                if hasattr(part, "tool_name"):
                    tools.add(part.tool_name)
    if tools:
        print("Tools used in this run:", ", ".join(tools))
    else:
        print("No tools used in this run.")

async def cli_async():
    print("Welcome to the Market Parser CLI. Type 'exit' to quit.")
    try:
        server = create_polygon_mcp_server()
        agent = Agent(
            model="anthropic:claude-4-sonnet-20250514",
            mcp_servers=[server],
            system_prompt=(
                "You are an expert financial analyst. Note that when using Polygon tools, prices are already stock split adjusted. "
                "Use the latest data available. Always double check your math. "
                "For any questions about the current date, use the 'get_today_date' tool. "
                "For long or complex queries, break the query into logical subtasks and process each subtask in order."
            )
        )

        # Add a custom tool to provide today's date
        from datetime import date
        @agent.tool
        def get_today_date(ctx: RunContext) -> str:
            """Returns today's date in YYYY-MM-DD format."""
            return str(date.today())


        async with agent.run_mcp_servers():
            message_history = []
            while True:
                try:
                    user_input = input('> ').strip()
                    if user_input.lower() == 'exit':
                        print("Goodbye!")
                        break
                    try:
                        # Run the agent with the current message history
                        response = await agent.run(
                            user_input,
                            message_history=message_history
                        )
                        print("\r", end="")
                        print_agent_response(response)
                        print_tools_used(response)
                        # Use the agent's own message objects for the next run
                        message_history = response.all_messages()
                    except Exception as agent_err:
                        print("\r", end="")
                        print_agent_error(agent_err)
                except (EOFError, KeyboardInterrupt):
                    print("\nGoodbye!")
                    break
                except Exception as e:
                    print_agent_error(e)
    except Exception as setup_err:
        print(f"Failed to start CLI agent or MCP server: {setup_err}")

def main():
    asyncio.run(cli_async())

if __name__ == "__main__":
    main() 