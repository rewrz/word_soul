from flask import Blueprint, request, jsonify
from app import db
from app.models import Setting, User, World, GameSession
from app.services.ai_service import (analyze_world_creation_text,
                                      generate_game_master_response)
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

    # 从“创世咏唱”表单中提取数据
    world_name = data.get('world_name') # 此界之名
    character_description = data.get('character_description') # 吾身之形
    world_rules = data.get('world_rules') # 万物之律
    initial_scene = data.get('initial_scene') # 初始之景
    narrative_principles = data.get('narrative_principles') # 叙事原则
    # 新增：获取用户为这个世界选择的AI配置ID
    active_ai_config_id = data.get('active_ai_config_id')

    if not all([world_name, character_description, world_rules, initial_scene, narrative_principles]):
        return jsonify({"error": "创建世界所需字段不完整"}), 400

    # 组合自由文本字段以供AI分析
    ai_input_blob = f"万物之律:\n{world_rules}\n\n叙事原则:\n{narrative_principles}"
    analyzed_data = analyze_world_creation_text(ai_input_blob)

    # 构建世界蓝图
    blueprint = {
        "user_defined_character": character_description,
        "user_defined_rules": world_rules,
        "user_defined_narrative": narrative_principles,
        "ai_premise": analyzed_data.get('world_premise'),
        "ai_narrative_principles": analyzed_data.get('narrative_principles')
    }

    new_world = World(creator_id=current_user_id, name=world_name, blueprint=blueprint)
    db.session.add(new_world)
    db.session.flush() # 刷新以获取 new_world.id 用于游戏会话

    initial_state = {
        "player_character": character_description,
        "current_location": initial_scene,
        "inventory": [],
        "hp": 100,  # 初始生命值
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
    from app.services.ai_service import assist_world_creation_text
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

    # 将用户输入和AI配置传递给AI服务函数
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
    """
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    player_action = data.get('action')

    if not player_action:
        return jsonify({"error": "必须提供行动指令"}), 400

    # 一次性获取会话并验证所有权
    session = GameSession.query.filter_by(id=session_id, user_id=current_user_id).first_or_404(
        description="游戏会话未找到或无权访问"
    )

    # --- AI Prompt构建与调用 ---
    # 这是关键的修改：我们将整个 session 对象传递给AI服务
    ai_response_data = generate_game_master_response(
        world_blueprint=session.world.blueprint,
        current_state=session.current_state,
        player_action=player_action,
        game_session=session
    )

    # 检查AI服务是否返回了错误
    if "error" in ai_response_data:
        return jsonify(ai_response_data), 500

    # --- 状态更新逻辑 ---
    # 注意：SQLAlchemy 2.0+ 会自动跟踪JSON字段的变化，无需手动标记修改
    current_state = session.current_state

    if item_to_add := ai_response_data.get('add_item_to_inventory'):
        current_state['inventory'].append(item_to_add)

    if item_to_remove := ai_response_data.get('remove_item_from_inventory'):
        if item_to_remove in current_state['inventory']:
            current_state['inventory'].remove(item_to_remove)

    if quest_update_str := ai_response_data.get('update_quest_status'):
        if ':' in quest_update_str:
            quest_name, quest_status = quest_update_str.split(':', 1)
            current_state['active_quests'][quest_name.strip()] = quest_status.strip()

    if hp_change_str := ai_response_data.get('hp_change'):
        try:
            hp_change = int(hp_change_str)
            current_state['hp'] = max(0, current_state.get('hp', 0) + hp_change)  # 确保生命值不低于0
        except ValueError:
            print(f"无法解析的生命值变化：{hp_change_str}")
            # 这里可以选择记录错误或采取其他适当的操作
    
    # 更新最近历史记录以维持AI的上下文
    current_state['recent_history'].insert(0, {"role": "player", "content": player_action})
    current_state['recent_history'].insert(0, {"role": "assistant", "content": ai_response_data.get('description', '')})
    current_state['recent_history'] = current_state['recent_history'][:10] # 保留最近5轮交互

    # 存储完整的上一次AI回复，以便加载时恢复建议选项
    current_state['last_ai_response'] = ai_response_data

    # 关键修复：明确告知SQLAlchemy，current_state这个JSON字段已被修改
    flag_modified(session, "current_state")

    db.session.commit()

    # 将AI的回复与完整的游戏状态一起返回给前端
    response_payload = {**ai_response_data, "current_state": current_state}
    return jsonify(response_payload)

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
