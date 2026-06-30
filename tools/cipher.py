def cipher(text: str, key: int, encrypt: bool = True) -> str:
    """
    多语系 Unicode 偏移加密/解密（纯数学运算，无需第三方包）。

    支持：简体中文、繁体中文、日文（假名+汉字）、俄文、法文、德文、英文。
    同语系内映射：中文→中文、英文→英文、俄文→俄文……不会串味。

    Args:
        text:    待处理文本
        key:     整数密钥（建议 1~1000）
        encrypt: True 为加密，False 为解密

    Returns:
        处理后的文本
    """
    # 各语系 Unicode 范围
    RANGES = {
        'cjk': tuple(range(0x4E00, 0x9FFF + 1)) + tuple(range(0x3400, 0x4DBF + 1)),
        'hira': tuple(range(0x3040, 0x309F + 1)),
        'kana': tuple(range(0x30A0, 0x30FF + 1)),
        'cyrl': tuple(range(0x0400, 0x04FF + 1)),
        'latn': tuple(range(0x0041, 0x005A + 1)) + tuple(range(0x0061, 0x007A + 1)) + tuple(range(0x00C0, 0x017F + 1)),
        'digit': tuple(range(0x0030, 0x0039 + 1)),
        'punct': tuple(range(0x3000, 0x303F + 1)) + tuple(range(0x2000, 0x206F + 1)) + tuple(range(0xFF00, 0xFFEF + 1)),
    }

    # 首次调用时缓存 {字符: 所属范围} 查找表
    if not hasattr(cipher, '_CHAR_MAP'):
        cipher._CHAR_MAP = {}
        for rng in RANGES.values():
            for cp in rng:
                cipher._CHAR_MAP[chr(cp)] = rng

    char_map = cipher._CHAR_MAP
    k = key if encrypt else -key
    result = []

    for ch in text:
        rng = char_map.get(ch)
        if rng is None:
            result.append(ch)  # 不在范围内的字符原样保留
        else:
            idx = rng.index(ord(ch))  # 找到当前字符在范围内的位置
            result.append(chr(rng[(idx + k) % len(rng)]))

    return ''.join(result)


# ==================== 调用示例 ====================
"""
KEY = 42

# 加密
plain = "Hello世界！日本語とEnglish混ぜてみる。Привет!"
secret = cipher(plain, key=KEY, encrypt=True)
print(secret)  # xÔÛÛÞ乀當Ｋ昏杖諈をuÝÖÛØâ×渡ゆゐぉさ〬щѪѢќџѬ!

# 解密
back = cipher(secret, key=KEY, encrypt=False)
print(back)  # Hello世界！日本語とEnglish混ぜてみる。Привет!
"""