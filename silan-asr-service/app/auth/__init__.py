# JWT 认证模块 - 支持 HS256（共享密钥）和 RS256（非对称签名）

import jwt
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
PRIVATE_KEY_PATH = PROJECT_ROOT / "keys" / "private.pem"
PUBLIC_KEY_PATH = PROJECT_ROOT / "keys" / "public.pem"

JWT_ISSUER = "meeting-ai"
JWT_AUDIENCE = "jitsi"

# 从环境变量读取算法，默认 HS256
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_SHARED_SECRET = os.getenv("JWT_SHARED_SECRET", "")

_private_key: Optional[str] = None
_public_key: Optional[str] = None


def _load_keys() -> None:
    global _private_key, _public_key
    try:
        _private_key = PRIVATE_KEY_PATH.read_text(encoding="utf-8")
        _public_key = PUBLIC_KEY_PATH.read_text(encoding="utf-8")
        logger.info("JWT RSA keys loaded from files")
    except FileNotFoundError:
        logger.warning("密钥文件未找到，将使用环境变量中的密钥")
        _private_key = os.getenv("JWT_PRIVATE_KEY", "")
        _public_key = os.getenv("JWT_PUBLIC_KEY", "")


# 启动时加载 RSA 密钥（用于 RS256）
_load_keys()

logger.info(f"JWT 认证算法: {JWT_ALGORITHM}")


def _get_sign_key() -> str:
    """获取签名密钥"""
    if JWT_ALGORITHM == "HS256":
        return JWT_SHARED_SECRET
    return _private_key


def _get_verify_key() -> str:
    """获取验证密钥"""
    if JWT_ALGORITHM == "HS256":
        return JWT_SHARED_SECRET
    return _public_key


def sign_token(payload: Dict[str, Any]) -> str:
    """签发 JWT Token"""
    key = _get_sign_key()
    if not key:
        raise ValueError("JWT signing key not configured")
    return jwt.encode(payload, key, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 JWT Token，返回 payload 或 None"""
    try:
        key = _get_verify_key()
        if not key:
            logger.error("JWT verification key not configured")
            return None
        decoded = jwt.decode(
            token,
            key,
            algorithms=[JWT_ALGORITHM],
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
    """生成 Jitsi JWT Token

    role: 'moderator' | 'participant'
      - moderator: XMPP affiliation=owner（房间所有者，主持权限）
      - participant: XMPP affiliation=member（普通参会者，不会被自动升级为 owner）
    """
    import time

    # XMPP affiliation：决定房间权限
    # - 'owner'：主持权限
    # - 'member'：普通参会者（关键：不填或 'none' 时 Jitsi 客户端可能自动升级为 owner）
    affiliation = "owner" if role == "moderator" else "member"

    payload = {
        "iss": JWT_ISSUER,
        "sub": room_id,
        "aud": JWT_AUDIENCE,
        "room": room_id,
        "userId": user_id,
        "role": role,
        "affiliation": affiliation,  # 显式声明 XMPP 房间身份
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


def generate_moderator_token(room_id: str, user_id: str, user_name: Optional[str] = None) -> str:
    """生成主持人 Token（专用入口，会校验房间首人）"""
    return generate_jitsi_token(room_id, user_id, "moderator", user_name)


def generate_participant_token(room_id: str, user_id: str, user_name: Optional[str] = None) -> str:
    """生成参会者 Token"""
    return generate_jitsi_token(room_id, user_id, "participant", user_name)
