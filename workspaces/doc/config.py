"""纪实业务 — 默认 Profile 配置（realshot）。"""

PROFILES = {
    "realshot": {
        "name": "实拍",
        "root": "",
        "from": "",
        "to": "",
        "naming_rules": {},
        "extra_config": {},
        "crid_pattern": "",
        "screenshot_config": {"count": 2, "moments": []},
        "table_schema": [
            {"name": "file_size", "type": "INTEGER", "label": "文件大小"},
            {"name": "duration", "type": "REAL", "label": "时长"},
            {"name": "codec", "type": "TEXT", "label": "编码"},
            {"name": "resolution", "type": "TEXT", "label": "分辨率"},
        ],
    },
}
