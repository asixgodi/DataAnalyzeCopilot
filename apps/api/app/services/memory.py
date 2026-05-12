from dataclasses import dataclass, field


@dataclass
class SessionMemory:
    recent_turns: list[dict[str, str]] = field(default_factory=list)
    conversation_summary: str = ""
    user_profile: dict[str, str] = field(default_factory=dict)


_STORE: dict[str, SessionMemory] = {}


def get_memory(session_id: str) -> SessionMemory:
    if session_id not in _STORE:
        _STORE[session_id] = SessionMemory(
            user_profile={"role": "after_sales_operator", "focus": "refund rate and ticket reasons"}
        )
    return _STORE[session_id]


def resolve_followup(message: str, memory: SessionMemory) -> str:
    followup_markers = ["那", "这个", "这两个", "对比", "呢"]
    if not memory.recent_turns or not any(marker in message for marker in followup_markers):
        return message
    previous = memory.recent_turns[-1]["user"]
    if "鞋" in message or "鞋靴" in message:
        return f"{previous}。继续追问：把类目换成鞋靴，{message}"
    return f"{previous}。继续追问：{message}"


def update_memory(memory: SessionMemory, user_message: str, assistant_answer: str) -> None:
    memory.recent_turns.append({"user": user_message, "assistant": assistant_answer[:300]})
    memory.recent_turns = memory.recent_turns[-6:]
    if len(memory.recent_turns) >= 3:
        latest_topics = [turn["user"] for turn in memory.recent_turns[-3:]]
        memory.conversation_summary = "；".join(latest_topics)
