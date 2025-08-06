import os
import re
import requests
from flask import current_app
import json
from urllib.parse import urljoin
from app.models import Setting, GameSession

def parse_ai_output(text):
    """
    一个健壮的解析器，用于处理AI返回的带标签的文本格式。
    现在修改为处理 JSON 格式。
    """
    # 增加处理逻辑，去除AI可能返回的markdown代码块标记
    # 例如 ```json\n{...}\n```
    cleaned_text = text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError:
        print(f"JSON解析失败: {cleaned_text}")
        return {}

    # 转换为小写键
    data = {k.lower(): v for k, v in data.items()}

    return data

def format_json_like_string(json_string):
    try:
        data = json.loads(json_string)
        formatted_json = json.dumps(data, indent=4, ensure_ascii=False)
        return formatted_json
    except json.JSONDecodeError:
        return json_string

def _call_openai_api(prompt_text, api_key, base_url=None, model_name="gpt-4o-mini"):
    """调用OpenAI或兼容OpenAI的API（如Ollama）"""
    if base_url:
        # 对于本地模型或代理，将基础URL与API端点拼接
        # urljoin可以智能处理末尾是否有'/'的问题
        url = urljoin(base_url, "v1/chat/completions")
    else:
        # 对于官方OpenAI，使用默认的完整URL
        url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name or "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.7,
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()  # 如果HTTP状态码是4xx或5xx，则抛出异常
        data = response.json()

        # 增加健壮性：检查API是否在JSON中返回了错误信息
        if 'error' in data:
            error_value = data['error']
            if isinstance(error_value, dict):
                # 如果 'error' 是一个字典，尝试获取 'message'
                error_message = error_value.get('message', json.dumps(error_value))
            else:
                # 如果 'error' 是一个字符串或其他类型，直接转换
                error_message = str(error_value)
            print(f"OpenAI API返回错误: {error_message}")
            return f"[错误] AI服务返回错误: {error_message}"

        return data['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        print(f"调用OpenAI API时出错: {e}")
        return "[错误] AI服务暂时无法连接。"
    except (KeyError, IndexError) as e:
        # 增强日志：打印出收到的原始数据，方便排查问题
        print(f"解析OpenAI API响应时出错: {e}。收到的原始数据: {data}")
        return "[错误] AI服务返回了意料之外的数据格式。"
    except json.JSONDecodeError:
        print(f"解析OpenAI API响应时出错: 无法解码JSON。收到的原始文本: {response.text}")
        return "[错误] AI服务返回了非JSON格式的响应。"

def _call_gemini_api(prompt_text, api_key, model_name="gemini-1.5-flash"):
    """调用Google Gemini API"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name or 'gemini-1.5-flash'}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()

        # 增加健壮性：检查Gemini特有的错误格式
        if not data.get('candidates'):
            error_info = data.get('promptFeedback', '未知错误')
            print(f"Gemini API 返回错误: {error_info}")
            return f"[错误] AI服务返回错误: {error_info}"

        return data['candidates'][0]['content']['parts'][0]['text']
    except requests.exceptions.RequestException as e:
        print(f"调用Gemini API时出错: {e}")
        return "[错误] AI服务暂时无法连接。"
    except (KeyError, IndexError) as e:
        print(f"解析Gemini API响应时出错: {e}。收到的原始数据: {data}")
        return "[错误] AI服务返回了意料之外的数据格式。"
    except json.JSONDecodeError:
        print(f"解析Gemini API响应时出错: 无法解码JSON。收到的原始文本: {response.text}")
        return "[错误] AI服务返回了非JSON格式的响应。"

def _call_claude_api(prompt_text, api_key, model_name="claude-3-haiku-20240307"):
    """调用Anthropic Claude API"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": model_name or "claude-3-haiku-20240307",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt_text}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()

        # 增加健壮性：检查Claude特有的错误格式
        if data.get('type') == 'error':
            error_message = data.get('error', {}).get('message', str(data.get('error')))
            print(f"Claude API 返回错误: {error_message}")
            return f"[错误] AI服务返回错误: {error_message}"

        return data['content'][0]['text']
    except requests.exceptions.RequestException as e:
        print(f"调用Claude API时出错: {e}")
        return "[错误] AI服务暂时无法连接。"
    except (KeyError, IndexError) as e:
        print(f"解析Claude API响应时出错: {e}。收到的原始数据: {data}")
        return "[错误] AI服务返回了意料之外的数据格式。"
    except json.JSONDecodeError:
        print(f"解析Claude API响应时出错: 无法解码JSON。收到的原始文本: {response.text}")
        return "[错误] AI服务返回了非JSON格式的响应。"

def call_llm_api(prompt_text, active_config=None):
    """
    根据提供的AI配置或全局默认配置，分发到不同的LLM API调用函数。
    """
    if active_config:
        # 使用用户为当前会话选择的特定配置
        print(f"--- 正在使用用户配置: {active_config.config_name} ---")
        provider = active_config.api_type.lower()
        api_key = active_config.api_key
        base_url = active_config.base_url
        model_name = active_config.model_name
    else:
        # 回退到使用 .env 文件中的全局默认配置
        print(f"--- 未找到用户特定配置，正在使用全局默认配置 ---")
        provider = os.environ.get('AI_PROVIDER', 'local_openai').lower()
        api_key = os.environ.get(f"{provider.upper()}_API_KEY", 'dummy-key')
        base_url = os.environ.get(f"{provider.upper()}_API_BASE_URL")
        model_name = None # 使用API函数中的默认模型

    if provider in ['openai', 'local_openai']:
        if not api_key: return "[错误] 缺少 API Key。"
        if provider == 'local_openai' and not base_url:
            return "[错误] 使用本地模型时，必须配置基础URL (base_url)。"
        return _call_openai_api(prompt_text, api_key, base_url, model_name or "gpt-4o-mini")
    
    elif provider == 'gemini':
        if not api_key: return "[错误] 缺少 Gemini API Key。"
        return _call_gemini_api(prompt_text, api_key, model_name)

    elif provider == 'claude':
        if not api_key: return "[错误] 缺少 Claude API Key。"
        return _call_claude_api(prompt_text, api_key, model_name)

    else:
        return f"[错误] 不支持的AI提供商: {provider}。"

def analyze_world_creation_text(text_blob):
    """调用AI分析创世文本 (使用全局默认配置)"""
    prompt = f"""
你是一个游戏设定分析师。你的任务是从一段给定的世界描述中，提炼出核心设定和叙事原则。请严格按照“[TAG] content”的格式输出。

# 以下是由玩家创造的世界描述：
{text_blob}

# --- 请从上述描述中提取并填充以下信息 ---

[WORLD_PREMISE]
(在此处用一句话总结这个世界的核心规则或风格)

[NARRATIVE_PRINCIPLES]
(在此处总结玩家定义的叙事原则、故事基调和结局导向。如果没有，则总结为“一个开放、自由的沙盒世界”)
"""
    # 创世分析总是使用全局配置，不使用用户特定配置
    ai_response_text = call_llm_api(prompt)
    return parse_ai_output(ai_response_text)

def assist_world_creation_text(world_name, character_description, world_rules, initial_scene, narrative_principles, active_config=None):
    """
    调用AI辅助创世。
    """
    # 构建一个字典来表示用户输入，方便检查
    user_input = {
        "此界之名": world_name,
        "吾身之形": character_description,
        "万物之律": world_rules,
        "初始之景": initial_scene,
        "叙事原则": narrative_principles,
    }

    # 格式化用户输入，如果为空则标记
    formatted_input = "\n".join(
        f"  - {key}: {value or '(空，待生成)'}" for key, value in user_input.items()
    )

    prompt = f"""
你是一位富有想象力的世界构建大师和创意写作助手。你的任务是帮助用户完善或从零开始创建一个引人入胜的文字冒险游戏世界。

# 核心任务
根据用户提供的不完整或完整的世界设定，进行润色、扩充、补充，并确保所有设定在逻辑上自洽且充满创意。你的输出**必须**是符合 JSON 格式的字符串。

- 如果用户提供了某个字段的内容，你必须在该内容的基础上进行扩充和润色，使其更加生动和具体。
- 如果用户将某个字段留空，你必须根据其他已填写的字段，创作出与之风格协调、逻辑自洽的内容。
- 如果用户所有字段都留空，你必须随机生成一个完整、有趣、充满想象力的世界设定。

# 用户输入
{formatted_input}

# 你的输出
请严格按照以下格式，为每个字段生成或完善内容。确保你的输出是一个完整的、可以直接用于创建游戏世界的设定集，不要输出多余的内容。

```json
{{
    "WORLD_NAME": "(生成一个独特且富有吸引力的世界名称)",
    "CHARACTER_DESCRIPTION": "(描述一个引人入胜的玩家角色背景和形象)",
    "WORLD_RULES": "(详细阐述这个世界的核心规则、物理法则、魔法系统、社会结构等，使其丰满可信)",
    "INITIAL_SCENE": "(描绘一个充满悬念和探索可能性的开场画面)",
    "NARRATIVE_PRINCIPLES": "(设定一个清晰的故事基调，例如：黑暗奇幻、赛博朋克、英雄史诗、轻松幽默等)"
}}
```
"""
    # 创世辅助根据传入的配置调用AI
    ai_response_text = call_llm_api(prompt, active_config=active_config)

    # 尝试格式化输出，如失败则原样返回
    ai_response_text = format_json_like_string(ai_response_text)



    # 检查API调用是否返回了空内容或错误信息
    if not ai_response_text or not ai_response_text.strip():
        return {"world_name": "[错误] AI服务返回了空内容，请重试。"}

    if ai_response_text.strip().startswith("[错误]"):
        return {"world_name": ai_response_text}
    # 解析AI的输出
    parsed_data = parse_ai_output(ai_response_text)

    # 检查解析结果是否为空，这表示AI没有遵循格式
    if not parsed_data:
        return {"world_name": "[错误] AI未能按预期格式生成内容，请重试。"}

    # 将解析后的数据映射回前端期望的字段名。
    # 关键：即使AI没有返回某个字段，也要确保返回一个包含空字符串的完整结构，
    # 而不是None，这样可以防止前端JS因处理null而出错或清空表单。
    return {
        "world_name": parsed_data.get("world_name", ""),
        "character_description": parsed_data.get("character_description", ""),
        "world_rules": parsed_data.get("world_rules", ""),
        "initial_scene": parsed_data.get("initial_scene", ""),
        "narrative_principles": parsed_data.get("narrative_principles", ""),
    }


def generate_game_master_response(world_blueprint, current_state, player_action, game_session):
    """调用AI生成游戏剧情"""
    narrative_principles = world_blueprint.get('ai_narrative_principles', '一个开放、自由的沙盒世界')
    player_character = current_state.get('player_character', '未知')
    current_location = current_state.get('current_location', '未知之地')
    inventory = ", ".join(current_state.get('inventory', [])) or "无"
    hp = current_state.get('hp', '未知') # 如果状态中没有HP，则明确告知AI
    
    history_log = ""
    for entry in reversed(current_state.get('recent_history', [])):
        if entry['role'] == 'player':
            history_log += f"玩家: {entry['content']}\n"
        else:
            history_log += f"你: {entry['content']}\n"

    prompt = f"""
你是一位名为“世界之灵”的游戏主持人，引导着一场名为“言灵”的文字冒险。你的行为必须严格遵守以下准则。

# --- 核心行为准则 (Your Core Principles) ---
1.  **绝对沉浸:** 绝不承认自己是AI或程序。拒绝回答任何与游戏剧情无关的问题。若被问及，应以游戏角色的口吻巧妙回避。
2.  **动态引导:** 尊重玩家的自由选择，但当玩家行为严重偏离世界基调时，应通过剧情将其温和地引导回来。
3.  **开放结局:** 故事的结局由玩家的行为累积决定。
4.  **严格格式化输出:** 你的所有回复都必须严格遵循下方的格式。每个部分都以一个大写的标签（如 `[DESCRIPTION]`）开始，然后换行写内容。如果某个部分没有内容，则将标签保留，内容留空。

# --- 世界设定 (World Blueprint) ---
[世界基调]
{narrative_principles}

# --- 当前状态 (Current State) ---
[玩家角色]
{player_character}
[当前位置]
{current_location}
[生命值]
{hp}
[持有物品]
{inventory}

# --- 最近的交互历史 (Recent History) ---
{history_log}

# --- 玩家的当前行动 (Player's Current Action) ---
玩家: {player_action}

# --- 你的回复 (Your Response) ---
# 请严格按照以下JSON格式生成你的回复。
```json
{{
    "DESCRIPTION": "(在此处详细、生动地描述玩家行动后，世界发生的变化、新的场景、NPC的反应等。这是故事的主体。)",    
    "PLAYER_MESSAGE": "(如果需要给玩家一个简短的、系统层面的提示或状态更新，请写在这里。例如：“你的火把似乎快要熄灭了。”或“你感到一阵寒意。”。如果没有，则留空。)",
    "ADD_ITEM_TO_INVENTORY": "(如果玩家在此回合获得了新物品，请在此处写下物品的名称。例如：“一把生锈的钥匙”。如果没有，则留空。)",
    "REMOVE_ITEM_FROM_INVENTORY": "(如果玩家在此回合消耗或失去了物品，请在此处写下物品的名称。例如：“火把”。如果没有，则留空。)",
    "UPDATE_QUEST_STATUS": "(如果任务状态有更新，请以“任务名: 任务新状态”的格式写在这里。例如：“寻找圣物: 你找到了关于圣物位置的线索。”。如果没有，则留空。)",
    "HP_CHANGE": "(玩家生命值的变化，正数为增加，负数为减少。例如：+10 或 -5。 如果没有变化，则留空。)",
    "SUGGESTED_CHOICES": [
        "(第一个行动建议)",
        "(第二个行动建议)",
        "(第三个行动建议)"        
    ]
}}
```
"""
    # 传递 game_session.active_ai_config，它可能是用户选择的配置，也可能是None
    ai_response_text = call_llm_api(prompt, active_config=game_session.active_ai_config)
    return parse_ai_output(ai_response_text)
