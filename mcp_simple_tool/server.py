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

# 創建一個 MCP Sever 的實例
app = Server("mcp-website-fetcher")

# 非同步抓取網頁內容
async def fetch_website(url: str) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    headers = {
        "User-Agent": "MCP Test Server"
    }

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type:
                return [types.TextContent(type="text", text=response.text)]
            elif "image" in content_type:
                return [types.ImageContent(type="image", url=url)]
            elif "application/json" in content_type:
                return [types.EmbeddedResource(type="json", data=response.json())]
            else:
                return [types.TextContent(type="text", text="Unsupported content type.")]
        except httpx.HTTPStatusError as e:
            return [types.TextContent(type="text", text=f"HTTP Error: {e.response.status_code}")]
        except httpx.RequestError as e:
            return [types.TextContent(type="text", text=f"Request Error: {str(e)}")]

# 這是 MCP 工具調用（call_tool）介面
@app.call_tool()
async def fetch_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name != "fetch":
        raise ValueError(f"Unknown tool: {name}")
    if "url" not in arguments:
        raise ValueError("Missing required argument 'url'")
    return await fetch_website(arguments["url"])

# 這個函式回傳 MCP 伺服器可用的工具清單
@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fetch",
            description="Fetches a website and returns its content",
            inputSchema={
                "type": "object", # 資料格式為 JSON 物件
                "required": ["url"], # 需要一個 url 參數
                "properties": {
                    # 表示要獲取的網站 URL
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    }
                },
            },
        )
    ]

# 使用 Click 命令列工具來啟動 MCP 伺服器，並提供兩種通訊模式：
# 1. SSE (Server-Sent Events)
# 2. 標準輸入輸出 (Stdio)
@click.command()
@click.option("--port", default=5488, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="sse",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    # SSE (Server-Sent Events) 協議支援
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
    # 標準輸入輸出 (Stdio) 協議支援
    else:
        async def arun():
            async with stdio_server() as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        anyio.run(arun)

    return 0

