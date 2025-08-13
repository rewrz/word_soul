import json

def validate_setting_pack(setting_pack):
    """
    根据定义的框架，验证设定包内的结构和数据。
    """
    errors = []

    # 1. 验证核心模块是否存在
    required_modules = ["attribute_dimensions", "items", "skills", "tasks", "npcs"]
    for module_name in required_modules:
        if module_name not in setting_pack:
            errors.append(f"Missing required module: {module_name}")

    # 如果核心模块缺失，后续的验证将无意义
    if errors:
        return False, errors

    # 2. 验证属性维度
    errors.extend(validate_attribute_dimensions(setting_pack["attribute_dimensions"]))

    # 3. 验证物品
    errors.extend(validate_items(setting_pack["items"], setting_pack["attribute_dimensions"]))

    # 4. Validate skills
    errors.extend(validate_skills(setting_pack["skills"], setting_pack["attribute_dimensions"]))

    # 5. Validate tasks
    errors.extend(validate_tasks(setting_pack["tasks"]))

    # 6. Validate npcs
    errors.extend(validate_npcs(setting_pack["npcs"], setting_pack["attribute_dimensions"]))

    return not errors, errors


def validate_attribute_dimensions(attribute_dimensions):
    """
    验证 attribute_dimensions 模块。
    """
    errors = []

    # 检查 attribute_dimensions 是否为字典
    if not isinstance(attribute_dimensions, dict):
        errors.append("attribute_dimensions must be a dictionary.")
        return errors

    # 检查必需的维度及其结构
    required_dimension_types = ["生存", "输出", "资源"]  # 例如："生存"、"输出"、"资源"
    for dim_type in required_dimension_types:
        if dim_type not in attribute_dimensions:
            errors.append(f"Missing required dimension type: {dim_type}")
        else:
            dimension = attribute_dimensions[dim_type]
            if not isinstance(dimension, dict):
                errors.append(f"Dimension '{dim_type}' must be a dictionary.")
            else:
                required_keys = ["name", "initial_value"]
                for key in required_keys:
                    if key not in dimension:
                        errors.append(f"Dimension '{dim_type}' missing required key: {key}")
                if not isinstance(dimension.get("name"), str):
                    errors.append(f"Dimension '{dim_type}' 'name' must be a string.")

                if not isinstance(dimension.get("initial_value"), (int, float)):
                     errors.append(f"Dimension '{dim_type}' 'initial_value' must be a number.")

    return errors

def validate_npcs(npcs, attribute_dimensions):
    """
    验证 npcs 模块。
    """
    errors = []

    if not isinstance(npcs, list):
        errors.append("NPCs must be a list.")
        return errors

    defined_attributes = [dim["name"] for dim in attribute_dimensions.values()]

    for npc in npcs:
        if not isinstance(npc, dict):
            errors.append("Each NPC must be a dictionary.")
            continue

        required_keys = ["名称", "描述", "位置", "attributes", "is_hostile"]
        for key in required_keys:
            if key not in npc:
                errors.append(f"NPC '{npc.get('名称', 'Unknown')}' missing required key: {key}")

        # 验证 attributes
        npc_attrs = npc.get("attributes")
        if npc_attrs:
            if not isinstance(npc_attrs, dict):
                errors.append(f"NPC '{npc.get('名称', 'Unknown')}' 'attributes' must be a dictionary.")
            else:
                for attr_name in npc_attrs:
                    if attr_name not in defined_attributes:
                        errors.append(f"NPC '{npc.get('名称', 'Unknown')}' has an undefined attribute: '{attr_name}'. Valid attributes are: {', '.join(defined_attributes)}")
    return errors

def validate_items(items, attribute_dimensions):
    """
    验证 items 模块。
    """
    errors = []

    if not isinstance(items, list):
        errors.append("Items must be a list.")
        return errors

    for item in items:
        if not isinstance(item, dict):
            errors.append("Each item must be a dictionary.")
            continue

        required_keys = ["类型", "名称", "效果", "获取"]  # 例如："类型"、"名称"、"效果"、"获取"
        for key in required_keys:
            if key not in item:
                errors.append(f"Item '{item.get('名称', 'Unknown')}' missing required key: {key}") # 物品名称

        # 验证 '效果'
        effect = item.get("效果")
        if effect:
            if isinstance(effect, str):
                errors.extend(validate_effect(effect, attribute_dimensions, item.get("名称", "Unknown")))
            elif isinstance(effect, list):
                for single_effect in effect:
                     errors.extend(validate_effect(single_effect, attribute_dimensions, item.get("名称", "Unknown")))
    
    return errors


def validate_skills(skills, attribute_dimensions):
    """
    验证 skills 模块。
    """
    errors = []

    if not isinstance(skills, list):
        errors.append("Skills must be a list.")
        return errors

    for skill in skills:
        if not isinstance(skill, dict):
            errors.append("Each skill must be a dictionary.")
            continue

        required_keys = ["类型", "名称", "消耗", "效果"]  # 例如："类型"、"名称"、"消耗"、"效果"
        for key in required_keys:
            if key not in skill:
                errors.append(f"Skill '{skill.get('名称', 'Unknown')}' missing required key: {key}")

        # 验证 '消耗'
        cost = skill.get("消耗")
        if cost:
            errors.extend(validate_cost(cost, attribute_dimensions, skill.get("名称", "Unknown")))

        # 验证 '效果'
        effect = skill.get("效果")
        if effect:
            if isinstance(effect, str):
                errors.extend(validate_effect(effect, attribute_dimensions, skill.get("名称", "Unknown")))
            elif isinstance(effect, list):
                for single_effect in effect:
                    errors.extend(validate_effect(single_effect, attribute_dimensions, skill.get("名称", "Unknown")))
        
        # 验证可选的 '冷却时间'
        cooldown = skill.get('冷却时间')
        if cooldown is not None and not isinstance(cooldown, int):
            errors.append(f"在 '{skill.get('名称', 'Unknown')}' 中, '冷却时间' 必须是一个整数。")


    return errors


def validate_tasks(tasks):
    """
    验证 tasks 模块。
    """
    errors = []

    if not isinstance(tasks, list):
        errors.append("Tasks must be a list.")
        return errors

    for task in tasks:
        if not isinstance(task, dict):
            errors.append("Each task must be a dictionary.")
            continue

        required_keys = ["名称", "状态", "目标", "奖励"]  # 例如："名称"、"状态"、"目标"、"奖励"
        for key in required_keys:
            if key not in task:
                task_identifier = task.get('名称', task.get('目标', 'Unknown'))
                errors.append(f"Task '{task_identifier}' missing required key: {key}")

        task_name = task.get("名称")
        if not isinstance(task_name, str) or not task_name.strip():
            task_identifier = task.get('目标', 'Unknown')
            errors.append(f"Task '{task_identifier}' '名称' must be a non-empty string.")

    return errors

def validate_effect(effect, attribute_dimensions, item_name):
    """
    验证物品或技能的 '效果'。
    效果应该是一个可以被解析为属性变化的字符串。
    """
    errors = []
    import re

    if not isinstance(effect, str):
        errors.append(f"在 '{item_name}' 中，'效果' 必须是字符串。")
        return errors
    
    # 1. 验证格式是否为 "<属性名> <操作符> <数值>"
    match = re.match(r"^\s*([^\s]+)\s*([+\-*/])\s*(\d+(\.\d+)?)\s*$", effect)
    if not match:
        errors.append(f"在 '{item_name}' 中，'效果' 格式无效。应为 '属性名 +/-/*// 数值' (例如 '气血 + 10')，但收到了 '{effect}'。")
        return errors

    # 2. 提取属性名并验证其是否存在
    attribute_name = match.group(1).strip()
    dimension_names = [dim["name"] for dim in attribute_dimensions.values()]
    if attribute_name not in dimension_names:
        valid_names_str = ", ".join(dimension_names)
        errors.append(f"在 '{item_name}' 的效果中，使用了无效的属性名 '{attribute_name}'。有效名称为: {valid_names_str}。")

    return errors

def validate_cost(cost, attribute_dimensions, skill_name):
    """
    验证技能的 '消耗'。
    消耗应该是一个可以被解析为资源消耗的字符串。
    """
    errors = []
    import re

    if not isinstance(cost, str):
        errors.append(f"在 '{skill_name}' 中，'消耗' 必须是字符串。")
        return errors

    # 1. 验证格式是否为 "<资源名> - <数值>"
    match = re.match(r"^\s*(.+?)\s*(-)\s*(\d+(\.\d+)?)\s*$", cost)
    if not match:
        errors.append(f"在 '{skill_name}' 中，'消耗' 格式无效。应为 '资源名 - 数值' (例如 '法力 - 10')，但收到了 '{cost}'。")
        return errors

    # 2. 提取资源名并验证
    resource_name_from_cost = match.group(1).strip()
    resource_dimension = attribute_dimensions.get("资源")

    # 2a. 检查框架中是否定义了“资源”维度
    if not resource_dimension or "name" not in resource_dimension:
        errors.append(f"在 '{skill_name}' 的消耗中，框架未定义'资源'维度的具体名称，无法验证。")
        return errors

    # 2b. 检查消耗的属性是否与定义的资源名称匹配
    defined_resource_name = resource_dimension["name"]
    if resource_name_from_cost != defined_resource_name:
        errors.append(f"在 '{skill_name}' 的消耗中，使用了无效的资源名 '{resource_name_from_cost}'。根据设定，应为 '{defined_resource_name}'。")

    return errors

def validate_game_state(current_state, setting_pack):
    """
    对游戏会话的 current_state 进行全面校验，防止AI生成不一致或无效的数据。
    """
    errors = []

    # 1. 校验核心 'attributes'
    if 'attributes' not in current_state or not isinstance(current_state['attributes'], dict):
        errors.append("current_state 缺少 'attributes' 字典。")
        return False, errors # 如果没有属性，后续检查无意义，提前退出

    defined_attributes = [dim["name"] for dim in setting_pack.get("attribute_dimensions", {}).values()]
    for attr_name, attr_value in current_state['attributes'].items():
        # 1a. 检查属性名是否在设定中定义
        if attr_name not in defined_attributes:
            errors.append(f"游戏状态中包含未定义的属性: '{attr_name}'。")
        # 1b. 检查属性值是否为数字
        if not isinstance(attr_value, (int, float)):
            errors.append(f"属性 '{attr_name}' 的值必须是数字，但收到了 '{attr_value}'。")

    # 2. 校验 'inventory' - 【修改】支持动态物品系统
    if 'inventory' in current_state:
        if not isinstance(current_state['inventory'], list):
            errors.append("游戏状态中的 'inventory' 必须是一个列表。")
        else:
            # 【修改】不再严格校验物品是否预定义，因为支持动态物品获取
            # 只检查基本的数据完整性
            for item_name in current_state['inventory']:
                if not isinstance(item_name, str) or not item_name.strip():
                    errors.append(f"玩家物品栏中包含无效的物品名称: '{item_name}'。")

    # 【修改】校验 'cooldowns' - 支持动态技能系统
    if 'cooldowns' in current_state:
        if not isinstance(current_state['cooldowns'], dict):
            errors.append("游戏状态中的 'cooldowns' 必须是一个字典。")
        else:
            # 【修改】不再检查技能是否在预定义列表中，允许动态技能的冷却
            for skill_name, cooldown_value in current_state['cooldowns'].items():
                # 只检查技能名称和冷却时间的基本有效性
                if not isinstance(skill_name, str) or not skill_name.strip():
                    errors.append(f"技能冷却中包含无效的技能名称: '{skill_name}'。")
                if not isinstance(cooldown_value, int) or cooldown_value < 0:
                    errors.append(f"技能 '{skill_name}' 的冷却时间必须是非负整数。")

    # 4. 校验 'active_quests', 'current_location' 等字段的基本类型
    if 'active_quests' in current_state and not isinstance(current_state['active_quests'], dict):
        errors.append("游戏状态中的 'active_quests' 必须是一个字典。")
    if 'current_location' in current_state and not isinstance(current_state['current_location'], str):
        errors.append("游戏状态中的 'current_location' 必须是字符串。")

    return not errors, errors