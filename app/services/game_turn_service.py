import re
from sqlalchemy.orm.attributes import flag_modified
from app.services.ai_service import generate_game_master_response
from app.services.framework_validator import validate_game_state

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

        # 4. 应用AI叙事结果中的状态变更
        self._apply_ai_state_changes(ai_response_data)

        # 5. 如果在战斗中，处理NPC回合和战斗状态检查
        if self.current_state.get('in_combat'):
            self._process_npc_turns()
            self._check_combat_status()

        # 6. 丰富AI建议，并进行最终状态校验
        if 'suggested_choices' in ai_response_data:
            ai_response_data['suggested_choices'] = self._enrich_suggestions(
                ai_response_data['suggested_choices']
            )

        is_valid, validation_errors = validate_game_state(self.current_state, self.setting_pack)
        if not is_valid:
            print(f"[严重警告] 会话 {self.session.id} 的游戏状态校验失败: {validation_errors}")
            return {"error": "游戏状态出现异常，为防止数据损坏已中断操作。请尝试重试或联系管理员。"}, 500

        # 7. 更新历史记录并准备返回
        self._update_history(player_action, ai_response_data)

        # 标记状态已被修改，以便SQLAlchemy能检测到
        flag_modified(self.session, "current_state")

        response_payload = {**ai_response_data, "current_state": self.current_state}
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
        """应用AI叙事结果中的状态变更"""
        # 添加物品
        item_to_add = ai_response_data.get("add_item_to_inventory")
        if item_to_add:
            self.current_state['inventory'].append(item_to_add)

        # 移除物品
        item_to_remove = ai_response_data.get("remove_item_from_inventory")
        if item_to_remove and item_to_remove in self.current_state.get('inventory', []):
            self.current_state['inventory'].remove(item_to_remove)

        # 更新任务状态
        quest_update = ai_response_data.get("update_quest_status")
        if quest_update:
            parts = quest_update.split(":", 1)
            if len(parts) == 2:
                self.current_state['active_quests'][parts[0].strip()] = parts[1].strip()

        # 更新位置
        new_location = ai_response_data.get("update_location")
        if new_location and self.current_state['current_location'] != new_location:
            self.current_state['current_location'] = new_location

        # 创建新任务
        new_quest_data = ai_response_data.get("create_new_quest")
        if isinstance(new_quest_data, dict) and '名称' in new_quest_data and '目标' in new_quest_data:
            quest_name = new_quest_data['名称']
            existing_task_names = [t.get('名称') for t in self.setting_pack.get('tasks', [])]
            if quest_name not in existing_task_names:
                if 'tasks' not in self.setting_pack:
                    self.setting_pack['tasks'] = []
                new_quest_data['状态'] = '未开始'
                self.setting_pack['tasks'].append(new_quest_data)
                flag_modified(self.session.world, "setting_pack")
                self.current_state['active_quests'][quest_name] = "已接取"

    def _update_history(self, player_action, ai_response_data):
        """更新最近历史记录和上一次AI的回复"""
        def sanitize_text(text):
            """一个简单的净化函数，防止基本的HTML注入。
            对于生产环境，建议使用更强大的库，如 Bleach。"""
            return text.replace("<", "&lt;").replace(">", "&gt;")

        sanitized_action = sanitize_text(player_action)
        sanitized_description = sanitize_text(ai_response_data.get('description', ''))
        self.current_state['recent_history'].insert(0, {"role": "player", "content": sanitized_action})
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
        item_name = match.group(1).strip()
        if item_name not in self.current_state.get('inventory', []): return
        item_to_use = next((item for item in self.setting_pack.get('items', []) if item['名称'] == item_name), None)
        if not item_to_use: return

        for effect_str in item_to_use.get('效果', []):
            self._apply_effect(effect_str)

        if item_to_use.get('类型') in ['恢复类']:
            self.current_state['inventory'].remove(item_name)

    def _handle_use_skill(self, match):
        target, skill_name = match.group(1).strip(), match.group(2).strip()
        skill_to_use = next((skill for skill in self.setting_pack.get('skills', []) if skill['名称'] == skill_name), None)
        if not skill_to_use or skill_name in self.current_state.get('cooldowns', {}): return

        if cost := skill_to_use.get('消耗'): self._apply_effect(cost)
        for effect_str in skill_to_use.get('效果', []): self._apply_effect(effect_str)

        if cooldown := skill_to_use.get('冷却时间'):
            if 'cooldowns' not in self.current_state: self.current_state['cooldowns'] = {}
            self.current_state['cooldowns'][skill_name] = cooldown

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