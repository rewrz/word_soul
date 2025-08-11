import re
from typing import Dict, Any, Tuple, List

class AICorrectorService:
    """
    一个用于校验和修正AI生成内容的后处理服务。
    它充当AI输出和游戏状态更新之间的“总编”和“事实核查员”。
    """
    def __init__(self, game_session):
        self.session = game_session
        self.current_state = game_session.current_state
        self.setting_pack = game_session.world.setting_pack

    def validate_and_correct(self, ai_response: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        执行一个完整的校验和修正流程。
        返回修正后的AI响应和发现的错误列表。
        """
        errors = []

        # 步骤 1: 语义和逻辑校验 (Rule-Based Validation)
        # 这是比JSON格式校验更深一层的检查。
        narrative_errors = self._validate_narrative_consistency(ai_response.get('description', ''))
        errors.extend(narrative_errors)

        suggestion_errors = self._validate_suggestions_consistency(ai_response.get('suggested_choices', []))
        errors.extend(suggestion_errors)

        # 步骤 2: 状态变更校验
        # 检查AI建议的状态变更是否符合世界规则。
        state_change_errors = self._validate_state_changes(ai_response)
        errors.extend(state_change_errors)

        # 步骤 3: 内容修正 (Correction)
        # 如果发现错误，可以尝试修正或标记。
        # 目前，我们主要记录错误，复杂的修正可能需要重新调用AI。
        if errors:
            print(f"[AI修正服务] 在会话 {self.session.id} 中发现不一致: {errors}")
            # 可以在这里添加逻辑，如果错误严重，则触发AI重新生成。
            # 例如: ai_response['description'] = "世界之灵似乎走神了，请你重述一遍你的行动。"
        
        return ai_response, errors

    def _validate_narrative_consistency(self, narrative: str) -> List[str]:
        """
        校验叙事描述是否与世界观和当前状态一致。
        使用更灵活的规则，并支持从 setting_pack 中动态加载规则。
        """
        errors = []
        # 提前获取并小写化，以备不区分大小写的比较
        narrative_lower = narrative.lower()
        original_location = self.current_state.get('current_location', '')
        current_location_lower = original_location.lower()

        # 1. 动态加载和应用禁用词规则
        forbidden_word_rules = self.setting_pack.get('narrative_rules', {}).get('forbidden_words', [])
        for rule in forbidden_word_rules:
            word = rule.get('word')
            if not word:
                continue
            # 使用小写进行不区分大小写的检查
            if word.lower() in narrative_lower:
                message = rule.get('message', f"叙事中出现了禁用词: '{word}'")
                errors.append(message)

        # 示例2: 检查叙事是否与玩家状态矛盾。
        # 例如，玩家明明在“霓虹小巷”，AI却说“你在森林里”。
        location_rules = self.setting_pack.get('narrative_rules', {}).get('location_rules', [])
        for rule in location_rules:
            required_location = rule.get('required_location')
            forbidden_location = rule.get('forbidden_location')
            message = rule.get('message')

            if required_location and required_location.lower() not in current_location_lower and required_location.lower() in narrative_lower:
                errors.append(message or f"叙事提到了'{required_location}'，但玩家当前位置'{original_location}'不包含该地点。")

            if forbidden_location and forbidden_location.lower() in current_location_lower and forbidden_location.lower() in narrative_lower:
                errors.append(message or f"叙事提到了'{forbidden_location}'，但玩家当前位置'{original_location}'包含该禁用地点。")

        return errors

    def _validate_suggestions_consistency(self, suggestions: List[Dict]) -> List[str]:
        """校验AI的行动建议是否合理、可行。"""
        errors = []
        if not isinstance(suggestions, list):
            return [] # 如果格式不对，直接返回，避免后续错误

        # 将可用技能和物品名称转换为小写集合，以便快速、不区分大小写地查找
        available_skills_lower = {s['名称'].lower() for s in self.setting_pack.get('skills', []) if '名称' in s}
        inventory_items_lower = {item.lower() for item in self.current_state.get('inventory', [])}

        for suggestion in suggestions:
            command = suggestion.get('action_command', '')
            if not command:
                continue

            # 示例1: 建议使用的技能是否存在？
            skill_match = re.search(r"使用\s+(.+)", command)
            if skill_match:
                entity_name = skill_match.group(1).strip()
                if entity_name.lower() not in available_skills_lower and entity_name.lower() not in inventory_items_lower:
                    errors.append(f"AI建议了不存在的技能或物品: '{entity_name}'")

            # 示例2: 建议交谈的NPC是否在场景中？
            talk_match = re.search(r"(与|和)\s+(.+?)\s+交谈", command)
            if talk_match:
                npc_name = talk_match.group(2).strip()
                # 将场景中的NPC名称也转换为小写集合进行比较
                scene_npcs_lower = {
                    n['名称'].lower() for n in self.setting_pack.get('npcs', [])
                    if n.get('位置') == self.current_state.get('current_location') and '名称' in n
                }
                if npc_name.lower() not in scene_npcs_lower:
                    errors.append(f"AI建议与不在场的NPC '{npc_name}' 交谈。")

        return errors

    def _validate_state_changes(self, ai_response: Dict[str, Any]) -> List[str]:
        """校验AI建议的状态变更是否符合规则。"""
        errors = []

        # 预处理，创建小写集合以便高效、不区分大小写地查找
        defined_items_lower = {
            name.lower() for item in self.setting_pack.get("items", [])
            if (name := item.get("名称")) and isinstance(name, str)
        }
        defined_tasks_lower = {
            name.lower() for task in self.setting_pack.get("tasks", [])
            if (name := task.get("名称")) and isinstance(name, str)
        }
        inventory_items_lower = {item.lower() for item in self.current_state.get('inventory', [])}

        # 校验: AI是否试图添加一个不存在于设定集中的物品？
        item_to_add = ai_response.get('add_item_to_inventory')
        if item_to_add and item_to_add.lower() not in defined_items_lower:
            errors.append(f"AI试图添加一个未在世界设定中定义的物品: '{item_to_add}'")

        # 校验: AI是否试图移除一个不存在于设定集中或玩家没有的物品？
        item_to_remove = ai_response.get('remove_item_from_inventory')
        if item_to_remove:
            if item_to_remove.lower() not in defined_items_lower:
                errors.append(f"AI试图移除一个未在世界设定中定义的物品: '{item_to_remove}'")
            elif item_to_remove.lower() not in inventory_items_lower:
                # 这是一个逻辑一致性错误，而不是定义错误
                errors.append(f"AI试图移除玩家并不拥有的物品: '{item_to_remove}'")

        # 校验: AI是否试图更新一个不存在的任务？
        quest_update_str = ai_response.get("update_quest_status")
        if quest_update_str and isinstance(quest_update_str, str):
            parts = quest_update_str.split(":", 1)
            if len(parts) == 2:
                quest_name = parts[0].strip()
                # 修复：确保quest_name不为None再调用lower方法
                if quest_name and quest_name.lower() not in defined_tasks_lower:
                    errors.append(f"AI试图更新一个不存在的任务: '{quest_name}'")
                elif not quest_name:
                    errors.append("AI试图更新任务，但任务名为空")

        # 校验: AI是否试图创建一个已经存在的任务？
        new_quest_data = ai_response.get("create_new_quest")
        if isinstance(new_quest_data, dict) and '名称' in new_quest_data:
            quest_name = new_quest_data['名称']
            # 修复：确保quest_name不为None再调用lower方法
            if quest_name and quest_name.lower() in defined_tasks_lower:
                errors.append(f"AI试图创建一个已经存在的任务: '{quest_name}'")
            elif not quest_name:
                errors.append("AI试图创建任务，但任务名为空")

        return errors


def use_rule_engine_for_validation(game_session, ai_response):
    """
    【进阶思路】使用规则引擎进行校验。
    这比手写if-else更灵活、更易于扩展。
    你可以使用像 `pyknow` 或 `durable_rules` 这样的库。

    1. 定义规则 (e.g., IF world is 'Cyberpunk' AND narrative contains 'Magic' -> THEN raise InconsistencyError).
    2. 将 game_session 和 ai_response 作为“事实”(Facts) 输入引擎。
    3. 运行引擎，收集所有触发的错误。
    """
    pass # 此处为伪代码，具体实现取决于所选的规则引擎库。