import anyio
import click
import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.sse import Request
from starlette.applications import Starlette
from starlette.routing import Mount, Route
import uvicorn
from mcp.server.stdio import stdio_server

app = Server("mcp-website-fetcher")

async def fetch_website(url: str) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    headers = {
        "User-Agent": "MCP Test Server"
    }

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return [types.TextContent(type="text", text=response.text)]

@app.call_tool()
async def fetch_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name != "fetch":
        raise ValueError(f"Unknown tool: {name}")
    if "url" not in arguments:
        raise ValueError("Missing required argument 'url'")
    return await fetch_website(arguments["url"])

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fetch",
            description="Fetches a website and returns its content",
            inputSchema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    }
                },
            },
        )
    ]

@click.command()
@click.option("--port", default=5488, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="sse",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    if transport == "sse":
        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message)
            ],
        )

        uvicorn.run(starlette_app, host="0.0.0.0", port=port)
    else:
        async def arun():
            async with stdio_server() as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        anyio.run(arun)

    return 0

