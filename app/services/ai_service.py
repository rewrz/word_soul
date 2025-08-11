import os
import re
import requests
import time
import traceback
from urllib.parse import urljoin
import json
import logging
from app.services.framework_validator import (
    validate_attribute_dimensions,
    validate_items,
    validate_skills,
    validate_npcs,
    validate_tasks,
)
from flask import current_app
from sqlalchemy.orm.attributes import flag_modified


from app.models import Setting, GameSession

logger = logging.getLogger(__name__)

def parse_ai_output(text):
    """
    一个健壮的解析器，用于处理AI返回的JSON格式文本。
    它会尝试去除常见的markdown代码块标记，例如 ```json ... ```。
    """
    print(f"原始AI输出: {text}")  # 打印原始AI输出

    # 增加处理逻辑，去除AI可能返回的markdown代码块标记。
    cleaned_text = text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]  # 去除 ```json
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}\n原始文本: {cleaned_text}")
        return {}


    # 将JSON的第一层键统一转换为小写，以增加容错性。
    data = {k.lower(): v for k, v in data.items()}

    return data

def _call_openai_api(prompt_text, api_key, base_url=None, model_name="gpt-4o-mini", max_retries=3, history=None):

    """调用OpenAI或兼容OpenAI的API（如Ollama）"""
    if base_url:
        # 对于本地模型或代理，将基础URL与API端点拼接
        # urljoin可以智能处理末尾是否有'/'的问题
        url = urljoin(base_url, "chat/completions")
    else:
        # 对于官方OpenAI，使用默认的完整URL
        url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 核心修复：构建正确的消息历史
    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt_text})
    payload = {
        "model": model_name or "gpt-4o-mini", "messages": messages, "temperature": 0.7,
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()  # 如果HTTP状态码是4xx或5xx，则抛出异常
            data = response.json()

            # 增加健壮性：检查API是否在JSON中返回了错误信息
            if 'error' in data:
                print(f"data_error:{data}")
                error_value = data['error']
                if isinstance(error_value, dict):
                    error_message = error_value.get('message', json.dumps(error_value))
                else:
                    error_message = str(error_value)
                logger.error(f"OpenAI API返回错误: {error_message}")
                return f"[错误] AI服务返回错误: {error_message}"
            
            return data['choices'][0]['message']['content']

        except requests.exceptions.RequestException as e:
            logger.warning(f"调用OpenAI API时出错: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # 简单的线性增加等待时间
                logger.warning(f"正在重试... ({attempt + 1}/{max_retries}). 等待 {wait_time} 秒.")
                time.sleep(wait_time)
                continue # 继续下一次循环
            else:
                logger.error(f"调用OpenAI API在 {max_retries} 次重试后仍然失败。")
                return "[错误] AI服务暂时无法连接。"
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"解析OpenAI API响应时出错: {e}", exc_info=True)
            return "[错误] AI服务返回了意料之外的数据格式或无效的JSON。"

    return "[错误] AI服务在所有重试后均未能成功调用。"

def _call_gemini_api(prompt_text, api_key, model_name="gemini-1.5-flash", max_retries=3, history=None):
    """调用Google Gemini API"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name or 'gemini-1.5-flash'}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    # 核心修复：为Gemini构建正确的contents历史
    contents = []
    if history:
        # Gemini的role是'user'和'model'
        for entry in history:
            role = 'model' if entry['role'] == 'assistant' else 'user'
            contents.append({"role": role, "parts": [{"text": entry['content']}]})
    contents.append({"role": "user", "parts": [{"text": prompt_text}]})

    payload = {
        "contents": contents
    }
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            # 增加健壮性：检查Gemini特有的错误格式
            if not data.get('candidates'):
                error_info = data.get('promptFeedback', '未知错误')
                logger.error(f"Gemini API 返回错误: {error_info}")
                return f"[错误] AI服务返回错误: {error_info}"

            return data['candidates'][0]['content']['parts'][0]['text']
        except requests.exceptions.RequestException as e:
            logger.warning(f"调用Gemini API时出错: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                logger.warning(f"正在重试... ({attempt + 1}/{max_retries}). 等待 {wait_time} 秒.")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"调用Gemini API在 {max_retries} 次重试后仍然失败。")
                return "[错误] AI服务暂时无法连接。"
        except (KeyError, IndexError) as e:
            logger.exception(f"解析Gemini API响应时出错: {e}。收到的原始数据: {data}")
            return "[错误] AI服务返回了意料之外的数据格式。"
        except json.JSONDecodeError:
            logger.error(f"解析Gemini API响应时出错: 无法解码JSON。收到的原始文本: {response.text}")
            return "[错误] AI服务返回了非JSON格式的响应。"
    return "[错误] AI服务在所有重试后均未能成功调用。"

def _call_claude_api(prompt_text, api_key, model_name="claude-3-haiku-20240307", max_retries=3, history=None):
    """调用Anthropic Claude API"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    # 核心修复：构建正确的消息历史
    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt_text})

    payload = {
        "model": model_name or "claude-3-haiku-20240307",
        "max_tokens": 2048, "messages": messages
    }
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            # 增加健壮性：检查Claude特有的错误格式
            if data.get('type') == 'error':
                error_message = data.get('error', {}).get('message', str(data.get('error')))
                logger.error(f"Claude API 返回错误: {error_message}")
                return f"[错误] AI服务返回错误: {error_message}"

            return data['content'][0]['text']
        except requests.exceptions.RequestException as e:
            logger.warning(f"调用Claude API时出错: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                logger.warning(f"正在重试... ({attempt + 1}/{max_retries}). 等待 {wait_time} 秒.")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"调用Claude API在 {max_retries} 次重试后仍然失败。")
                return "[错误] AI服务暂时无法连接。"
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"解析Claude API响应时出错: {e}", exc_info=True)
            return "[错误] AI服务返回了意料之外的数据格式或无效的JSON。"
    return "[错误] AI服务在所有重试后均未能成功调用。"


def call_llm_api(prompt_text, active_config=None, history=None):

    """
    AI调用分发器。
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
        return _call_openai_api(prompt_text, api_key, base_url, model_name or "gpt-4o-mini", history=history)

    elif provider == 'gemini':
        if not api_key: return "[错误] 缺少 Gemini API Key。"
        return _call_gemini_api(prompt_text, api_key, model_name, history=history)

    elif provider == 'claude':
        if not api_key: return "[错误] 缺少 Claude API Key。"
        return _call_claude_api(prompt_text, api_key, model_name, history=history)

    else:
        return f"[错误] 不支持的AI提供商: {provider}。"


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
- **重要**: 所有字段的值都必须是**字符串 (string)**。对于像"世界规则"这样复杂的内容，请将其全部写入一个单一的、详细的字符串中，**不要**使用嵌套的JSON对象。
- **特别重要**: 你必须始终提供一个非空的world_name（此界之名）字段，这是创建世界的必要条件。

# 用户输入
{formatted_input}

# 你的输出
请严格按照以下格式，为每个字段生成或完善内容。确保你的输出是一个完整的、可以直接用于创建游戏世界的设定集，不要输出多余的内容。所有字段的值都必须是字符串。

```json
{{
    "world_name": "(生成一个独特且富有吸引力的故事名称，要足够吸睛和劲爆，一般是故事的核心升华，使用浮夸和猎奇的手法引起玩家的好奇)",
    "character_description": "(关键角色的具体描述，包括主要男女主角（如有）、主要配角（如有）、主要反派角色（如有）等影响整个故事发展的关键角色要点介绍，禁止使用神秘的、古老的、未知的等模糊描述)",
    "world_rules": "(一个**单一的字符串**，概括这个世界主要讲了一个什么故事，采用线性的叙事结构，融合主线、支线、伏笔\暗线、感情线的完整线性故事发展，至少要有一个惊天的大反转，例如玄幻世界里一个废物主角逆袭成为人人爱慕的宇宙帝王等，根据世界观背景类型以及故事内容所需而定，例如力量体系或技能体系或装备体系或门派体系等方面，力量等级要清晰，不同等级的差距和特点需明确描述。主角所使用的技能要罗列并注解其威力和影响，装备的获取方式、效果等也要详细设定。比如在仙侠世界中，设定从练气到飞升的多个力量等级，每个等级的能力和突破条件都不同)",
    "initial_scene": "(描绘一个具体的开场画面，也是主角的初始场景，至少要描述该场景的背景、关键事件、关键角色（若有）、关键物品（若有）、关键任务（若有）等。)",
    "narrative_principles": "(设定一个清晰的故事基调，例如：现代都市、架空奇幻、未来科幻、末世、言情、修仙、玄幻、魔法奇幻、轻小说等)"
}}
```
"""

    # 获取AI配置
    ai_config = active_config or Setting.query.filter_by(is_global=True).first()
    if not ai_config:
        return {"error": "未找到有效的AI配置。请先设置AI配置。"}

    # 调用AI
    response_text = call_llm_api(prompt, active_config)

    # 检查是否有错误
    if response_text.startswith("[错误]"):
        return {"world_name": response_text}

    # 尝试解析JSON
    try:
        # 提取JSON部分
        json_match = re.search(r'```json\s*({[\s\S]*?})\s*```', response_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'{[\s\S]*?}', response_text)
            if json_match:
                json_str = json_match.group(0)
            else:
                return {"world_name": "[错误] AI未能生成有效的JSON格式响应。"}

        # 解析JSON
        assisted_data = json.loads(json_str)

        # 确保world_name字段不为空
        if not assisted_data.get("world_name"):
            # 如果用户提供了world_name，则使用用户的输入
            if world_name:
                assisted_data["world_name"] = world_name
            else:
                # 否则生成一个默认的world_name
                assisted_data["world_name"] = "未命名世界_" + str(int(time.time()))

        # 映射字段名称
        return {
            "world_name": assisted_data.get("world_name", ""),
            "character_description": assisted_data.get("character_description", ""),
            "world_rules": assisted_data.get("world_rules", ""),
            "initial_scene": assisted_data.get("initial_scene", ""),
            "narrative_principles": assisted_data.get("narrative_principles", "")
        }
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        print(f"原始响应: {response_text}")
        return {"world_name": f"[错误] AI生成的响应无法解析为JSON: {str(e)}"}
    except Exception as e:
        print(f"处理AI响应时发生错误: {e}")
        return {"world_name": f"[错误] 处理AI响应时发生错误: {str(e)}"}



def _generate_world_meta(world_keywords, player_description, active_config, previous_errors=None):
    """
    第一步：生成世界的核心元数据（名称、描述等）。
    """
    correction_prompt_part = ""
    if previous_errors:
        error_string = "\n- ".join(previous_errors)
        correction_prompt_part = f"""
# 上次尝试失败 (Last Attempt Failed)
你上次生成的JSON未能通过校验。错误如下:
- {error_string}
请修正这些错误，并重新生成。
"""
    prompt = f"""
{correction_prompt_part}
你是一个世界观架构师。根据用户提供的关键词，生成一个游戏世界的核心设定。

# 用户输入
- 世界关键词: {world_keywords}
- 玩家角色描述: {player_description}

# 你的任务
生成一个JSON对象，包含以下字段：
- `world_name`: (string) 这个世界的故事名称。
- `world_description`: (string) 对这个世界的整体风格、背景和核心冲突的简要描述。
- `player_character_description`: (string) 基于用户描述，润色后的玩家角色背景故事和初始状态。
- `initial_scene`: (string) 游戏开始时的场景描述，需要引人入胜，并提供明确的起点。
- `narrative_principles`: (string) 故事的基调，例如：黑暗奇幻、赛博朋克、英雄史诗等。

```json
{{
  "world_name": "(一个符合世界关键词的独特名称)",
  "world_description": "(一段关于世界背景、风格和核心冲突的描述)",
  "player_character_description": "(基于用户输入，润色后的玩家角色背景故事)",
  "initial_scene": "(一个引人入胜的游戏开场场景描述)",
  "narrative_principles": "(一个清晰的故事基调，例如：黑暗奇幻、赛博朋克等)"
}}
```
"""
    response_text = call_llm_api(prompt, active_config)
    return parse_ai_output(response_text)

def _generate_attributes(setting_pack, active_config, previous_errors=None):
    """
    第二步：生成属性维度。
    """
    correction_prompt_part = ""
    if previous_errors:
        error_string = "\n- ".join(previous_errors)
        correction_prompt_part = f"""
# 上次尝试失败
你上次生成的JSON未能通过校验。错误如下:
- {error_string}
请修正这些错误，并重新生成。
"""
    prompt = f"""
{correction_prompt_part}
你是一个游戏设计师。根据已有的世界观设定，为游戏角色设计核心属性。

# 世界观设定参考
- 故事基调: {setting_pack.get('narrative_principles', '未知')}
- 世界描述: {setting_pack.get('world_description', '未知')}
- 玩家角色: {setting_pack.get('player_character_description', '未知')}

# 你的任务
生成一个JSON对象 `attribute_dimensions`。
- 必须包含“生存”、“输出”、“资源”三个维度。
- 可以有可选的“防御”和“辅助”维度。
- 在“辅助”维度中，请务必定义一个用于交易的**货币**属性。
- 每个维度都是一个对象，包含 "name" (string) 和 "initial_value" (number)。

```json
{{
  "attribute_dimensions": {{
    "生存": {{ "name": "生命值", "initial_value": 100 }},
    "输出": {{ "name": "攻击力", "initial_value": 10 }},
    "资源": {{ "name": "法力值", "initial_value": 50 }},
    "防御": {{ "name": "护甲", "initial_value": 5 }},
    "辅助": {{ "name": "金币", "initial_value": 20 }}
  }}
}}
```
"""
    response_text = call_llm_api(prompt, active_config)
    return parse_ai_output(response_text)


def _generate_content_modules(world_keywords, player_description, setting_pack, active_config, previous_errors=None):
    """
    第三步：基于已定义的世界观和属性，生成物品、技能、NPC和任务。
    """
    correction_prompt_part = ""
    if previous_errors:
        error_string = "\n- ".join(previous_errors)
        correction_prompt_part = f"""
# 上次尝试失败
你上次生成的JSON未能通过校验。错误如下:
- {error_string}
请仔细阅读并修正这些错误，然后重新生成 `items`, `skills`, `npcs`, `tasks` 模块。
"""
    # 将已有的设定包转换为字符串，作为上下文提供给AI
    context_str = json.dumps(setting_pack, ensure_ascii=False, indent=2)
    
    # 从设定包中提取有效的属性名称列表，用于在提示中明确告知AI
    valid_attribute_names = [dim["name"] for dim in setting_pack.get("attribute_dimensions", {}).values()]
    valid_names_str = ", ".join(f"'{name}'" for name in valid_attribute_names)
    resource_name = setting_pack.get("attribute_dimensions", {}).get("资源", {}).get("name", "未知资源")

    prompt = f"""
{correction_prompt_part}
你是一个资深游戏内容设计师。你的任务是基于已有的世界设定和属性框架，创建游戏中的具体内容，包括物品、技能、NPC和任务。

# 已有设定 (Existing Blueprint)
```json
{context_str}
```

# 关键规则 (CRITICAL RULE) - 你必须严格遵守！
1.  **严格对应**: 所有 `效果` 和 `消耗` 字符串中使用的**属性名**，都**必须**从以下列表中选取: {valid_names_str}。
2.  **消耗对应**: `消耗` 字符串中的属性名，**必须**是 '{resource_name}'。
3.  **商人与敌人**: 你必须创建至少一个商人NPC，并为其 `售卖物品` 列表添加一些你在物品库中定义的、有价格的物品。同时，必须创建一个可供战斗的敌对NPC (`is_hostile: true`)。

# 你的任务
按照设定，生成一个符合设定逻辑的JSON对象，包含 `items`, `skills`, `npcs`, `tasks` 四个模块，示例如下：

```json
{{
  "items": [
    {{
      "类型": "恢复类",
      "名称": "生命药水",
      "效果": ["{valid_attribute_names[0]} + 30"],
      "价格": 50,
      "获取": "商人处购买",
      "背景描述": "常见的恢复药剂。"
    }}
  ],
  "skills": [
    {{
      "类型": "伤害类",
      "名称": "强力一击",
      "消耗": "{resource_name} - 15",
      "效果": ["{valid_attribute_names[1]} * 1.5"],
      "冷却时间": 3
    }}
  ],
  "tasks": [
    {{
        "名称": "村庄的麻烦",
        "状态": "未开始",
        "目标": "调查村庄周围的哥布林踪迹。",
        "奖励": {{ "金币": 50 }}
    }}
  ],
  "npcs": [
    {{
      "名称": "RewrZ",
      "描述": "一个friendly的商人。",
      "位置": "{setting_pack.get('initial_scene', '未知')}",
      "对话样本": "需要点什么吗？",
      "attributes": {{ "{valid_attribute_names[0]}": 100, "{valid_attribute_names[1]}": 5 }},
      "is_hostile": false,
      "售卖物品": ["生命药水"]
    }},
    {{
      "名称": "XXX",
      "描述": "一个鬼鬼祟祟的哥布林。",
      "位置": "{setting_pack.get('initial_scene', '未知')}",
      "对话样本": "滚开，人类！",
      "attributes": {{ "{valid_attribute_names[0]}": 80, "{valid_attribute_names[1]}": 12 }},
      "is_hostile": true
    }}
  ]
}}
```
"""
    response_text = call_llm_api(prompt, active_config)
    return parse_ai_output(response_text)


def _validate_meta(data):
    """简单的元数据校验器"""
    errors = []
    if not data:
        return False, ["AI未能生成元数据。"]

    required_keys = ["world_name", "world_description", "player_character_description", "initial_scene", "narrative_principles"]
    for key in required_keys:
        if key not in data:
            errors.append(f"元数据缺少必需的键: '{key}'")
        elif not isinstance(data[key], str) or not data[key].strip():
            errors.append(f"元数据键 '{key}' 的值必须是一个非空的字符串。")
    return not errors, errors
def generate_setting_pack(
    active_ai_config_id,
    world_keywords=None,
    player_description=None,
    initial_settings=None
):
    """
    调用大模型，根据用户关键词生成结构化的“动态设定包”。
    """
    # 根据传入的ID从数据库获取具体的AI配置
    active_config = None
    if active_ai_config_id:
        active_config = Setting.query.get(active_ai_config_id)

    # --- 分步生成与独立校验/重试 ---
    max_retries_per_step = 3
    setting_pack = {}

    # 步骤 1: 处理世界元数据
    if initial_settings:
        # 情况A：使用前端提供的、用户已确认的元数据
        print("--- 创世咏唱[1/3]: 使用用户提供的元数据 ---")
        is_valid, errors = _validate_meta(initial_settings)
        if not is_valid:
            return {"error": "提供的元数据校验失败。", "details": errors}
        setting_pack.update(initial_settings)
    elif world_keywords:
        # 情况B（备用）：从关键词开始生成元数据
        last_errors = []
        for attempt in range(max_retries_per_step):
            print(f"--- 创世咏唱[1/3]: 生成世界元数据 (尝试 {attempt + 1}/{max_retries_per_step}) ---")
            meta_data = _generate_world_meta(world_keywords, player_description, active_config, previous_errors=last_errors)
            is_valid, last_errors = _validate_meta(meta_data)
            if is_valid:
                setting_pack.update(meta_data)
                break
            else:
                print(f"--- 元数据校验失败: {last_errors} ---")
        else: # for...else, 循环正常结束（未被break）时执行
            return {"error": "AI在生成世界元数据时多次失败。", "details": last_errors}
    else:
        # 两种必要输入都没有提供
        return {"error": "无法创建世界：必须提供完整的初始设定或背景关键词。"}

    # 步骤 2: 生成并校验属性维度
    last_errors = []
    for attempt in range(max_retries_per_step):
        print(f"--- 创世咏唱[2/3]: 生成属性维度 (尝试 {attempt + 1}/{max_retries_per_step}) ---")
        # 使用已有的setting_pack作为上下文，而不是简单的关键词
        attr_data = _generate_attributes(setting_pack, active_config, previous_errors=last_errors)
        if not attr_data or "attribute_dimensions" not in attr_data:
             last_errors = ["AI未能生成'attribute_dimensions'模块。"]
             continue
        last_errors = validate_attribute_dimensions(attr_data["attribute_dimensions"])
        if not last_errors:
            setting_pack.update(attr_data)
            break
        else:
            print(f"--- 属性维度校验失败: {last_errors} ---")
    else:
        return {"error": "AI在生成属性维度时多次失败。", "details": last_errors}

    # 步骤 3: 生成并校验游戏内容模块
    last_errors = []
    for attempt in range(max_retries_per_step):
        print(f"--- 创世咏唱[3/3]: 生成游戏内容模块 (尝试 {attempt + 1}/{max_retries_per_step}) ---")
        content_modules = _generate_content_modules(None, None, setting_pack, active_config, previous_errors=last_errors)
        if not content_modules:
            last_errors = ["AI未能生成内容模块。"]
            continue
        
        # 为确保校验完整性，即使AI遗漏了某个模块，也用空列表代替
        item_errors = validate_items(content_modules.get("items", []), setting_pack["attribute_dimensions"])
        skill_errors = validate_skills(content_modules.get("skills", []), setting_pack["attribute_dimensions"])
        npc_errors = validate_npcs(content_modules.get("npcs", []), setting_pack["attribute_dimensions"])
        task_errors = validate_tasks(content_modules.get("tasks", []))
        last_errors = item_errors + skill_errors + npc_errors + task_errors
        if not last_errors:
            setting_pack.update(content_modules)
            break
        else:
            print(f"--- 内容模块校验失败: {last_errors} ---")
    else:
        print(f"AI在生成游戏内容模块时多次失败:{last_errors}")
        return {"error": "AI在生成游戏内容模块时多次失败。", "details": last_errors}

    return setting_pack

def format_json_like_string(json_string):
    """
    尝试将类似JSON的字符串格式化为标准JSON格式。
    这包括修复缺失的引号、括号等。
    """
    # 当前实现比较简单，直接返回字符串
    # TODO: 添加更复杂的修复逻辑
    return json_string

def _prepare_common_context(setting_pack, current_state, player_action, action_was_unparsed):
    """辅助函数：准备一个包含所有通用上下文的字典，供后续步骤使用。"""
    context = {
        'narrative_principles': setting_pack.get('narrative_principles', '一个开放、自由的沙盒世界'),
        'world_description': setting_pack.get('world_description', '一个神秘的世界'),
        'player_character_description': current_state.get('player_character', '未知'),
        'current_location': current_state.get('current_location', '未知之地'),
        'player_action': player_action,
        'action_was_unparsed': action_was_unparsed
    }

    # 动态构建属性字符串
    attributes_list = [f"  - {name}: {value}" for name, value in current_state.get('attributes', {}).items()]
    context['attributes_str'] = "\n".join(attributes_list) or "无"

    # 构建物品、技能、NPC等上下文
    context['inventory'] = ", ".join(current_state.get('inventory', [])) or "无"
    
    usable_items = [item_name for item_name in current_state.get('inventory', []) if next((item for item in setting_pack.get('items', []) if item['名称'] == item_name and item.get('效果')), None)]
    context['usable_items_str'] = ", ".join(usable_items) or "无"

    available_skills = [skill.get('名称') for skill in setting_pack.get('skills', []) if skill.get('名称') and skill.get('名称') not in current_state.get('cooldowns', {})] 
    context['available_skills_str'] = ", ".join(available_skills) or "无"

    scene_npcs = [f"{npc.get('名称')} ({npc.get('描述', '无可用描述')})" for npc in setting_pack.get('npcs', []) if npc.get('位置') == context['current_location']]
    context['scene_npcs_str'] = "、".join(scene_npcs) or "无"

    # 核心修复：准备结构化的历史记录，并将其倒序以符合API的时间顺序要求。
    # 同时，将内部使用的 'player' 角色映射为AI API可接受的 'user' 角色。
    raw_history = current_state.get('recent_history', [])
    
    # API需要按时间顺序排列的历史记录 (旧->新)，所以我们先反转。
    # 同时使用列表推导式来映射角色，确保发送给API的角色是 'user' 或 'assistant'。
    api_history = [
        {'role': 'user' if entry.get('role') == 'player' else entry.get('role'), 'content': entry.get('content')}
        for entry in reversed(raw_history)
    ]
    context['history_for_api'] = api_history

    # 构建特定行动的上下文
    context['focus_target'] = current_state.get('focus_target')
    context['talk_target_name'] = current_state.get('talk_target')
    context['give_info'] = current_state.get('give_info')
    context['buy_info'] = current_state.get('buy_info')
    context['sell_info'] = current_state.get('sell_info')

    return context


def _generate_narrative_description(context, active_config):
    """第一步：只生成故事描述。"""
    prompt = f"""
你是一位名为“世界之灵”的游戏主持人，你的唯一职责是**讲故事**。
根据玩家的行动和当前世界状态，生动地描述接下来发生的事情。

# 核心准则
- **绝对沉浸**: 绝不承认自己是AI。以游戏角色的口吻巧妙回避无关问题。
- **动态引导**: 尊重玩家选择，但通过剧情温和地引导。
- **职责分离**: 你只负责叙事，**不要**进行数值计算或思考游戏规则。

# 世界设定
- **故事基调**: {context['narrative_principles']}
- **世界设定或故事主线**: {context['world_description']}
- **关键角色设定**: {context['player_character_description']}

# 当前状态
- **位置**: {context['current_location']}
- **场景中的NPC**: {context['scene_npcs_str']}
- **玩家当前属性**: \n{context['attributes_str']}
- **持有物品**: {context['inventory']}

# 玩家当前行动指令
玩家: {context['player_action']}

# 你的任务
- 作为故事的叙述者，请根据玩家的行动指令，简短说明玩家行动指令发生的情节，例如事件发展变化、到了新的场景、NPC的反应等。
- 确保你的回复能够让玩家有更好的体验，并使玩家能够理解故事中的内容。
- 如果场景陷入沉闷，请主动引入新事件（例如：NPC出现、触发新事件、有新发现等）来推进故事。
- **必须执行玩家行动指令，严格按照世界设定或故事主线以及角色设定来生成剧情，严禁偏离。**

**你的输出只能是纯文本的故事情节，就像在写网络小说一样，请勿输出任何其他内容。**
"""
    response_text = call_llm_api(prompt, active_config, history=context['history_for_api'])
    # 简单检查错误，如果出错则直接返回错误信息
    if not response_text or response_text.strip().startswith("[错误]"):
        return response_text or "[错误] AI叙事模块未能生成内容。"
    return response_text

def _analyze_narrative_for_state_changes(narrative_text, context, active_config):
    """第二步：从故事描述中解析游戏状态变更。"""
    prompt = f"""
你是一个严谨的游戏逻辑分析器。你的任务是阅读一段游戏剧情，并从中提取出所有需要更新的游戏状态。

# 游戏剧情描述
```text
{narrative_text}
```

# 你的任务
根据以上剧情，分析是否发生了以下事件，并严格按照JSON格式输出。
如果某个事件没有发生，请让对应的值为 null 或空字符串。

1.  **玩家信息 (PLAYER_MESSAGE)**: 剧情中是否有给玩家的直接提示或状态提醒？（例如“你感到一阵寒意。”）
2.  **获得物品 (ADD_ITEM_TO_INVENTORY)**: 剧情是否明确描述玩家获得了某个物品？
3.  **失去物品 (REMOVE_ITEM_FROM_INVENTORY)**: 剧情是否明确描述玩家消耗、损坏或失去了某个物品？
4.  **位置变更 (UPDATE_LOCATION)**: 剧情是否描述玩家移动到了一个新地点？
5.  **任务更新 (UPDATE_QUEST_STATUS)**: 剧情是否暗示某个任务的状态发生了变化？（格式："任务名: 新状态"）
6.  **创建新任务 (CREATE_NEW_QUEST)**: 剧情是否自然地引出了一个全新的任务？如果是，请定义任务的名称、目标和奖励。

# 输出格式
```json
{{
    "PLAYER_MESSAGE": "(字符串)",
    "ADD_ITEM_TO_INVENTORY": "(字符串, 物品名)",
    "REMOVE_ITEM_FROM_INVENTORY": "(字符串, 物品名)",
    "UPDATE_LOCATION": "(字符串, 新地点名)",
    "UPDATE_QUEST_STATUS": "(字符串, '任务名: 新状态')",
    "CREATE_NEW_QUEST": {{
        "名称": "(字符串)",
        "目标": "(字符串)",
        "奖励": "(字符串或对象)"
    }}
}}
```
"""
    response_text = call_llm_api(prompt, active_config)
    return parse_ai_output(response_text)

def _generate_action_suggestions(narrative_text, context, active_config):
    """第三步：根据新情景生成行动建议。"""
    prompt = f"""
你是一位聪明的游戏向导。你的任务是根据当前的场景和玩家状态，为玩家提供有趣且合理的行动建议。

# 当前场景描述
```text
{narrative_text}
```

# 玩家当前状态
- **位置**: {context['current_location']}
- **场景中的NPC**: {context['scene_npcs_str']}
- **可用物品**: {context['usable_items_str']}
- **可用技能**: {context['available_skills_str']}

# 你的任务
- 生成2-4个多样化且符合逻辑的行动建议（例如：与环境互动、与NPC交谈、使用物品/技能或表达个人意图等）。
- **请务必严格按照世界设定和角色设定来生成行动建议，严禁偏离。**

# 输出格式
请严格按照以下JSON格式输出一个对象，其中包含一个名为 `SUGGESTED_CHOICES` 的列表。
- `display_text`: 给玩家看的描述性文本。
- `action_command`: 给程序执行的、格式化的命令。如果建议是程序可解析的行动（如使用物品/技能、与NPC交谈等），请务必提供此字段并确保格式正确。

```json
{{
    "SUGGESTED_CHOICES": [
        {{
            "display_text": "(一个简短的行动建议，例如：'你决定使用金疮药治疗伤口。')",
            "action_command": "使用 金疮药"
        }},
        {{
            "display_text": "(另一个简短的行动建议，例如：'你仔细观察周围的环境。')",
            "action_command": "观察 周围"
        }},
        {{
            "display_text": "(一个纯叙事的行动，例如：'你决定保持警惕，静观其变。')",
            "action_command": "保持警惕"
        }}
    ]
}}
```
"""
    response_text = call_llm_api(prompt, active_config)
    return parse_ai_output(response_text)

def generate_game_master_response(setting_pack, current_state, player_action, game_session, action_was_unparsed=False):
    """
    调用AI生成游戏剧情（三步流水线）。
    """
    # 1. 准备通用上下文
    context = _prepare_common_context(setting_pack, current_state, player_action, action_was_unparsed)
    active_config = game_session.active_ai_config

    # 2. 生成叙事描述
    narrative_text = _generate_narrative_description(context, active_config)
    if narrative_text.strip().startswith("[错误]"):
        return {"error": narrative_text}

    # 3. 分析状态变更
    state_changes = _analyze_narrative_for_state_changes(narrative_text, context, active_config)

    # 4. 生成行动建议
    action_suggestions = _generate_action_suggestions(narrative_text, context, active_config)

    # 5. 合并结果
    ai_response = {
        "description": narrative_text,
        **state_changes,
        **action_suggestions
    }
    return ai_response
