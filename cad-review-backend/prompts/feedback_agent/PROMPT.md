请你判断这条误报反馈线程。
必须只返回 JSON 对象，不要 markdown，不要解释，不要代码块。
JSON 字段固定为：
{"status":"resolved_incorrect|resolved_not_incorrect|agent_needs_user_input|escalated_to_human","user_reply":"","summary":"","confidence":0.0,"reason_codes":[""],"needs_learning_gate":false,"suggested_learning_decision":"pending|accepted_for_learning|rejected_for_learning|record_only|needs_human_review","follow_up_question":null,"evidence_gaps":[""]}
补充约束：
- 如果 status=agent_needs_user_input，follow_up_question 必须有值，而且只问一个关键问题。
- 如果是项目私有别名/单项目特例，更适合 suggested_learning_decision=record_only。
- confidence 范围是 0 到 1。
- user_reply 必须是给用户看的自然语言。
上下文如下：
{{payload_json}}
