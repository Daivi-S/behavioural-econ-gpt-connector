import os, datetime
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
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

# Pydantic models with extra="allow" to accept additional fields
class QueryDatabaseBody(BaseModel):
    database_id: str
    filter: Optional[Dict[str, Any]] = None
    sorts: Optional[list] = None
    page_size: int = 50
    
    class Config:
        extra = "allow"

class UpsertItemBody(BaseModel):
    database_id: str
    page_id: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    children: Optional[list] = None
    
    class Config:
        extra = "allow"

class AppendBlocksBody(BaseModel):
    page_id: str
    blocks: list = Field(default_factory=list)
    
    class Config:
        extra = "allow"

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/notion/query-database")
def query_database(body: QueryDatabaseBody, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    if not notion:
        raise HTTPException(500, "Server missing NOTION_TOKEN")
    
    query_params = {"database_id": body.database_id}
    
    if body.filter is not None:
        query_params["filter"] = body.filter
    
    if body.sorts is not None:
        query_params["sorts"] = body.sorts
    
    query_params["page_size"] = body.page_size
    
    res = notion.databases.query(**query_params)
    
    return {
        "object": res.get("object", "list"),
        "results": res.get("results", []),
        "has_more": res.get("has_more", False),
        "next_cursor": res.get("next_cursor")
    }

@app.post("/notion/upsert-database-item")
def upsert_item(body: UpsertItemBody, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    if not notion:
        raise HTTPException(500, "Server missing NOTION_TOKEN")
    
    database_id = body.database_id
    page_id = body.page_id
    properties = body.properties
    children = body.children

    if page_id:
        res = notion.pages.update(page_id=page_id, properties=properties)
        if children:
            notion.blocks.children.append(block_id=page_id, children=children)
    else:
        create_params = {
            "parent": {"database_id": database_id},
            "properties": properties
        }
        
        if children is not None:
            create_params["children"] = children
        
        res = notion.pages.create(**create_params)
    
    # Return ONLY the fields defined in schema - nothing extra
    return {
        "success": True,
        "id": res.get("id"),
        "url": res.get("url")
    }

@app.post("/notion/append-blocks")
def append_blocks(body: AppendBlocksBody, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    if not notion:
        raise HTTPException(500, "Server missing NOTION_TOKEN")
    
    page_id = body.page_id
    blocks = body.blocks
    
    if not page_id or not blocks:
        raise HTTPException(400, "page_id and blocks required")
    
    res = notion.blocks.children.append(block_id=page_id, children=blocks)
    return res

    