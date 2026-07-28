import logging
import argparse
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="SiLAN FunASR 实时会议转写服务 - WebSocket Gateway"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="服务端口号 (默认: 8080)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="服务监听地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda"],
        default="cpu",
        help="ASR 推理设备 (默认: cpu)"
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
