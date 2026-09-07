"""Workspaces 共享后端 — 配置校验与保存（screen/lab 复用）。"""

import json


def parse_naming_rules(s: str) -> dict:
    return json.loads(s) if s.strip() else {}


def parse_table_schema(s: str) -> list:
    if not s.strip():
        return []
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("表结构必须是数组")
    for col in data:
        if "name" not in col:
            raise ValueError(f"表结构列缺少 name: {col}")
    return data


def parse_json_or(s: str, default):
    return json.loads(s) if s.strip() else default


def save_config(
    config_mgr, profile: str, root: str, from_path: str, to_path: str,
    rules_str: str, schema_str: str, ss_str: str, extra_str: str,
) -> str:
    """校验并保存 Profile 配置，返回错误信息（空串表示成功）。"""
    try:
        naming_rules = parse_naming_rules(rules_str)
    except json.JSONDecodeError as e:
        return f"命名规则 JSON 格式错误: {e}"
    try:
        table_schema = parse_table_schema(schema_str)
    except (json.JSONDecodeError, ValueError) as e:
        return f"表结构 JSON 格式错误: {e}"
    try:
        ss_config = parse_json_or(ss_str, {"count": 3, "moments": []})
    except json.JSONDecodeError as e:
        return f"截图配置 JSON 格式错误: {e}"
    try:
        extra_config = parse_json_or(extra_str, {})
    except json.JSONDecodeError as e:
        return f"扩展配置 JSON 格式错误: {e}"

    config_mgr.update_profile_config(profile, "root", root)
    config_mgr.update_profile_config(profile, "from", from_path)
    config_mgr.update_profile_config(profile, "to", to_path)
    config_mgr.update_profile_config(profile, "naming_rules", naming_rules)
    config_mgr.update_profile_config(profile, "table_schema", table_schema)
    config_mgr.update_profile_config(profile, "screenshot_config", ss_config)
    config_mgr.update_profile_config(profile, "extra_config", extra_config)
    return ""
