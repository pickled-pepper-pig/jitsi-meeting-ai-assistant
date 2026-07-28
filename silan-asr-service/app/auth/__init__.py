# JWT 认证模块 - RS256 非对称签名

import jwt
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
PRIVATE_KEY_PATH = PROJECT_ROOT / "keys" / "private.pem"
PUBLIC_KEY_PATH = PROJECT_ROOT / "keys" / "public.pem"

JWT_ISSUER = "meeting-ai"
JWT_AUDIENCE = "jitsi"

_private_key: Optional[str] = None
_public_key: Optional[str] = None


def _load_keys() -> None:
    global _private_key, _public_key
    try:
        _private_key = PRIVATE_KEY_PATH.read_text(encoding="utf-8")
        _public_key = PUBLIC_KEY_PATH.read_text(encoding="utf-8")
        logger.info("JWT keys loaded from files")
    except FileNotFoundError:
        logger.warning("密钥文件未找到，将使用环境变量中的密钥")
        import os
        _private_key = os.getenv("JWT_PRIVATE_KEY", "")
        _public_key = os.getenv("JWT_PUBLIC_KEY", "")


# 启动时加载密钥
_load_keys()


def sign_token(payload: Dict[str, Any]) -> str:
    """签发 JWT Token"""
    return jwt.encode(payload, _private_key, algorithm="RS256")


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 JWT Token，返回 payload 或 None"""
    try:
        decoded = jwt.decode(
            token,
            _public_key,
            algorithms=["RS256"],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
        )
        return decoded
    except Exception as e:
        logger.debug(f"Token 验证失败: {e}")
        return None


def is_moderator(token: str) -> bool:
    """检查 token 是否为主持人"""
    payload = verify_token(token)
    if not payload:
        return False
    return payload.get("role") == "moderator"


def generate_jitsi_token(
    room_id: str,
    user_id: str,
    role: str,
    user_name: Optional[str] = None,
) -> str:
    """生成 Jitsi JWT Token"""
    import time

    payload = {
        "iss": JWT_ISSUER,
        "sub": room_id,
        "aud": JWT_AUDIENCE,
        "room": room_id,
        "userId": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400,  # 24h
    }
    if user_name:
        payload["context"] = {"user": {"name": user_name}}

    return sign_token(payload)


def generate_dev_tokens(room_id: str, user_id: str) -> Dict[str, str]:
    """开发环境：生成主持人 + 参会者两套 Token"""
    return {
        "moderator": generate_jitsi_token(room_id, user_id, "moderator"),
        "participant": generate_jitsi_token(room_id, user_id, "participant"),
    }
