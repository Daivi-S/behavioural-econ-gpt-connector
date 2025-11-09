import os, datetime
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Header, HTTPException
from typing import Optional, Any, Dict
from notion_client import Client as Notion
from openai import OpenAI

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
ACTIONS_API_KEY = os.getenv("ACTIONS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not NOTION_TOKEN:
    print("WARNING: NOTION_TOKEN not set yet")
notion = Notion(auth=NOTION_TOKEN) if NOTION_TOKEN else None
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

app = FastAPI(title="CUBS Notion Connector")

def require_key(x_api_key: Optional[str]):
    if not ACTIONS_API_KEY:
        return
    if x_api_key != ACTIONS_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/notion/query-database")
def query_database(body: Dict[str, Any], x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    if not notion:
        raise HTTPException(500, "Server missing NOTION_TOKEN")
    database_id = body.get("database_id")
    if not database_id:
        raise HTTPException(400, "database_id required")
    
    # Build query parameters, only including what's provided
    query_params = {"database_id": database_id}
    
    if "filter" in body and body["filter"] is not None:
        query_params["filter"] = body["filter"]
    
    if "sorts" in body and body["sorts"] is not None:
        query_params["sorts"] = body["sorts"]
    
    if "page_size" in body:
        query_params["page_size"] = body["page_size"]
    else:
        query_params["page_size"] = 50
    
    res = notion.databases.query(**query_params)
    
    # Return full response to match OpenAPI schema
    return {
        "object": res.get("object", "list"),
        "results": res.get("results", []),
        "has_more": res.get("has_more", False),
        "next_cursor": res.get("next_cursor")
    }

@app.post("/notion/upsert-database-item")
def upsert_item(body: Dict[str, Any], x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    if not notion:
        raise HTTPException(500, "Server missing NOTION_TOKEN")
    
    database_id = body.get("database_id")
    page_id = body.get("page_id")
    properties = body.get("properties", {})
    children = body.get("children")

    if page_id:
        # Update existing page
        res = notion.pages.update(page_id=page_id, properties=properties)
        if children:
            notion.blocks.children.append(block_id=page_id, children=children)
    else:
        # Create new page
        create_params = {
            "parent": {"database_id": database_id},
            "properties": properties
        }
        
        if children is not None:
            create_params["children"] = children
        
        res = notion.pages.create(**create_params)
    
    # Return response matching OpenAPI schema
    return {
        "object": res.get("object"),
        "id": res.get("id"),
        "url": res.get("url"),
        "archived": res.get("archived", False),
        "properties": res.get("properties", {})
    }

@app.post("/notion/append-blocks")
def append_blocks(body: Dict[str, Any], x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    if not notion:
        raise HTTPException(500, "Server missing NOTION_TOKEN")
    page_id = body.get("page_id")
    blocks = body.get("blocks", [])
    if not page_id or not blocks:
        raise HTTPException(400, "page_id and blocks required")
    res = notion.blocks.children.append(block_id=page_id, children=blocks)
    return res