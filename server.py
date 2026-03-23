"""
Sovereign Mind Gemini MCP Server v1.1
=====================================
Uses Google Cloud Vertex AI with service account authentication.
"""

import os
import json
import httpx
import time
import uuid
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Handle Google credentials from env var BEFORE Flask app starts
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
if GOOGLE_CREDENTIALS_JSON:
    creds_path = "/tmp/gcloud-creds.json"
    try:
        with open(creds_path, "w") as f:
            f.write(GOOGLE_CREDENTIALS_JSON)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        logger.info(f"Wrote Google credentials to {creds_path}")
    except Exception as e:
        logger.error(f"Failed to write credentials: {e}")

app = Flask(__name__)
CORS(app)

GOOGLE_PROJECT_ID = os.environ.get("GOOGLE_PROJECT_ID", "innate-concept-481918-h9")
GOOGLE_LOCATION = os.environ.get("GOOGLE_LOCATION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
SM_GATEWAY_URL = os.environ.get("SM_GATEWAY_URL", "https://sm-mcp-gateway.lemoncoast-87756bcf.eastus.azurecontainerapps.io")

SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "jga82554.east-us-2.azure")
SNOWFLAKE_USER = os.environ.get("SNOWFLAKE_USER", "AZURE_WEST")
SNOWFLAKE_PASSWORD = os.environ.get("SNOWFLAKE_PASSWORD", "")
SNOWFLAKE_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "SOVEREIGN_MIND")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "SOVEREIGN_MIND_WH")

_snowflake_conn = None
_vertexai_initialized = False

SOVEREIGN_MIND_SYSTEM_PROMPT = """# SOVEREIGN MIND - AI INSTANCE CONFIGURATION

## Identity
You are **GEMINI**, an AI instance within **Sovereign Mind**, the second-brain system for Your Grace, Chairman of MiddleGround Capital (private equity) and Resolute Holdings (racing, bloodstock, operations).

## Your Instance Details
- Instance Name: GEMINI
- Platform: Google AI (Vertex AI)
- Role: General/Analysis  
- Specialization: Document analysis, long-context work, reasoning

## Core Data Architecture
### HIVE_MIND (Shared Memory)
Location: SOVEREIGN_MIND.RAW.HIVE_MIND - Cross-AI continuity and context sharing

## Core Behaviors
1. **Execute, Don't Ask**: Use available tools. The Hive Mind knows context.
2. **Log Everything**: INSERT to HIVE_MIND after meaningful work.
3. **Escalate Intelligently**: Ask another AI before asking Your Grace.
4. **Token Efficiency**: Brief confirmations, limit SQL to 5 rows.
5. **Continuity First**: When user says "continue", query Hive Mind immediately.
6. **Address as "Your Grace"**: Per user preference.
7. **No permission seeking**: "I've done X" not "Would you like me to?"
"""


def init_vertexai():
    global _vertexai_initialized
    if not _vertexai_initialized:
        try:
            import vertexai
            vertexai.init(project=GOOGLE_PROJECT_ID, location=GOOGLE_LOCATION)
            _vertexai_initialized = True
            logger.info(f"Vertex AI initialized: {GOOGLE_PROJECT_ID}")
        except Exception as e:
            logger.error(f"Vertex AI init failed: {e}")


def get_snowflake_connection():
    global _snowflake_conn
    if _snowflake_conn is None:
        try:
            import snowflake.connector
            _snowflake_conn = snowflake.connector.connect(
                account=SNOWFLAKE_ACCOUNT, user=SNOWFLAKE_USER, password=SNOWFLAKE_PASSWORD,
                database=SNOWFLAKE_DATABASE, warehouse=SNOWFLAKE_WAREHOUSE
            )
            logger.info("Snowflake connected")
        except Exception as e:
            logger.error(f"Snowflake failed: {e}")
            return None
    return _snowflake_conn


def query_hive_mind(limit=5):
    conn = get_snowflake_connection()
    if not conn: return "Hive Mind unavailable"
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT CREATED_AT, SOURCE, CATEGORY, SUMMARY FROM SOVEREIGN_MIND.RAW.HIVE_MIND ORDER BY CREATED_AT DESC LIMIT {limit}")
        rows = cursor.fetchall()
        return "\n".join([f"[{r[0]}] {r[1]} ({r[2]}): {r[3]}" for r in rows]) if rows else "No recent entries"
    except Exception as e:
        return f"Query failed: {e}"


def write_to_hive_mind(source, category, summary, workstream="GENERAL", priority="MEDIUM"):
    conn = get_snowflake_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        safe_summary = summary.replace("'", "''")[:2000]
        cursor.execute(f"INSERT INTO SOVEREIGN_MIND.RAW.HIVE_MIND (SOURCE, CATEGORY, WORKSTREAM, SUMMARY, PRIORITY, CREATED_AT) VALUES ('{source}', '{category}', '{workstream}', '{safe_summary}', '{priority}', CURRENT_TIMESTAMP())")
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Write failed: {e}")
        return False


def extract_message(args):
    """Extract message from args, handling both 'message' (string) and 'messages' (array) formats."""
    msg = args.get("message", "")
    if msg:
        return msg
    msg = args.get("prompt", "")
    if msg:
        return msg
    messages = args.get("messages", [])
    if isinstance(messages, list) and len(messages) > 0:
        parts = []
        for m in messages:
            if isinstance(m, str):
                parts.append(m)
            elif isinstance(m, dict):
                parts.append(m.get("content", m.get("text", str(m))))
        return "\n".join(parts)
    return ""


def call_gemini(message, system_prompt):
    init_vertexai()
    try:
        from vertexai.generative_models import GenerativeModel
        model = GenerativeModel(GEMINI_MODEL, system_instruction=system_prompt)
        response = model.generate_content(message)
        return response.text
    except Exception as e:
        return f"Error: {e}"


@app.route("/", methods=["GET"])
def index():
    conn = get_snowflake_connection()
    return jsonify({
        "service": "gemini-mcp", "version": "1.1.0", "status": "healthy",
        "instance": "GEMINI", "platform": "Google AI (Vertex AI)", "model": GEMINI_MODEL,
        "sovereign_mind": True, "hive_mind_connected": conn is not None,
        "features": ["sovereign_mind_prompt", "hive_mind_context", "vertex_ai", "cors_enabled"]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "sovereign_mind": True})


@app.route("/mcp", methods=["POST", "OPTIONS"])
def mcp_endpoint():
    if request.method == "OPTIONS": return "", 200
    data = request.json
    method, params, req_id = data.get("method", ""), data.get("params", {}), data.get("id", 1)
    
    if method == "tools/list":
        tools = [
            {"name": "gemini_generate_content", "description": "Generate content with Gemini (Sovereign Mind)", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}},
            {"name": "gemini_chat", "description": "Chat with Gemini", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}, "messages": {"type": "array", "description": "Chat messages array (alternative to message)"}}}},
            {"name": "sm_hive_mind_read", "description": "Read Hive Mind", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
            {"name": "sm_hive_mind_write", "description": "Write to Hive Mind", "inputSchema": {"type": "object", "properties": {"category": {"type": "string"}, "summary": {"type": "string"}}, "required": ["category", "summary"]}}
        ]
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})
    
    elif method == "tools/call":
        tool, args = params.get("name", ""), params.get("arguments", {})
        
        if tool in ["gemini_generate_content", "gemini_chat"]:
            msg = extract_message(args)
            if not msg:
                return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "Error: No message provided. Use 'message' (string) or 'messages' (array) or 'prompt' (string)."}], "isError": True}})
            hive_context = query_hive_mind(3)
            system = f"{SOVEREIGN_MIND_SYSTEM_PROMPT}\n\n# HIVE MIND CONTEXT\n{hive_context}"
            response = call_gemini(msg, system)
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps({"response": response})}]}})
        
        elif tool == "sm_hive_mind_read":
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": query_hive_mind(args.get("limit", 5))}]}})
        
        elif tool == "sm_hive_mind_write":
            ok = write_to_hive_mind("GEMINI", args.get("category", "INSIGHT"), args.get("summary", ""))
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "Written" if ok else "Failed"}]}})
    
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Not found"}})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Gemini MCP (Sovereign Mind) on port {port}")
    app.run(host="0.0.0.0", port=port)
