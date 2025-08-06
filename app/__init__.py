from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # Add custom error handlers for JWT to get more detailed logs
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        # The 'error' argument is a string indicating the reason why the token is invalid.
        app.logger.error(f"JWT Invalid Token Error: {error}")
        return jsonify({
            "msg": "Your token is invalid.",
            "error": "token_invalid"
        }), 422

    from app.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.main import main_bp
    app.register_blueprint(main_bp)

    return app