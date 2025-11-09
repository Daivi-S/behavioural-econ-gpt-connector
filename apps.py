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