import pytest
from unittest.mock import MagicMock
from app.services.game_turn_service import GameTurnProcessor
from app.models import GameSession, World, Setting

@pytest.fixture
def mock_game_session():
    """
    创建一个模拟的游戏会话对象，包含基本的游戏状态和世界设定。
    """
    # 创建模拟的世界设定
    mock_setting = Setting(
        id=1,
        config_name="Test AI Config",
        api_type="local_openai",
        api_key="test_key",
        base_url="http://test",
        model_name="test_model",
        user_id=1
    )
    mock_world = World(
        id=1,
        creator_id=1,
        name="Test World",
        setting_pack={
            "attribute_dimensions": {
                "生存": {"name": "气血", "initial_value": 100},
                "资源": {"name": "法力", "initial_value": 50}
            },
            "items": [{"名称": "小血瓶", "效果": ["气血 + 20"], "类型": "恢复类"}],
            "skills": [{"名称": "火球术", "消耗": "法力 - 10", "效果": ["气血 - 30"]}],
            "npcs": [],
            "tasks": []
        }
    )

    # 创建模拟的游戏会话
    mock_session = GameSession(
        id=1,
        user_id=1,
        world_id=1,
        current_state={
            "attributes": {"气血": 100, "法力": 50},
            "inventory": ["小血瓶"],
            "current_location": "test",
            "recent_history": [],
            "last_ai_response": {}
        },
        world=mock_world,
        active_ai_config=mock_setting
    )
    return mock_session

@pytest.fixture
def mock_ai_service():
    """
    创建一个模拟的AI服务，可以控制其返回值。
    """
    ai_service_mock = MagicMock()
    ai_service_mock.generate_game_master_response.return_value = {
        "description": "AI生成的描述",
        "add_item_to_inventory": None,
        "remove_item_from_inventory": None,
        "update_quest_status": None,
        "suggested_choices": []
    }
    return ai_service_mock


def test_process_turn_basic(mock_game_session, monkeypatch, mock_ai_service):
    """
    测试 process_turn 方法的基本流程。
    """
    # 替换掉 ai_service 模块
    monkeypatch.setattr("app.services.game_turn_service.generate_game_master_response",
                        mock_ai_service.generate_game_master_response)
    turn_processor = GameTurnProcessor(mock_game_session)
    player_action = "你好"
    response, status_code = turn_processor.process_turn(player_action)

    assert status_code == 200
    assert "description" in response
    assert response["description"] == "AI生成的描述"
    assert "current_state" in response

def test_process_turn_use_item(mock_game_session, monkeypatch, mock_ai_service):
    """
    测试 process_turn 方法中使用物品的逻辑。
    """
    monkeypatch.setattr("app.services.game_turn_service.generate_game_master_response",
                        mock_ai_service.generate_game_master_response)

    turn_processor = GameTurnProcessor(mock_game_session)
    player_action = "使用 小血瓶"
    response, status_code = turn_processor.process_turn(player_action)

    assert status_code == 200
    assert "description" in response
    assert "current_state" in response
    # 检查血瓶是否使用
    assert '小血瓶' not in response["current_state"]["inventory"]
    # 检查血量是否增加
    assert response["current_state"]["attributes"]["气血"] == 120

def test_process_turn_use_skill(mock_game_session, monkeypatch, mock_ai_service):
    """
    测试 process_turn 方法中使用技能的逻辑
    """
    monkeypatch.setattr("app.services.game_turn_service.generate_game_master_response",
                        mock_ai_service.generate_game_master_response)

    turn_processor = GameTurnProcessor(mock_game_session)
    # 修正：技能使用的指令需要一个目标，以匹配 GameTurnProcessor 中的正则表达式
    player_action = "对 敌人 使用 火球术"
    response, status_code = turn_processor.process_turn(player_action)

    assert status_code == 200
    assert "description" in response
    assert "current_state" in response
    # 检查法力是否扣除
    assert response["current_state"]["attributes"]["法力"] == 40
    # 检查气血是否扣除
    assert response["current_state"]["attributes"]["气血"] == 70

def test_process_turn_framework_validation_error(mock_game_session, monkeypatch, mock_ai_service):
    """
    测试框架校验失败的情况
    """
    monkeypatch.setattr("app.services.game_turn_service.generate_game_master_response",
                        mock_ai_service.generate_game_master_response)

    # 模拟校验失败
    monkeypatch.setattr("app.services.game_turn_service.validate_game_state",
                        lambda x, y: (False, ["测试错误"]))

    turn_processor = GameTurnProcessor(mock_game_session)
    player_action = "你好"
    response, status_code = turn_processor.process_turn(player_action)

    assert status_code == 500
    assert "error" in response
    assert response["error"] == "游戏状态出现异常，为防止数据损坏已中断操作。请尝试重试或联系管理员。"