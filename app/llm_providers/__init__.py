"""Per-provider LLM clients. All implement the same interface:

    stream_completion(model, system, messages, tools, on_chunk) -> dict

Returns either {"type":"final","text":...} or
{"type":"tool_use","text":...,"tool_calls":[...]}
"""
