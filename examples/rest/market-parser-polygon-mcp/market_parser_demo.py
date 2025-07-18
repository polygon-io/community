import os
import asyncio
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from pydantic_ai import Agent
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
    console.print("------------------\n")

async def cli_async():
    print("Welcome to the Market Parser CLI. Type 'exit' to quit.")
    try:
        server = create_polygon_mcp_server()
        agent = Agent(model="anthropic:claude-4-sonnet-20250514", mcp_servers=[server])
        async with agent.run_mcp_servers():
            while True:
                try:
                    user_input = input('> ').strip()
                    if user_input.lower() == 'exit':
                        print("Goodbye!")
                        break
                    try:
                        response = await agent.run(user_input)
                        print("\r", end="")
                        print_agent_response(response)
                    except Exception as agent_err:
                        print("\r", end="")
                        raise Exception(agent_err)
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