"""Shared validation for names written to Codex."""
import unicodedata


def validate_session_name(name):
    if not isinstance(name, str):
        raise ValueError('会话名称必须是文本')
    if any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'} for char in name):
        raise ValueError('会话名称不能包含换行或控制字符')
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError('会话名称须为 1～100 个字符')
    return name
