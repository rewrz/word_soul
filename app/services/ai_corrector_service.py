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
        # 如果发现错误，尝试自动修复或重新生成
        if errors:
            print(f"[AI修正服务] 在会话 {self.session.id} 中发现不一致: {errors}")
            
            # 对AI响应进行自动修复
            ai_response = self._auto_fix_errors(ai_response, errors)
            
            # 检查是否有严重错误需要重新生成
            if self._has_critical_errors(errors):
                # 触发重新生成机制
                regenerated_response = self._regenerate_ai_response(ai_response, errors)
                if regenerated_response:
                    return regenerated_response, ["已重新生成响应以修复严重错误"]
        
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
        """校验AI的行动建议是否合理、可行。
        
        注意：为了支持动态游戏世界，我们允许AI建议使用新的技能和物品，
        但仍然对明显不合理的建议进行校验。
        """
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

            # 【修改】对于技能和物品使用，采用更宽松的校验策略
            skill_match = re.search(r"使用\s+(.+)", command)
            if skill_match:
                entity_name = skill_match.group(1).strip()
                # 只有当明确不在技能列表且不在物品栏时才报错
                # 但允许AI建议使用可能在游戏过程中获得的新技能或物品
                if (entity_name.lower() not in available_skills_lower and 
                    entity_name.lower() not in inventory_items_lower and
                    not self._is_plausible_dynamic_ability(entity_name)):
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
    
    def _is_plausible_dynamic_ability(self, ability_name: str) -> bool:
        """判断一个技能或物品名称是否是合理的动态能力。
        
        这个方法用于判断AI建议的技能或物品是否可能是在游戏过程中
        动态获得的，而不是明显的错误。
        """
        ability_lower = ability_name.lower()
        
        # 一些常见的动态技能/物品模式
        dynamic_patterns = [
            '影刃', '暗影', '光环', '护体', '位移',  # 常见的技能词汇
            '护符', '药水', '卷轴', '宝石', '符文',  # 常见的物品词汇
            '剑', '盾', '法杖', '弓', '匕首',        # 武器类
            '药', '丹', '符', '珠', '石'            # 消耗品类
        ]
        
        # 如果包含这些模式中的任何一个，认为是合理的动态能力
        for pattern in dynamic_patterns:
            if pattern in ability_lower:
                return True
                
        return False

    def _validate_state_changes(self, ai_response: Dict[str, Any]) -> List[str]:
        """校验AI建议的状态变更是否符合规则。
        
        注意：为了支持动态游戏世界，我们允许AI创建新的物品和技能，
        但仍然对明显的逻辑错误进行校验。
        """
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

        # 【修改】允许AI添加新物品 - 这是游戏过程中获得物品的正常逻辑
        # 不再校验物品是否在预定义列表中，因为游戏中可以动态获得新物品
        item_to_add = ai_response.get('add_item_to_inventory')
        if item_to_add:
            # 只检查基本的数据类型，不检查是否预定义
            if not isinstance(item_to_add, str) or not item_to_add.strip():
                errors.append(f"AI试图添加无效的物品: '{item_to_add}'")

        # 【修改】对于移除物品，只检查玩家是否真的拥有该物品
        item_to_remove = ai_response.get('remove_item_from_inventory')
        if item_to_remove:
            if item_to_remove.lower() not in inventory_items_lower:
                # 这是一个逻辑一致性错误 - 不能移除没有的物品
                errors.append(f"AI试图移除玩家并不拥有的物品: '{item_to_remove}'")

        # 【修改】对于任务更新，允许更新动态创建的任务
        quest_update_str = ai_response.get("update_quest_status")
        if quest_update_str and isinstance(quest_update_str, str):
            parts = quest_update_str.split(":", 1)
            if len(parts) == 2:
                quest_name = parts[0].strip()
                if not quest_name:
                    errors.append("AI试图更新任务，但任务名为空")
                # 不再检查任务是否预定义，允许更新动态创建的任务

        # 【修改】允许创建新任务，不检查是否已存在（可能是任务的不同阶段）
        new_quest_data = ai_response.get("create_new_quest")
        if isinstance(new_quest_data, dict) and '名称' in new_quest_data:
            quest_name = new_quest_data['名称']
            if not quest_name:
                errors.append("AI试图创建任务，但任务名为空")
            # 移除重复任务检查，允许任务的演化和分支

        # 【修改】对于属性更新，允许动态属性，但保持数值类型检查
        attribute_updates = ai_response.get("update_attributes")
        if isinstance(attribute_updates, dict):
            for attr_name, change_value in attribute_updates.items():
                # 只检查变化值是否为数字，不检查属性是否预定义
                if not isinstance(change_value, (int, float)):
                    errors.append(f"AI试图将属性'{attr_name}'的变化值设为非数字: '{change_value}'")
                # 允许动态属性的创建和更新

        return errors

    def _auto_fix_errors(self, ai_response: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
        """
        自动修复简单错误。
        根据错误类型和内容，尝试对AI响应进行自动修复。
        """
        # 创建一个响应的副本，以便进行修改
        fixed_response = ai_response.copy()
        
        # 处理物品相关错误
        for error in errors:
            # 修复：移除不存在的物品
            if "AI试图移除玩家并不拥有的物品" in error:
                # 从错误消息中提取物品名称
                item_match = re.search(r"AI试图移除玩家并不拥有的物品: '(.+?)'$", error)
                if item_match and 'remove_item_from_inventory' in fixed_response:
                    # 清除该物品的移除请求
                    fixed_response['remove_item_from_inventory'] = None
                    print(f"[自动修复] 已移除对不存在物品的移除请求: {item_match.group(1)}")
            
            # 【移除】不再阻止添加未定义的物品，因为支持动态物品系统
            # elif "AI试图添加一个未在世界设定中定义的物品" in error:
            #     # 允许动态物品，不再自动修复此类"错误"
            
            # 【移除】不再阻止更新动态任务，因为支持任务系统的动态演化
            # elif "AI试图更新一个不存在的任务" in error:
            #     # 允许动态任务更新，不再自动修复此类"错误"
            
            # 【移除】不再阻止创建重复任务，因为任务可能有多个阶段或分支
            # elif "AI试图创建一个已经存在的任务" in error:
            #     # 允许任务的演化和分支，不再自动修复此类"错误"
            
            # 【修改】对于技能和物品建议，采用更智能的修复策略
            elif "AI建议了不存在的技能或物品" in error:
                # 这种情况比较复杂，需要修改suggested_choices列表
                if 'suggested_choices' in fixed_response and isinstance(fixed_response['suggested_choices'], list):
                    entity_match = re.search(r"AI建议了不存在的技能或物品: '(.+?)'$", error)
                    if entity_match:
                        entity_name = entity_match.group(1)
                        # 只有当技能/物品名称明显不合理时才移除建议
                        if not self._is_plausible_dynamic_ability(entity_name):
                            # 过滤掉包含明显错误技能或物品的建议
                            original_count = len(fixed_response['suggested_choices'])
                            fixed_response['suggested_choices'] = [
                                choice for choice in fixed_response['suggested_choices']
                                if not (f"使用 {entity_name}" in choice.get('action_command', '') or
                                       entity_name in choice.get('action_command', ''))
                            ]
                            if len(fixed_response['suggested_choices']) < original_count:
                                print(f"[自动修复] 已移除包含不合理技能或物品的建议: {entity_name}")
            
            # 【移除】不再阻止更新未定义的属性，因为支持动态属性系统
            # elif "AI试图更新一个未在世界设定中定义的属性" in error:
            #     # 允许动态属性的创建和更新，不再自动修复此类"错误"
            
            # 修复：属性变化值为非数字
            elif "AI试图将属性" in error and "的变化值设为非数字" in error:
                attr_match = re.search(r"AI试图将属性'(.+?)'的变化值设为非数字: '(.+?)'$", error)
                if attr_match and 'update_attributes' in fixed_response:
                    attr_name = attr_match.group(1)
                    if isinstance(fixed_response['update_attributes'], dict):
                        # 移除非数字的属性更新
                        fixed_response['update_attributes'].pop(attr_name, None)
                        # 如果字典为空，则移除整个update_attributes字段
                        if not fixed_response['update_attributes']:
                            fixed_response['update_attributes'] = None
                        print(f"[自动修复] 已移除非数字属性变化值: {attr_name}")
            
            # 修复：建议与不在场的NPC交谈
            elif "AI建议与不在场的NPC" in error:
                if 'suggested_choices' in fixed_response and isinstance(fixed_response['suggested_choices'], list):
                    npc_match = re.search(r"AI建议与不在场的NPC '(.+?)' 交谈", error)
                    if npc_match:
                        npc_name = npc_match.group(1)
                        # 过滤掉包含不在场NPC的建议
                        fixed_response['suggested_choices'] = [
                            choice for choice in fixed_response['suggested_choices']
                            if not (f"与 {npc_name} 交谈" in choice.get('action_command', '') or 
                                   f"和 {npc_name} 交谈" in choice.get('action_command', ''))
                        ]
                        print(f"[自动修复] 已移除与不在场NPC交谈的建议: {npc_name}")
        
        return fixed_response

    def _has_critical_errors(self, errors: List[str]) -> bool:
        """
        判断是否存在需要重新生成的严重错误。
        """
        # 定义严重错误的关键词
        critical_keywords = [
            "叙事提到了",  # 叙事与位置不一致的错误
            "叙事中出现了禁用词",  # 叙事中包含禁用词的错误
        ]
        
        # 检查错误数量，如果错误过多也视为严重错误
        if len(errors) >= 3:
            return True
        
        # 检查是否包含严重错误关键词
        for error in errors:
            for keyword in critical_keywords:
                if keyword in error:
                    return True
        
        return False

    def _regenerate_ai_response(self, ai_response: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
        """
        重新生成AI响应。
        当检测到严重错误时，调用AI服务重新生成响应。
        """
        try:
            from app.services.ai_service import generate_game_master_response
            
            # 获取当前游戏状态和玩家行动
            setting_pack = self.session.world.setting_pack
            current_state = self.session.current_state
            player_action = current_state.get('last_player_action', '观察周围')
            
            # 记录重新生成的原因
            print(f"[AI重新生成] 由于严重错误，正在重新生成响应: {errors}")
            
            # 调用AI服务重新生成响应
            # 添加错误信息作为上下文，帮助AI避免同样的错误
            error_context = "\n".join([f"- {error}" for error in errors])
            enhanced_player_action = f"{player_action}\n[系统提示] 上一次生成的响应存在以下问题，请避免:\n{error_context}"
            
            # 创建一个临时状态副本，添加错误信息
            temp_state = current_state.copy()
            temp_state['last_player_action'] = enhanced_player_action
            
            # 调用AI服务重新生成响应
            new_response = generate_game_master_response(
                setting_pack, 
                temp_state, 
                enhanced_player_action, 
                self.session, 
                action_was_unparsed=False
            )
            
            # 如果重新生成成功，返回新响应
            if new_response and not new_response.get('error'):
                print("[AI重新生成] 成功重新生成响应")
                return new_response
            else:
                print(f"[AI重新生成] 失败: {new_response.get('error', '未知错误')}")
                return None
        except Exception as e:
            print(f"[AI重新生成] 发生异常: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    def use_rule_engine_for_validation(game_session, ai_response):
        """
        【进阶思路】使用规则引擎进行校验。
        这比手写if-else更灵活、更易于扩展。
        你可以使用像 `pyknow` 或 `durable_rules` 这样的库。

        1. 定义规则 (e.g., IF world is 'Cyberpunk' AND narrative contains 'Magic' -> THEN raise InconsistencyError).
        2. 将 game_session 和 ai_response 作为"事实"(Facts) 输入引擎。
        3. 运行引擎，收集所有触发的错误。
        """
        pass # 此处为伪代码，具体实现取决于所选的规则引擎库。