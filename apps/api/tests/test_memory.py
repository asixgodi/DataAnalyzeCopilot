from app.services.memory import (
    SessionMemory,
    build_context,
    get_instruction,
    get_memory,
    resolve_followup,
    update_memory,
)


class TestGetMemory:
    def test_get_memory_returns_session_memory(self):
        memory = get_memory("test_session_1")
        assert isinstance(memory, SessionMemory)

    def test_same_session_id_returns_same_object(self):
        session_id = "test_session_2"
        memory1 = get_memory(session_id)
        memory2 = get_memory(session_id)
        assert memory1 is memory2

    def test_different_session_ids_return_different_objects(self):
        memory1 = get_memory("test_session_3")
        memory2 = get_memory("test_session_4")
        assert memory1 is not memory2

    def test_new_memory_has_default_user_profile(self):
        memory = get_memory("test_session_5")
        assert memory.user_profile["role"] == "after_sales_operator"
        assert "focus" in memory.user_profile
        assert memory.recent_turns == []
        assert memory.conversation_summary == ""

    def test_new_memory_has_default_profile_fields(self):
        memory = get_memory("test_session_6")
        for key in ("role", "focus", "preferred_categories", "preferred_metrics", "interaction_count"):
            assert key in memory.user_profile, f"Missing profile key: {key}"


class TestResolveFollowup:
    def test_no_previous_turns_returns_original_message(self):
        memory = SessionMemory()
        result = resolve_followup("4月服装类退款率是多少？", memory)
        assert result == "4月服装类退款率是多少？"

    def test_non_followup_returns_unchanged(self):
        memory = SessionMemory()
        memory.recent_turns.append({
            "user": "4月服装类退款率是多少？",
            "assistant": "服装类退款率为16.77%。",
        })
        # "查询5月数码类退款率" — 没有追问标记词，完整独立问题
        result = resolve_followup("查询5月数码类退款率", memory)
        assert result == "查询5月数码类退款率"

    def test_followup_injects_previous_context(self):
        memory = SessionMemory()
        memory.recent_turns.append({
            "user": "4月服装类退款率是多少？",
            "assistant": "服装类退款率为16.77%。",
        })
        # "呢" 触发追问 → 应注入上一轮上下文
        result = resolve_followup("5月情况呢？", memory)
        assert "上一轮问题" in result
        assert "4月服装类退款率是多少？" in result
        assert "5月情况呢？" in result

    def test_followup_with_shoe_switches_category(self):
        memory = SessionMemory()
        memory.recent_turns.append({
            "user": "4月服装类退款率是多少？",
            "assistant": "服装类退款率为16.77%。",
        })
        result = resolve_followup("那鞋靴呢？", memory)
        assert "鞋靴" in result
        assert "4月服装类退款率是多少？" in result


class TestUpdateMemory:
    def test_update_memory_appends_recent_turn(self):
        memory = SessionMemory()
        update_memory(memory, "问题1", "答案1")
        assert len(memory.recent_turns) == 1
        assert memory.recent_turns[0] == {"user": "问题1", "assistant": "答案1"}

    def test_update_memory_keeps_last_10_turns(self):
        memory = SessionMemory()
        for i in range(15):
            update_memory(memory, f"问题{i}", f"答案{i}")
        # 新系统保留最近 10 轮（原 6 轮升级为 10 轮）
        assert len(memory.recent_turns) == 10
        assert memory.recent_turns[0]["user"] == "问题5"
        assert memory.recent_turns[-1]["user"] == "问题14"

    def test_summary_triggers_after_6_turns(self):
        memory = SessionMemory()
        for i in range(5):
            update_memory(memory, f"Q{i}", f"A{i}")
        assert memory._dirty_summary is False
        update_memory(memory, "Q5", "A5")
        # 第 6 轮标记为脏，摘要可能已被 LLM 或规则回退更新
        assert memory._dirty_summary is False  # 同步触发后清除
        # 摘要应有内容（LLM 或规则回退都会填充）
        assert len(memory.conversation_summary) > 0

    def test_assistant_answer_truncated_to_300_chars(self):
        memory = SessionMemory()
        long_answer = "A" * 500
        update_memory(memory, "Q", long_answer)
        assert len(memory.recent_turns[0]["assistant"]) == 300


class TestInstructionMemory:
    def test_get_instruction_returns_non_empty(self):
        instruction = get_instruction()
        assert len(instruction) > 0
        assert "电商售后数据分析助手" in instruction

    def test_get_instruction_includes_guidelines(self):
        instruction = get_instruction()
        assert "回答要求" in instruction
        assert "数据结论" in instruction


class TestBuildContext:
    def test_build_context_always_includes_instruction(self):
        memory = SessionMemory()
        ctx = build_context(memory)
        # 指令记忆始终注入，即使没有任何对话历史
        assert "电商售后数据分析助手" in ctx["system_prompt"]
        assert len(ctx["system_prompt"]) > 0
        assert len(ctx["business_instructions"]) > 0

    def test_build_context_with_summary(self):
        memory = SessionMemory()
        memory.conversation_summary = "测试摘要内容"
        ctx = build_context(memory)
        assert "测试摘要内容" in ctx["summary_text"]

    def test_build_context_with_profile(self):
        memory = SessionMemory()
        memory.user_profile["preferred_categories"] = "服装"
        memory.user_profile["preferred_metrics"] = "退款率"
        ctx = build_context(memory)
        assert "服装" in ctx["user_profile_text"]
        assert "退款率" in ctx["user_profile_text"]

    def test_build_context_returns_prompt_context_type(self):
        memory = SessionMemory()
        ctx = build_context(memory)
        for key in ("system_prompt", "business_instructions", "user_profile_text", "summary_text", "recent_turns"):
            assert key in ctx, f"Missing key: {key}"
