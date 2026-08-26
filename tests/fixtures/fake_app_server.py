import json
import os
import sys

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

thread_name = None
experimental_api = False
current_model = "gpt-5.6-sol"
current_effort = "high"
current_service_tier = None


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params", {})
    if method == "initialize":
        experimental_api = params.get("capabilities", {}).get("experimentalApi") is True
        send({"id": request_id, "result": {"userAgent": "fake"}})
    elif method == "initialized":
        pass
    elif method in {"thread/start", "thread/resume"}:
        thread_id = params.get("threadId", "thread-fake")
        send({"id": request_id, "result": {
            "thread": {"id": thread_id, "turns": [], "status": {"type": "idle"}},
            "model": current_model,
            "reasoningEffort": current_effort,
            "serviceTier": current_service_tier,
            "modelProvider": "openai",
        }})
    elif method == "model/list":
        send({"id": request_id, "result": {"data": [
            {
                "id": "gpt-5.6-sol", "model": "gpt-5.6-sol", "displayName": "GPT-5.6 Sol",
                "description": "Frontier coding model", "hidden": False, "isDefault": True,
                "defaultReasoningEffort": "high",
                "defaultServiceTier": None,
                "serviceTiers": [{"id": "fast", "name": "Fast", "description": "Lower latency"}],
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "medium", "description": "Balanced"},
                    {"reasoningEffort": "high", "description": "Deeper"},
                ],
            },
            {
                "id": "gpt-5.6-luna", "model": "gpt-5.6-luna", "displayName": "GPT-5.6 Luna",
                "description": "Fast coding model", "hidden": False, "isDefault": False,
                "defaultReasoningEffort": "medium",
                "defaultServiceTier": "priority",
                "serviceTiers": [{"id": "priority", "name": "Priority", "description": "Priority processing"}],
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "low", "description": "Fast"},
                    {"reasoningEffort": "medium", "description": "Balanced"},
                ],
            },
        ]}})
    elif method == "thread/settings/update":
        current_model = params.get("model", current_model)
        current_effort = params.get("effort", current_effort)
        if "serviceTier" in params:
            current_service_tier = params.get("serviceTier")
        send({"id": request_id, "result": {}})
        send({"method": "thread/settings/updated", "params": {
            "threadId": params.get("threadId"),
            "threadSettings": {
                "model": current_model, "effort": current_effort,
                "serviceTier": current_service_tier, "modelProvider": "openai",
            },
        }})
    elif method == "thread/read":
        thread_id = params.get("threadId", "thread-fake")
        send({"id": request_id, "result": {"thread": {
            "id": thread_id,
            "name": thread_name,
            "status": {"type": "idle"},
            "turns": [{"id": "turn-history", "status": "completed", "items": [{"id": "history-answer", "type": "agentMessage", "text": "history"}]}] if params.get("includeTurns") else [],
        }}})
    elif method == "thread/list":
        send({"id": request_id, "result": {
            "data": [{
                "id": "thread-fake",
                "sessionId": "thread-fake",
                "name": thread_name,
                "preview": "history",
                "cwd": os.getcwd(),
                "projectId": "project-fake",
                "parentThreadId": None,
                "ephemeral": False,
                "status": {"type": "idle"},
                "createdAt": 1,
                "updatedAt": 2,
            }],
            "nextCursor": None,
        }})
    elif method == "turn/start":
        if params.get("additionalContext") and not experimental_api:
            send({
                "id": request_id,
                "error": {
                    "code": -32600,
                    "message": "turn/start.additionalContext requires experimentalApi capability",
                },
            })
            continue
        send({"id": request_id, "result": {"turn": {"id": "turn-fake"}}})
        inputs = params.get("input", [])
        first_text = next((item.get("text") for item in inputs if item.get("type") == "text"), "")
        send({"method": "turn/started", "params": {"threadId": params.get("threadId"), "turn": {"id": "turn-fake", "status": "inProgress", "items": []}}})
        user_item = {"id": "user-fake", "type": "userMessage", "clientId": params.get("clientUserMessageId"), "content": inputs}
        send({"method": "item/started", "params": {"threadId": params.get("threadId"), "turnId": "turn-fake", "item": user_item}})
        send({"method": "item/completed", "params": {"threadId": params.get("threadId"), "turnId": "turn-fake", "item": user_item}})
        if first_text == "__echo_input__":
            answer = json.dumps(inputs, ensure_ascii=False)
        elif first_text == "__turn_params__":
            answer = json.dumps({key: params.get(key) for key in ("clientUserMessageId", "additionalContext")}, ensure_ascii=False)
        elif first_text == "__thread_name__":
            answer = thread_name or ""
        else:
            answer = "fake answer"
        if first_text == "__stream__":
            send({"method": "item/reasoning/summaryTextDelta", "params": {"threadId": params.get("threadId"), "turnId": "turn-fake", "itemId": "reasoning-fake", "summaryIndex": 0, "delta": "checking"}})
            send({"method": "item/agentMessage/delta", "params": {"threadId": params.get("threadId"), "turnId": "turn-fake", "itemId": "answer-fake", "delta": "fake "}})
            send({"method": "item/agentMessage/delta", "params": {"threadId": params.get("threadId"), "turnId": "turn-fake", "itemId": "answer-fake", "delta": "answer"}})
        send({"method": "item/completed", "params": {"threadId": params.get("threadId"), "turnId": "turn-fake", "item": {"id": "answer-fake", "type": "agentMessage", "text": answer}}})
        send({"method": "turn/completed", "params": {"threadId": params.get("threadId"), "turn": {"id": "turn-fake", "status": "completed"}}})
    elif method == "turn/interrupt":
        send({"id": request_id, "result": {}})
    elif method == "thread/archive":
        send({"id": request_id, "result": {}})
    elif method == "thread/name/set":
        thread_name = params.get("name")
        send({"id": request_id, "result": {}})
