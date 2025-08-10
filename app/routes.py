from flask import Blueprint, request, jsonify
from app import db
import json
from app.models import Setting, User, World, GameSession
from app.services.ai_service import (
                                      assist_world_creation_text,
                                      generate_setting_pack)
from app.services.framework_validator import validate_setting_pack
from app.services.game_turn_service import GameTurnProcessor
from sqlalchemy.orm.attributes import flag_modified
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

api_bp = Blueprint('api', __name__)

# --- 用户管理 ---
@api_bp.route('/register', methods=['POST'])
def register():
    """注册新用户"""
    data = request.get_json()
    if not data or not 'username' in data or not 'password' in data:
        return jsonify({'error': '必须提供用户名和密码'}), 400

    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': '用户名已存在'}), 400

    user = User(username=data['username'])
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': '用户注册成功'}), 201

@api_bp.route('/login', methods=['POST'])
def login():
    """用户登录，获取JWT"""
    data = request.get_json()
    if not data or not 'username' in data or not 'password' in data:
        return jsonify({'error': '必须提供用户名和密码'}), 400

    user = User.query.filter_by(username=data['username']).first()

    if user is None or not user.check_password(data['password']):
        return jsonify({'error': '用户名或密码无效'}), 401

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"access_token": access_token})

@api_bp.route('/logout', methods=['POST'])
def logout():
    """用户登出"""
    # 对于JWT，登出通常由客户端通过删除令牌来处理。
    # 更健壮的实现可以增加一个服务器端的令牌黑名单。
    return jsonify({'message': '登出成功'})

# --- 游戏创建 ---

@api_bp.route('/worlds', methods=['POST'])
@jwt_required()
def create_world():
    """
    创世咏唱
    创建一个新世界并开始第一个游戏会话。
    """
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的输入"}), 400

    # 接收用户的背景关键词和选择的AI模型
    world_keywords = data.get('world_keywords') # 例如: "赛博朋克, 东方武学, 霓虹都市"
    player_description = data.get('player_description') # 玩家对自己角色的初步描述
    active_ai_config_id = data.get('active_ai_config_id')

    if not world_keywords:
        return jsonify({"error": "必须提供世界背景关键词"}), 400

    # 3. 调用AI生成设定包。
    # generate_setting_pack 函数内部已经包含了分步生成、校验和重试逻辑。
    raw_setting_pack = generate_setting_pack(
        world_keywords,
        player_description,
        active_ai_config_id
    )

    # 4. 检查生成结果。如果包含error，说明内部重试后依然失败。
    if "error" in raw_setting_pack:
        return jsonify(raw_setting_pack), 500

    # 5. 校验通过，创建世界
    if not raw_setting_pack:
        return jsonify({"error": "AI未能生成有效的设定包"}), 500

    # setting_pack 中应包含世界名称等信息
    world_name = raw_setting_pack.get("world_name", "未命名世界")

    # 6. 根据设定包初始化游戏状态
    new_world = World(creator_id=current_user_id, name=world_name, setting_pack=raw_setting_pack)
    db.session.add(new_world)
    db.session.flush() # 刷新以获取 new_world.id 用于游戏会话
    attributes = {}
    # 从设定包的 "attribute_dimensions" 初始化玩家属性
    for dim_type, dim_details in raw_setting_pack.get("attribute_dimensions", {}).items():
        attributes[dim_details["name"]] = dim_details.get("initial_value", 100)

    initial_state = {
        "attributes": attributes,
        "player_character": raw_setting_pack.get("player_character_description", player_description),
        "current_location": raw_setting_pack["initial_scene"], # 直接获取初始场景
        "inventory": [],
        "active_quests": {},
        "recent_history": [],
        "last_ai_response": {} # 用于存储上一次AI的完整回复
    }

    # 将用户选择的AI配置与新会话关联
    new_session = GameSession(
        user_id=current_user_id,
        world_id=new_world.id,
        current_state=initial_state,
        active_ai_config_id=active_ai_config_id
    )
    db.session.add(new_session)
    db.session.commit()

    return jsonify({
        "message": f"世界 '{world_name}' 已成功创造!",
        "world_id": new_world.id,
        "session_id": new_session.id
    }), 201

# --- 新增：创世辅助 ---
@api_bp.route('/worlds/assist', methods=['POST'])
@jwt_required()
def assist_world_creation():
    """
    AI辅助创世
    接收用户已填写的创世表单字段，调用AI进行润色、补充和填充。
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json() or {}

    # 尝试从请求中获取用户希望使用的AI配置ID
    config_id = data.get('active_ai_config_id')
    active_config = None
    if config_id is not None:
        try:
            # 确保从JSON获取的ID被当作整数处理
            int_config_id = int(config_id)
            active_config = Setting.query.filter_by(id=int_config_id, user_id=current_user_id).first()
        except (ValueError, TypeError):
            # 如果ID不是有效的整数，则忽略它
            active_config = None
    # 如果没有提供有效的config_id，active_config将为None，
    # ai_service会回退到全局配置，并打印相应日志。

    assisted_data = assist_world_creation_text(
        world_name=data.get('world_name'),
        character_description=data.get('character_description'),
        world_rules=data.get('world_rules'),
        initial_scene=data.get('initial_scene'),
        narrative_principles=data.get('narrative_principles'),
        active_config=active_config
    )

    if assisted_data and "错误" in str(assisted_data.get("world_name", "")):
        # 将AI返回的具体错误信息传递给前端，而不是一个通用消息
        error_message = assisted_data.get("world_name", "AI辅助生成失败，请稍后再试。")
        return jsonify({"error": error_message}), 500

    return jsonify(assisted_data)


# --- 加载游戏会话 ---
@api_bp.route('/sessions/<int:session_id>', methods=['GET'])
@jwt_required()
def get_session(session_id):
    """
    根据会话ID获取游戏会话信息
    """
    current_user_id = int(get_jwt_identity())
    try:
        session = GameSession.query.filter_by(id=session_id, user_id=current_user_id).first_or_404(
            description="游戏会话未找到或无权访问"
        )

        session_data = {
            "session_id": session.id,
            "world_id": session.world_id,
            "world_name": session.world.name,
            "current_state": session.current_state,
            "active_ai_config_id": session.active_ai_config_id,
            "last_played": session.last_played.isoformat()
        }
        return jsonify(session_data)
    except Exception as e:
        print(f"获取会话信息时出错: {e}")
        return jsonify({'error': '获取会话信息失败'}), 500


# --- 游戏进行 ---

@api_bp.route('/sessions', methods=['GET'])
@jwt_required()
def get_sessions():
    """
    获取言灵纪事
    为当前用户获取所有游戏会话以在主菜单显示。
    """
    current_user_id = int(get_jwt_identity())
    try:
        # 查询会话并连接世界以获取世界名称
        sessions = db.session.query(
            GameSession.id,
            GameSession.last_played,
            World.name.label('world_name')
        ).join(World, World.id == GameSession.world_id).filter(
            GameSession.user_id == current_user_id
        ).order_by(GameSession.last_played.desc()).all()

        session_list = [
            {
                "session_id": session.id,
                "world_name": session.world_name,
                "last_played": session.last_played.isoformat()
            } for session in sessions
        ]
        return jsonify(session_list)
    except Exception as e:
        print(f"获取会话时出错: {e}")
        return jsonify({'error': '获取会话失败'}), 500

@api_bp.route('/sessions/<int:session_id>/action', methods=['POST'])
@jwt_required()
def take_action(session_id):
    """
    言灵交互
    提交玩家行动并获取AI的回应，同时更新游戏状态。
    重要：
    1. 在此函数的最开始，必须先减少所有技能冷却时间。
    2. 在处理完玩家行动后，如果处于战斗状态，则自动处理所有NPC的回合。
    3. 在返回响应前，必须对游戏状态进行最终校验。
    """
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    player_action = data.get('action')

    if not player_action:
        return jsonify({"error": "必须提供行动指令"}), 400

    # 1. 获取会话并验证所有权
    session = GameSession.query.filter_by(id=session_id, user_id=current_user_id).first_or_404(
        description="游戏会话未找到或无权访问"
    )

    # 创建 GameTurnProcessor 实例
    turn_processor = GameTurnProcessor(session)

    # 使用 GameTurnProcessor 处理回合
    response_payload, status_code = turn_processor.process_turn(player_action)

    # --- 关键修复 ---
    # 如果回合处理成功（HTTP状态码小于400），则将更新后的状态保存到数据库。
    # 如果不这样做，所有游戏进度都会在请求结束后丢失。
    if status_code < 400:
        # 告知SQLAlchemy，session.current_state这个JSON字段已被修改。
        # 如果不标记，SQLAlchemy可能不会检测到对字典内部值的更改。
        flag_modified(session, "current_state")
        db.session.commit()


    return jsonify(response_payload), status_code

@api_bp.route('/sessions/<int:session_id>', methods=['DELETE'])
@jwt_required()
def delete_session(session_id):
    """删除一个游戏会话"""
    current_user_id = int(get_jwt_identity())
    session = GameSession.query.filter_by(id=session_id, user_id=current_user_id).first_or_404(
        description="游戏会话未找到或无权访问"
    )

    db.session.delete(session)
    db.session.commit()

    return jsonify({'message': '会话删除成功'}), 200

# --- 用户AI配置管理 ---

@api_bp.route('/ai-configs', methods=['GET'])
@jwt_required()
def get_user_ai_configs():
    """获取当前用户的所有AI配置"""
    user_id = int(get_jwt_identity())
    configs = Setting.query.filter_by(user_id=user_id).order_by(Setting.config_name).all()
    return jsonify([{
        "id": c.id,
        "config_name": c.config_name,
        "api_type": c.api_type,
        "api_key": c.api_key,
        "base_url": c.base_url,
        "model_name": c.model_name
    } for c in configs])

@api_bp.route('/ai-configs', methods=['POST'])
@jwt_required()
def create_user_ai_config():
    """为当前用户创建新的AI配置"""
    user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data or not data.get('config_name') or not data.get('api_type'):
        return jsonify({"error": "配置名称和API类型是必填项"}), 400

    new_config = Setting(
        user_id=user_id,
        config_name=data['config_name'],
        api_type=data['api_type'],
        api_key=data.get('api_key'),
        base_url=data.get('base_url'),
        model_name=data.get('model_name')
    )
    db.session.add(new_config)
    db.session.commit()
    return jsonify({"message": "AI配置创建成功", "id": new_config.id}), 201

@api_bp.route('/ai-configs/<int:config_id>', methods=['PUT'])
@jwt_required()
def update_user_ai_config(config_id):
    """更新用户自己的一个AI配置"""
    user_id = int(get_jwt_identity())
    config = Setting.query.filter_by(id=config_id, user_id=user_id).first_or_404()
    data = request.get_json()

    config.config_name = data.get('config_name', config.config_name)
    config.api_type = data.get('api_type', config.api_type)
    config.api_key = data.get('api_key', config.api_key)
    config.base_url = data.get('base_url', config.base_url)
    config.model_name = data.get('model_name', config.model_name)

    db.session.commit()
    return jsonify({"message": "AI配置更新成功"})

@api_bp.route('/ai-configs/<int:config_id>', methods=['DELETE'])
@jwt_required()
def delete_user_ai_config(config_id):
    """删除用户自己的一个AI配置"""
    user_id = int(get_jwt_identity())
    config = Setting.query.filter_by(id=config_id, user_id=user_id).first_or_404()
    db.session.delete(config)
    db.session.commit()
    return jsonify({"message": "AI配置删除成功"})

@api_bp.route('/sessions/<int:session_id>/set-ai-config', methods=['POST'])
@jwt_required()
def set_active_ai_for_session(session_id):
    """为指定的游戏会话设置当前使用的AI配置"""
    user_id = int(get_jwt_identity())

    session = GameSession.query.filter_by(id=session_id, user_id=user_id).first_or_404()
    data = request.get_json()
    config_id = data.get('config_id') # 允许为 null

    # 在设置之前，验证config_id是否属于当前用户（如果它不是null）
    if config_id is not None:
        config_to_set = Setting.query.filter_by(id=config_id, user_id=user_id).first()
        if not config_to_set:
            return jsonify({"error": "配置未找到或无权使用"}), 404

    # 将 config_id 设置为 None 意味着使用全局默认配置
    session.active_ai_config_id = config_id
    db.session.commit()
    return jsonify({"message": f"会话 {session_id} 的AI配置已更新"})
