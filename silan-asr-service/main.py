import logging
import argparse
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """从项目根目录的 .env 文件加载环境变量（不覆盖已有值）"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        logger.info(f"已加载环境变量文件: {env_path}")
    except Exception as e:
        logger.warning(f"加载 .env 文件失败: {e}")


_load_dotenv()


def _check_required_env() -> None:
    """启动时校验关键配置，避免运行期才以 500 的形式暴露问题"""
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")
    if algorithm == "HS256" and not os.getenv("JWT_SHARED_SECRET"):
        logger.error(
            "JWT_SHARED_SECRET 未配置（JWT_ALGORITHM=HS256），Token 签发/校验一定会失败，"
            "AI 语音识别无法开启。请在 silan-asr-service/.env 中配置后重启服务。"
        )


def main():
    parser = argparse.ArgumentParser(
        description="SiLAN FunASR 实时会议转写服务 - WebSocket Gateway"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GATEWAY_PORT", "8080")),
        help="服务端口号 (默认: 8080 或 .env 中的 GATEWAY_PORT)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("GATEWAY_HOST", "0.0.0.0"),
        help="服务监听地址 (默认: 0.0.0.0 或 .env 中的 GATEWAY_HOST)"
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda"],
        default=os.getenv("ASR_DEVICE", "cpu"),
        help="ASR 推理设备 (默认: cpu 或 .env 中的 ASR_DEVICE)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Worker 数量 (默认: 1)"
    )
    parser.add_argument(
        "--hotword-file",
        type=str,
        default=None,
        help="热词文件路径 (默认: 使用内置词汇)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)"
    )
    
    args = parser.parse_args()
    
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    os.environ["ASR_DEVICE"] = args.device
    os.environ["GATEWAY_PORT"] = str(args.port)
    os.environ["GATEWAY_HOST"] = args.host
    
    if args.hotword_file:
        os.environ["HOTWORD_FILE"] = args.hotword_file
    
    logger.info("=" * 60)
    logger.info("SiLAN 会议 AI 统一服务 (ASR + Meeting + API)")
    logger.info("=" * 60)
    logger.info(f"  监听地址: {args.host}:{args.port}")
    logger.info(f"  推理设备: {args.device}")
    logger.info(f"  日志级别: {args.log_level}")
    logger.info(f"  功能模块: ASR转写 | 会议管理 | JWT认证 | HTTP API")
    logger.info("=" * 60)

    _check_required_env()

    try:
        from app.audio_gateway.ws_server import WebSocketGatewayServer
        from app.config.settings import load_config
        
        config = load_config()
        config.audio_gateway.port = args.port
        config.audio_gateway.host = args.host
        
        server = WebSocketGatewayServer(config.audio_gateway)
        
        logger.info("服务启动中...")
        server.start()
        
    except ImportError as e:
        logger.error(f"启动失败: 缺少必要的依赖库: {e}")
        logger.error("请执行: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        logger.error(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
