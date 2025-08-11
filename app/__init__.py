from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config
from flask_jwt_extended import JWTManager
from datetime import timedelta

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 核心修改：为访问令牌（access token）设置一个较短的过期时间，例如15分钟
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
    # 核心新增：为刷新令牌（refresh token）设置一个较长的过期时间，例如30天
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    from app.models import TokenBlocklist

    # 核心新增：注册一个回调函数，用于在每次请求时检查令牌是否在黑名单中
    @jwt.token_in_blocklist_loader
    def check_if_token_in_blocklist(jwt_header, jwt_payload):
        """
        这个回调函数会在每次使用受保护的端点时被调用。
        它会检查令牌的 JTI 是否存在于我们的黑名单数据库中。
        """
        jti = jwt_payload["jti"]
        token = db.session.query(TokenBlocklist.id).filter_by(jti=jti).scalar()
        return token is not None

    # 为JWT添加自定义的错误处理器，以便记录更详细的日志和返回中文提示
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        # 'error' 参数是一个字符串，说明了令牌无效的原因
        app.logger.error(f"JWT无效令牌错误: {error}")
        return jsonify({
            "msg": "您的令牌是无效的。",
            "error": "token_invalid"
        }), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        """
        当JWT过期时，返回一个更明确的中文错误信息。
        """
        app.logger.warning(f"Expired JWT received. User: {jwt_payload.get('sub')}")
        return jsonify({
            "msg": "Your session has expired. Please log in again.",
            "error": "token_expired"
        }), 401

    from app.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.main import main_bp
    app.register_blueprint(main_bp)

    return app