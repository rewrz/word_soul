from app import db
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.dialects.sqlite import JSON

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # 关系：一个用户可以有多个AI配置
    ai_configs = db.relationship('Setting', backref='owner', lazy='dynamic', foreign_keys='Setting.user_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class World(db.Model):
    __tablename__ = 'worlds'
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_world_creator'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    # 重构 blueprint 为 setting_pack，存储经过校验的、结构化的世界设定包
    # setting_pack 将包含 'attribute_dimensions', 'items', 'skills', 'tasks' 等模块
    # 它的结构由你的“通用规则框架”定义
    setting_pack = db.Column(JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', backref=db.backref('created_worlds', lazy=True), foreign_keys=[creator_id])

class GameSession(db.Model):
    __tablename__ = 'game_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_session_user'), nullable=False)
    world_id = db.Column(db.Integer, db.ForeignKey('worlds.id', name='fk_session_world'), nullable=False)
    # current_state 的结构应与 setting_pack 中的 attribute_dimensions 对应
    # 例如: { "attributes": { "气血": 100, "内力": 50 }, "inventory": ["金疮药"], ... }
    current_state = db.Column(JSON, nullable=False)
    last_played = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # 关系：用户选择的AI配置
    # 注意：这里我们使用一个整数ID来存储用户选择的配置的主键
    active_ai_config_id = db.Column(db.Integer, db.ForeignKey('settings.id', name='fk_session_ai_config'), nullable=True)

    user = db.relationship('User', backref=db.backref('game_sessions', lazy=True))
    world = db.relationship('World', backref=db.backref('game_sessions', lazy=True))
    active_ai_config = db.relationship('Setting', foreign_keys=[active_ai_config_id])

class Setting(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    
    # 用户自定义的配置名称，例如 '我的Ollama Llama3'
    config_name = db.Column(db.String(64), nullable=False) 
    
    # API 关键信息
    api_type = db.Column(db.String(64), nullable=False) # 'openai', 'gemini', 'claude', 'local_openai'
    api_key = db.Column(db.String(512), nullable=True) # API Key
    base_url = db.Column(db.String(512), nullable=True) # API 的基础URL
    model_name = db.Column(db.String(128), nullable=True) # 模型的具体名称
    
    # 外键，关联到用户。
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_setting_user'), nullable=False, index=True)

    def __repr__(self):
        return f"<Setting(config_name='{self.config_name}', user_id={self.user_id}, api_type='{self.api_type}')>"
