import re
from sqlalchemy.orm.attributes import flag_modified
from app.services.ai_service import generate_game_master_response
from app.services.framework_validator import validate_game_state
from app.services.ai_corrector_service import AICorrectorService

class GameTurnProcessor:
    """
    封装处理一个完整游戏回合的所有逻辑。
    """
    def __init__(self, session):
        self.session = session
        self.current_state = session.current_state
        self.setting_pack = session.world.setting_pack

    def process_turn(self, player_action):
        """
        处理玩家行动并返回最终的响应负载。
        """
        # 1. 回合开始，处理状态更新
        self._reduce_cooldowns()
        self._cleanup_temporary_flags()

        # 2. 解析玩家行动并应用其机械效果
        action_was_parsed = self._process_player_action(player_action)

        # 3. 基于更新后的状态，获取AI的叙事回应
        ai_response_data = generate_game_master_response(
            setting_pack=self.setting_pack,
            current_state=self.current_state,
            player_action=player_action,
            game_session=self.session,
            action_was_unparsed=(not action_was_parsed)
        )

        if "error" in ai_response_data:
            return ai_response_data, 500

        # 4. 【核心修改】调用AI修正服务对AI的输出进行校验和修正
        corrector = AICorrectorService(self.session)
        corrected_ai_response, validation_errors = corrector.validate_and_correct(ai_response_data)

        # 如果校验发现严重错误，可以选择在这里中断或返回特定信息
        if validation_errors:
            # 你可以决定如何处理这些错误，例如记录日志，或者向玩家显示一个通用错误
            print(f"[警告] AI响应未通过逻辑校验: {validation_errors}")
            # corrected_ai_response['description'] = "（你的思绪有些混乱，刚才发生了什么？）" # 可以选择覆盖描述

        # 5. 应用修正后的AI叙事结果中的状态变更
        self._apply_ai_state_changes(corrected_ai_response)

        # 6. 如果在战斗中，处理NPC回合和战斗状态检查
        if self.current_state.get('in_combat'):
            self._process_npc_turns()
            self._check_combat_status()

        # 6. 丰富AI建议，并进行最终状态校验
        if 'suggested_choices' in corrected_ai_response:
            corrected_ai_response['suggested_choices'] = self._enrich_suggestions(
                corrected_ai_response['suggested_choices']
            )

        is_valid, validation_errors = validate_game_state(self.current_state, self.setting_pack)
        if not is_valid:
            print(f"[严重警告] 会话 {self.session.id} 的游戏状态校验失败: {validation_errors}")
            return {"error": "游戏状态出现异常，为防止数据损坏已中断操作。请尝试重试或联系管理员。"}, 500

        # 7. 更新历史记录并准备返回
        self._update_history(player_action, corrected_ai_response)

        # 标记状态已被修改，以便SQLAlchemy能检测到
        flag_modified(self.session, "current_state")

        response_payload = {**corrected_ai_response, "current_state": self.current_state}
        return response_payload, 200

    def _cleanup_temporary_flags(self):
        """清理上一个回合可能留下的临时状态"""
        self.current_state.pop('focus_target', None)
        self.current_state.pop('talk_target', None)
        self.current_state.pop('give_info', None)
        self.current_state.pop('buy_info', None)
        self.current_state.pop('last_action_result', None)
        self.current_state.pop('npc_action_results', None)

    def _reduce_cooldowns(self):
        """在每个回合开始时，将所有技能的冷却时间减少1。"""
        if 'cooldowns' not in self.current_state:
            return

        next_cooldowns = {}
        for skill_name, remaining_turns in self.current_state.get('cooldowns', {}).items():
            if remaining_turns > 1:
                next_cooldowns[skill_name] = remaining_turns - 1
        self.current_state['cooldowns'] = next_cooldowns

    def _process_player_action(self, player_action):
        """
        核心行动解析与应用逻辑。
        返回 True 如果行动被程序解析，否则返回 False。
        """
        action_patterns = {
            r"^对\s+(.+?)\s+使用\s+(.+)": self._handle_use_skill,
            r"^使用\s+([^对]+)": self._handle_use_item,
            r"^(调查|观察|查看|检查)\s+(.+)": self._handle_observation,
            r"^(与|和)\s+(.+?)\s+交谈": self._handle_talk,
            r"^攻击\s+(.+)": self._handle_attack,
            r"^(防御|格挡)": self._handle_defend,
            r"^(给予|给)\s+(.+?)\s+(.+)": self._handle_give_item,
            r"^购买\s+(.+)": self._handle_buy_item,
            r"^售卖\s+(.+)": self._handle_sell_item,
        }

        for pattern, handler in action_patterns.items():
            match = re.match(pattern, player_action.strip())
            if match:
                handler(match)
                return True
        return False

    def _apply_ai_state_changes(self, ai_response_data):
        """应用AI叙事结果中的状态变更
        
        【修改】支持动态物品和技能系统，允许在游戏过程中获得新的物品和技能。
        """
        # 【修改】添加物品 - 支持动态物品获取
        item_to_add = ai_response_data.get("add_item_to_inventory")
        if item_to_add:
            # 将物品添加到玩家物品栏
            self.current_state['inventory'].append(item_to_add)
            
            # 【新增】如果是新物品，自动添加到世界设定中
            self._ensure_item_in_setting_pack(item_to_add)

        # 移除物品
        item_to_remove = ai_response_data.get("remove_item_from_inventory")
        if item_to_remove and item_to_remove in self.current_state.get('inventory', []):
            self.current_state['inventory'].remove(item_to_remove)

        # 【修改】更新任务状态 - 支持动态任务和任务完成清理
        quest_update = ai_response_data.get("update_quest_status")
        if quest_update:
            parts = quest_update.split(":", 1)
            if len(parts) == 2:
                quest_name, quest_status = parts[0].strip(), parts[1].strip()
                
                # 【新增】任务完成或失败后的处理逻辑
                if quest_status.lower() in ['已完成', '完成', '成功完成', '任务完成', '失败', '任务失败', '已失败']:
                    # 将任务移动到已完成任务列表
                    if 'completed_quests' not in self.current_state:
                        self.current_state['completed_quests'] = []
                    
                    # 记录完成的任务信息
                    completed_quest_info = {
                        'name': quest_name,
                        'status': quest_status,
                        'completed_at': len(self.current_state.get('recent_history', [])) // 2,  # 使用回合数作为完成时间
                        'is_success': quest_status.lower() not in ['失败', '任务失败', '已失败']
                    }
                    self.current_state['completed_quests'].append(completed_quest_info)
                    
                    # 从活跃任务中移除
                    if quest_name in self.current_state['active_quests']:
                        del self.current_state['active_quests'][quest_name]
                    
                    status_type = "完成" if completed_quest_info['is_success'] else "失败"
                    print(f"[任务系统] 任务 '{quest_name}' 已{status_type}并移至完成列表")
                else:
                    # 普通任务状态更新
                    self.current_state['active_quests'][quest_name] = quest_status
                
                # 【新增】确保任务在设定包中存在
                self._ensure_quest_in_setting_pack(quest_name)
                
                # 【新增】清理过多的已完成任务（保留最近10个）
                if 'completed_quests' in self.current_state and len(self.current_state['completed_quests']) > 10:
                    self.current_state['completed_quests'] = self.current_state['completed_quests'][-10:]

        # 更新位置
        new_location = ai_response_data.get("update_location")
        if new_location and self.current_state['current_location'] != new_location:
            self.current_state['current_location'] = new_location

        # 【修改】创建新任务 - 智能任务管理，避免重复创建
        new_quest_data = ai_response_data.get("create_new_quest")
        if isinstance(new_quest_data, dict) and '名称' in new_quest_data and '目标' in new_quest_data:
            quest_name = new_quest_data['名称']
            
            # 检查任务是否已经存在（活跃任务或最近完成的任务）
            quest_exists = (
                quest_name in self.current_state.get('active_quests', {}) or
                any(q.get('name') == quest_name for q in self.current_state.get('completed_quests', [])[-5:])  # 检查最近5个完成的任务
            )
            
            if not quest_exists:
                if 'tasks' not in self.setting_pack:
                    self.setting_pack['tasks'] = []
                new_quest_data['状态'] = '未开始'
                self.setting_pack['tasks'].append(new_quest_data)
                flag_modified(self.session.world, "setting_pack")
                self.current_state['active_quests'][quest_name] = "已接取"
                print(f"[任务系统] 创建新任务: '{quest_name}'")
            else:
                print(f"[任务系统] 任务 '{quest_name}' 已存在，跳过创建")

        # 【修改】更新属性 - 支持动态属性
        attribute_updates = ai_response_data.get("update_attributes")
        if isinstance(attribute_updates, dict):
            if 'attributes' not in self.current_state:
                self.current_state['attributes'] = {}
            
            for attr_name, change_value in attribute_updates.items():
                if isinstance(change_value, (int, float)):
                    # 【修改】支持动态属性创建
                    if attr_name not in self.current_state['attributes']:
                        # 为新属性设置合理的初始值
                        self.current_state['attributes'][attr_name] = self._get_default_attribute_value(attr_name)
                    
                    # 应用属性变化
                    self.current_state['attributes'][attr_name] += change_value
                    
                    # 四舍五入到两位小数
                    if isinstance(self.current_state['attributes'][attr_name], float):
                        self.current_state['attributes'][attr_name] = round(self.current_state['attributes'][attr_name], 2)
    
    def _ensure_item_in_setting_pack(self, item_name):
        """确保物品在设定包中存在，如果不存在则创建一个基础定义。"""
        existing_items = [item.get('名称') for item in self.setting_pack.get('items', [])]
        if item_name not in existing_items:
            # 创建一个基础的物品定义
            new_item = {
                '名称': item_name,
                '类型': '其他',
                '效果': [],  # 空效果，可以在后续游戏中定义
                '获取': f'在游戏过程中获得',
                '描述': f'在冒险中获得的{item_name}'
            }
            
            if 'items' not in self.setting_pack:
                self.setting_pack['items'] = []
            self.setting_pack['items'].append(new_item)
            flag_modified(self.session.world, "setting_pack")
            print(f"[动态物品] 已将新物品 '{item_name}' 添加到世界设定中")
    
    def _ensure_quest_in_setting_pack(self, quest_name):
        """确保任务在设定包中存在，如果不存在则创建一个基础定义。"""
        existing_quests = [quest.get('名称') for quest in self.setting_pack.get('tasks', [])]
        if quest_name not in existing_quests:
            # 创建一个基础的任务定义
            new_quest = {
                '名称': quest_name,
                '状态': '进行中',
                '目标': f'完成{quest_name}相关的任务',
                '奖励': '未知'
            }
            
            if 'tasks' not in self.setting_pack:
                self.setting_pack['tasks'] = []
            self.setting_pack['tasks'].append(new_quest)
            flag_modified(self.session.world, "setting_pack")
            print(f"[动态任务] 已将新任务 '{quest_name}' 添加到世界设定中")
    
    def _get_default_attribute_value(self, attr_name):
        """为新属性获取合理的默认值。"""
        attr_lower = attr_name.lower()
        
        # 根据属性名称推断合理的初始值
        if any(keyword in attr_lower for keyword in ['生命', '血', 'hp', 'health']):
            return 100  # 生命值类属性
        elif any(keyword in attr_lower for keyword in ['法力', '魔法', 'mp', 'mana', '内力']):
            return 50   # 法力值类属性
        elif any(keyword in attr_lower for keyword in ['经验', 'exp', 'experience']):
            return 0    # 经验值从0开始
        elif any(keyword in attr_lower for keyword in ['等级', 'level', 'lv']):
            return 1    # 等级从1开始
        else:
            return 10   # 其他属性的默认值
    
    def _initialize_player_basics(self):
        """为新玩家初始化基础技能和物品。
        
        这个方法应该在创建新游戏会话时调用，为玩家提供一些基础的技能和物品。
        """
        # 确保玩家有基础的技能
        basic_skills = ['观察', '移动', '交谈', '攻击', '防御']
        
        if 'skills' not in self.setting_pack:
            self.setting_pack['skills'] = []
        
        existing_skills = [skill.get('名称') for skill in self.setting_pack.get('skills', [])]
        
        for skill_name in basic_skills:
            if skill_name not in existing_skills:
                basic_skill = {
                    '名称': skill_name,
                    '类型': '基础',
                    '消耗': '无',
                    '效果': [],
                    '描述': f'基础的{skill_name}能力'
                }
                self.setting_pack['skills'].append(basic_skill)
        
        # 确保玩家有一些基础物品
        if len(self.current_state.get('inventory', [])) == 0:
            basic_items = ['基础衣物', '少量干粮']
            for item_name in basic_items:
                self.current_state['inventory'].append(item_name)
                self._ensure_item_in_setting_pack(item_name)
        
        flag_modified(self.session.world, "setting_pack")
        print("[初始化] 已为玩家初始化基础技能和物品")

    def _update_history(self, player_action, ai_response_data):
        """更新最近历史记录和上一次AI的回复"""
        def sanitize_text(text):
            """一个简单的净化函数，防止基本的HTML注入。
            对于生产环境，建议使用更强大的库，如 Bleach。"""
            return text.replace("<", "&lt;").replace(">", "&gt;")

        sanitized_action = sanitize_text(player_action)
        sanitized_description = sanitize_text(ai_response_data.get('description', ''))
        
        # 检查是否是通过建议按钮触发的行动（包含display_text）
        player_entry = {"role": "player", "content": sanitized_action}
        
        # 如果玩家行动来自建议选择，尝试找到对应的display_text
        if 'suggested_choices' in self.current_state.get('last_ai_response', {}):
            for choice in self.current_state['last_ai_response']['suggested_choices']:
                if (isinstance(choice, dict) and 
                    choice.get('action_command') == player_action and 
                    choice.get('display_text')):
                    player_entry['display_text'] = sanitize_text(choice['display_text'])
                    break
        
        self.current_state['recent_history'].insert(0, player_entry)
        self.current_state['recent_history'].insert(0, {"role": "assistant", "content": sanitized_description})
        self.current_state['recent_history'] = self.current_state['recent_history'][:10]
        self.current_state['last_ai_response'] = ai_response_data

    # --- 行动处理辅助函数 (原routes.py中的_handle_*等函数) ---
    # 注意：这些函数现在是类的方法，直接通过 self.current_state 和 self.setting_pack 访问状态

    def _apply_effect(self, effect_string):
        match = re.match(r"^\s*(.+?)\s*([+\-*/])\s*(\d+(\.\d+)?)\s*$", effect_string)
        if not match: return
        attribute_name, operator, value_str = match.group(1).strip(), match.group(2), match.group(3)
        value = float(value_str)
        if attribute_name not in self.current_state.get('attributes', {}): return
        
        attrs = self.current_state['attributes']
        if operator == '+': attrs[attribute_name] += value
        elif operator == '-': attrs[attribute_name] -= value
        elif operator == '*': attrs[attribute_name] *= value
        elif operator == '/' and value != 0: attrs[attribute_name] /= value
        
        if isinstance(attrs[attribute_name], float):
            attrs[attribute_name] = round(attrs[attribute_name], 2)

    def _handle_use_item(self, match):
        """处理物品使用，支持动态物品系统。
        
        【修改】支持使用游戏过程中获得的新物品，如果物品不在预定义列表中，
        会自动创建一个基础的物品定义。
        """
        item_name = match.group(1).strip()
        
        # 检查玩家是否拥有该物品
        if item_name not in self.current_state.get('inventory', []):
            self.current_state['last_action_result'] = {
                'type': 'item_not_owned',
                'item': item_name
            }
            return
        
        # 查找预定义的物品
        item_to_use = next((item for item in self.setting_pack.get('items', []) if item['名称'] == item_name), None)
        
        # 【新增】如果物品不存在，尝试创建动态物品
        if not item_to_use:
            item_to_use = self._create_dynamic_item(item_name)
            if not item_to_use:
                self.current_state['last_action_result'] = {
                    'type': 'item_not_usable',
                    'item': item_name
                }
                return
        
        # 应用物品效果
        for effect_str in item_to_use.get('效果', []):
            self._apply_effect(effect_str)
        
        # 记录使用结果
        self.current_state['last_action_result'] = {
            'type': 'item_used',
            'item': item_name,
            'effects': item_to_use.get('效果', [])
        }
        
        # 消耗性物品使用后移除
        if item_to_use.get('类型') in ['恢复类', '消耗品']:
            self.current_state['inventory'].remove(item_name)
            print(f"[物品使用] 玩家使用了 '{item_name}'，物品已消耗")

    def _handle_use_skill(self, match):
        """处理技能使用，支持动态技能系统。
        
        【修改】支持使用游戏过程中获得的新技能，如果技能不在预定义列表中，
        会自动创建一个基础的技能定义。
        """
        target, skill_name = match.group(1).strip(), match.group(2).strip()
        
        # 检查技能是否在冷却中
        if skill_name in self.current_state.get('cooldowns', {}):
            self.current_state['last_action_result'] = {
                'type': 'skill_on_cooldown',
                'skill': skill_name,
                'remaining': self.current_state['cooldowns'][skill_name]
            }
            return
        
        # 查找预定义的技能
        skill_to_use = next((skill for skill in self.setting_pack.get('skills', []) if skill['名称'] == skill_name), None)
        
        # 【新增】如果技能不存在，尝试创建动态技能
        if not skill_to_use:
            skill_to_use = self._create_dynamic_skill(skill_name)
            if not skill_to_use:
                self.current_state['last_action_result'] = {
                    'type': 'skill_not_available',
                    'skill': skill_name
                }
                return
        
        # 应用技能消耗
        if cost := skill_to_use.get('消耗'):
            if not self._can_afford_cost(cost):
                self.current_state['last_action_result'] = {
                    'type': 'insufficient_resources',
                    'skill': skill_name,
                    'cost': cost
                }
                return
            self._apply_effect(cost)
        
        # 应用技能效果
        for effect_str in skill_to_use.get('效果', []):
            self._apply_effect(effect_str)
        
        # 设置冷却时间
        if cooldown := skill_to_use.get('冷却时间'):
            if 'cooldowns' not in self.current_state:
                self.current_state['cooldowns'] = {}
            self.current_state['cooldowns'][skill_name] = cooldown
        
        # 记录技能使用结果
        self.current_state['last_action_result'] = {
            'type': 'skill_used',
            'skill': skill_name,
            'target': target
        }
    
    def _create_dynamic_skill(self, skill_name):
        """为游戏过程中获得的新技能创建基础定义。
        
        【新增】支持动态技能系统，允许AI在游戏过程中"教会"玩家新技能。
        """
        # 检查技能名称是否合理
        if not self._is_valid_skill_name(skill_name):
            return None
        
        # 根据技能名称推断基础属性
        skill_type, base_cost, base_effects, base_cooldown = self._infer_skill_properties(skill_name)
        
        # 创建动态技能定义
        dynamic_skill = {
            '名称': skill_name,
            '类型': skill_type,
            '消耗': base_cost,
            '效果': base_effects,
            '冷却时间': base_cooldown,
            '描述': f'在冒险中学会的{skill_name}'
        }
        
        # 添加到设定包中
        if 'skills' not in self.setting_pack:
            self.setting_pack['skills'] = []
        self.setting_pack['skills'].append(dynamic_skill)
        flag_modified(self.session.world, "setting_pack")
        
        print(f"[动态技能] 已将新技能 '{skill_name}' 添加到世界设定中")
        return dynamic_skill
    
    def _is_valid_skill_name(self, skill_name):
        """检查技能名称是否有效。"""
        if not skill_name or len(skill_name) > 10 or len(skill_name) < 1:
            return False
        
        # 检查是否包含无效字符
        invalid_chars = ['@', '#', '$', '%', '^', '&', '*', '(', ')', '[', ']']
        if any(char in skill_name for char in invalid_chars):
            return False
        
        return True
    
    def _infer_skill_properties(self, skill_name):
        """根据技能名称推断技能属性。"""
        skill_lower = skill_name.lower()
        
        # 攻击类技能
        if any(keyword in skill_lower for keyword in ['火球', '冰锥', '雷击', '风刃', '攻击', '斩', '刺', '击']):
            return '攻击', '法力 -10', ['目标气血 -20'], 2
        
        # 治疗类技能
        elif any(keyword in skill_lower for keyword in ['治疗', '恢复', '回血', '疗伤']):
            return '治疗', '法力 -15', ['气血 +30'], 3
        
        # 防御类技能
        elif any(keyword in skill_lower for keyword in ['护盾', '防御', '护体', '守护']):
            return '防御', '法力 -8', ['护甲 +5'], 4
        
        # 辅助类技能
        elif any(keyword in skill_lower for keyword in ['加速', '强化', '祝福', '增益']):
            return '辅助', '法力 -12', ['敏捷 +3'], 5
        
        # 默认技能
        else:
            return '其他', '法力 -5', [], 1
    
    def _can_afford_cost(self, cost_string):
        """检查是否能承担技能消耗。"""
        # 解析消耗字符串，例如 "法力 -10"
        import re
        match = re.match(r'(\S+)\s*([+-]?\d+)', cost_string)
        if not match:
            return True  # 如果无法解析，默认允许使用
        
        attr_name, change_str = match.groups()
        change_value = int(change_str)
        
        current_value = self.current_state.get('attributes', {}).get(attr_name, 0)
        
        # 如果是消耗（负值），检查是否有足够的资源
        if change_value < 0 and current_value + change_value < 0:
            return False
        
        return True
    
    def _create_dynamic_item(self, item_name):
        """为游戏过程中获得的新物品创建基础定义。
        
        【新增】支持动态物品系统，允许AI在游戏过程中给予玩家新物品。
        """
        # 检查物品名称是否合理
        if not self._is_valid_item_name(item_name):
            return None
        
        # 根据物品名称推断基础属性
        item_type, base_effects = self._infer_item_properties(item_name)
        
        # 创建动态物品定义
        dynamic_item = {
            '名称': item_name,
            '类型': item_type,
            '效果': base_effects,
            '获取': f'在游戏过程中获得',
            '描述': f'在冒险中获得的{item_name}'
        }
        
        # 添加到设定包中
        if 'items' not in self.setting_pack:
            self.setting_pack['items'] = []
        self.setting_pack['items'].append(dynamic_item)
        flag_modified(self.session.world, "setting_pack")
        
        print(f"[动态物品] 已将新物品 '{item_name}' 添加到世界设定中")
        return dynamic_item
    
    def _is_valid_item_name(self, item_name):
        """检查物品名称是否有效。"""
        if not item_name or len(item_name) > 15 or len(item_name) < 1:
            return False
        
        # 检查是否包含无效字符
        invalid_chars = ['@', '#', '$', '%', '^', '&', '*', '(', ')', '[', ']']
        if any(char in item_name for char in invalid_chars):
            return False
        
        return True
    
    def _infer_item_properties(self, item_name):
        """根据物品名称推断物品属性。"""
        item_lower = item_name.lower()
        
        # 恢复类物品
        if any(keyword in item_lower for keyword in ['药水', '药剂', '血瓶', '恢复', '治疗']):
            return '恢复类', ['气血 +20']
        
        # 法力恢复类
        elif any(keyword in item_lower for keyword in ['法力', '魔法', '蓝瓶', '魔力']):
            return '恢复类', ['法力 +15']
        
        # 武器类
        elif any(keyword in item_lower for keyword in ['剑', '刀', '斧', '锤', '弓', '法杖']):
            return '武器', ['力量 +5']
        
        # 防具类
        elif any(keyword in item_lower for keyword in ['盾', '甲', '护', '衣', '靴']):
            return '防具', ['护甲 +3']
        
        # 饰品类
        elif any(keyword in item_lower for keyword in ['戒指', '项链', '护符', '宝石']):
            return '饰品', ['敏捷 +2']
        
        # 默认为其他类
        else:
            return '其他', []

    def _handle_observation(self, match):
        self.current_state['focus_target'] = match.group(1).strip()

    def _handle_talk(self, match):
        self.current_state['talk_target'] = match.group(1).strip()

    def _handle_give_item(self, match):
        npc_name, item_name = match.group(2).strip(), match.group(3).strip()
        if item_name not in self.current_state.get('inventory', []): return
        if not any(npc.get('名称') == npc_name for npc in self.setting_pack.get('npcs', [])): return
        
        self.current_state['inventory'].remove(item_name)
        self.current_state['give_info'] = {'npc': npc_name, 'item': item_name}

    def _handle_attack(self, match):
        target_name = match.group(1).strip()
        if not self.current_state.get('in_combat'):
            npc_data = next((npc for npc in self.setting_pack.get('npcs', []) if npc['名称'] == target_name and npc.get('is_hostile')), None)
            if npc_data:
                self.current_state['in_combat'] = True
                self.current_state['combatants'] = [{'name': npc_data['名称'], 'attributes': npc_data['attributes'].copy()}]
                self.current_state['last_action_result'] = {'type': 'initiate_combat', 'target': target_name}
            else:
                self.current_state['last_action_result'] = {'type': 'attack_failed', 'reason': f'无法攻击目标 {target_name}。'}
            return

        target_in_combat = next((c for c in self.current_state.get('combatants', []) if c['name'] == target_name), None)
        if not target_in_combat:
            self.current_state['last_action_result'] = {'type': 'attack_failed', 'reason': f'战斗中没有名为 {target_name} 的敌人。'}
            return

        player_attrs = self.current_state['attributes']
        damage = player_attrs.get('力量', 10) - target_in_combat['attributes'].get('护甲', 0)
        damage = max(0, round(damage))
        target_in_combat['attributes']['气血'] -= damage
        self.current_state['last_action_result'] = {'type': 'attack', 'target': target_name, 'damage': damage}

    def _handle_defend(self, match):
        if not self.current_state.get('in_combat'): return
        if 'player_status_effects' not in self.current_state: self.current_state['player_status_effects'] = []
        self.current_state['player_status_effects'].append({'type': 'defending', 'duration': 1})
        self.current_state['last_action_result'] = {'type': 'defend'}

    def _handle_buy_item(self, match):
        item_name = match.group(1).strip()
        npc_name = self.current_state.get('talk_target')
        if not npc_name: return

        npc = next((n for n in self.setting_pack.get('npcs', []) if n.get('名称') == npc_name), None)
        item = next((i for i in self.setting_pack.get('items', []) if i.get('名称') == item_name), None)
        if not npc or not item or item_name not in npc.get('售卖物品', []): return

        currency_attr = next((d['name'] for dt, d in self.setting_pack.get('attribute_dimensions', {}).items() if dt == '资源'), None)
        price = item.get('价格')
        if not currency_attr or price is None: return

        if self.current_state['attributes'][currency_attr] < price:
            self.current_state['buy_info'] = {'npc': npc_name, 'item': item_name, 'success': False, 'reason': '货币不足'}
            return

        self.current_state['attributes'][currency_attr] -= price
        self.current_state['inventory'].append(item_name)
        self.current_state['buy_info'] = {'npc': npc_name, 'item': item_name, 'success': True, 'price': price}

    def _handle_sell_item(self, match):
        # 售卖逻辑可以类似购买逻辑进行实现
        pass

    def _process_npc_turns(self):
        player_attrs = self.current_state['attributes']
        npc_action_results = []
        is_defending = any(s['type'] == 'defending' for s in self.current_state.get('player_status_effects', []))

        for npc in self.current_state.get('combatants', []):
            npc_attrs = npc['attributes']
            npc_damage = npc_attrs.get('力量', 5) - player_attrs.get('护甲', 0)
            if is_defending: npc_damage //= 2
            npc_damage = max(0, round(npc_damage))
            player_attrs['气血'] -= npc_damage
            npc_action_results.append({'npc': npc['name'], 'action': 'attack', 'damage': npc_damage})

        self.current_state['player_status_effects'] = [s for s in self.current_state.get('player_status_effects', []) if s.get('duration', 1) > 1]
        self.current_state['npc_action_results'] = npc_action_results

    def _check_combat_status(self):
        alive_combatants = []
        for npc in self.current_state.get('combatants', []):
            if npc['attributes'].get('气血', 0) > 0:
                alive_combatants.append(npc)
            else:
                if 'last_action_result' not in self.current_state: self.current_state['last_action_result'] = {}
                self.current_state['last_action_result']['victory_info'] = f"你击败了 {npc['name']}！"

        if not alive_combatants:
            self.current_state['in_combat'] = False
            del self.current_state['combatants']
        else:
            self.current_state['combatants'] = alive_combatants

        if self.current_state['attributes'].get('气血', 0) <= 0:
            self.current_state['in_combat'] = False
            if 'last_action_result' not in self.current_state: self.current_state['last_action_result'] = {}
            self.current_state['last_action_result']['defeat_info'] = "你失去了意识..."

    def _enrich_suggestions(self, suggestions):
        if not isinstance(suggestions, list): return suggestions
        enriched_suggestions = []
        for suggestion in suggestions:
            if not isinstance(suggestion, dict) or 'action_command' not in suggestion:
                enriched_suggestions.append(suggestion)
                continue
            
            command = suggestion['action_command']
            details = []

            use_item_match = re.match(r"^使用\s+([^对]+)", command)
            if use_item_match:
                item_name = use_item_match.group(1).strip()
                item_info = next((item for item in self.setting_pack.get('items', []) if item['名称'] == item_name), None)
                if item_info and '效果' in item_info: details.extend(item_info['效果'])

            use_skill_match = re.match(r"^对\s+(.+?)\s+使用\s+(.+)", command)
            if use_skill_match:
                skill_name = use_skill_match.group(2).strip()
                skill_info = next((skill for skill in self.setting_pack.get('skills', []) if skill['名称'] == skill_name), None)
                if skill_info:
                    if '消耗' in skill_info: details.append(skill_info['消耗'])
                    if '效果' in skill_info: details.extend(skill_info['效果'])

            buy_item_match = re.match(r"^购买\s+(.+)", command)
            if buy_item_match:
                item_name = buy_item_match.group(1).strip()
                item_info = next((item for item in self.setting_pack.get('items', []) if item['名称'] == item_name), None)
                if item_info and '价格' in item_info:
                    details.append(f"价格: {item_info['价格']}")

            if details:
                suggestion['details'] = details

            enriched_suggestions.append(suggestion)

        return enriched_suggestions