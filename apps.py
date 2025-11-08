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
    filter_ = body.get("filter")
    sorts = body.get("sorts")
    page_size = body.get("page_size", 50)
    res = notion.databases.query(database_id=database_id, filter=filter_, sorts=sorts, page_size=page_size)
    return {"results": res.get("results", [])}

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
        # Update
        res = notion.pages.update(page_id=page_id, properties=properties)
        if children:
            notion.blocks.children.append(block_id=page_id, children=children)
        return res
    else:
        # Create
        res = notion.pages.create(parent={"database_id": database_id}, properties=properties, children=children)
        return res

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

#@app.post("/notion/weekly-summary")
#def weekly_summary(body: Dict[str, Any], x_api_key: Optional[str] = Header(None)):
#"""
#Reads last N days of entries from Research Journals DB,
#asks GPT to synthesize, writes a new page into Meeting Notes DB.
#body: { journal_db_id, notes_db_id, days=7, title="Weekly Research Summary" }
#"""
#require_key(x_api_key)
#if not notion:
#    raise HTTPException(500, "Server missing NOTION_TOKEN")
#if not client:
#    raise HTTPException(500, "Server missing OPENAI_API_KEY")

    journal_db_id = body.get("journal_db_id")
    notes_db_id = body.get("notes_db_id")
    days = int(body.get("days", 7))
    title = body.get("title", "Weekly Research Summary")

    if not journal_db_id or not notes_db_id:
        raise HTTPException(400, "journal_db_id and notes_db_id required")

    after_iso = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()+"Z"
    q = notion.databases.query(
        database_id=journal_db_id,
        filter={"timestamp": "last_edited_time", "last_edited_time": {"after": after_iso}},
        page_size=100
    )
    entries = []
    for r in q.get("results", []):
        props = r.get("properties", {})
        # Try to pull a generic text field named 'Content' or 'Notes' or 'Summary'
        text_candidates = ["Content", "Notes", "Summary", "Description"]
        text = ""
        for c in text_candidates:
            if c in props and props[c]["type"] == "rich_text" and props[c]["rich_text"]:
                text = " ".join([t["plain_text"] for t in props[c]["rich_text"]])
                break
        # Also pull title if present
        title_field = next((k for k,v in props.items() if v["type"]=="title"), None)
        name = ""
        if title_field:
            ts = props[title_field]["title"]
            if ts:
                name = ts[0]["plain_text"]
        entries.append(f"• {name}: {text}")

    corpus = "\n".join(entries) if entries else "No entries found."

    prompt = f"""You are the Behavioural Econ Research GPT.
Summarize these journal entries from the last {days} days into:

1) A Notion-ready table:
Phase | Goal | Progress % | Blockers | Decisions | Next Steps | Owner

2) A narrative summary (5–8 sentences)

3) An Action Matrix:
Person | Task | Deadline | Notes

Entries:
{corpus}
"""
    completion = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": "You are a research director and project manager. Output concise, structured text."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    summary_text = completion.choices[0].message.content

    # Create a page in Meeting Notes DB
    # Assume the DB has a title property (any name). We'll detect it.
    schema = notion.databases.retrieve(database_id=notes_db_id)
    title_prop = next((k for k,v in schema["properties"].items() if v["type"]=="title"), None)
    if not title_prop:
        raise HTTPException(500, "Meeting Notes DB needs a title property")

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    properties = {
        title_prop: {"title": [{"type": "text", "text": {"content": f"{title} – {today}"}}]}
    }
    # Append the summary as a paragraph block
    children = [{
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary_text}}]}
    }]

    page = notion.pages.create(parent={"database_id": notes_db_id}, properties=properties, children=children)
    return {"created": page.get("id")}