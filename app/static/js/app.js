document.addEventListener('DOMContentLoaded', function() {
    // --- Constants & State ---
    const API_URL = '/api';
    const state = {
        token: localStorage.getItem('jwt_token'),
        currentSessionId: null,
        activeAiConfigId: localStorage.getItem('active_ai_config_id'), // 新增：从本地存储加载激活的AI配置ID
        currentWorldName: null,
        lastPlayerAction: null, // 新增：存储上一次玩家的行动
        aiConfigs: [], // 新增：缓存用户的AI配置
    };


    // --- DOM Elements ---
    const views = document.querySelectorAll('.view');
    const authError = document.getElementById('auth-error');

    // Auth
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const showRegisterLink = document.getElementById('show-register-link');
    const showLoginLink = document.getElementById('show-login-link');

    // Main Menu
    const sessionList = document.getElementById('session-list');
    const showCreateWorldBtn = document.getElementById('show-create-world-btn');
    const manageAiConfigsBtn = document.getElementById('manage-ai-configs-btn');
    const logoutBtn = document.getElementById('logout-btn');

    // Create World
    const createWorldForm = document.getElementById('create-world-form');
    const creationAiConfigSelect = document.getElementById('creation-ai-config-select');
    const assistCreateWorldBtn = document.getElementById('assist-create-world-btn');
    const cancelCreateWorldBtn = document.getElementById('cancel-create-world-btn');

    // Game
    const gameWorldName = document.getElementById('game-world-name');
    const gameLog = document.getElementById('game-log');
    const gameSuggestions = document.getElementById('game-suggestions');
    const actionForm = document.getElementById('action-form');
    const actionInput = document.getElementById('action-input');
    const retryAiBtn = document.getElementById('retry-ai-btn');
    const questList = document.getElementById('quest-list');
    const currentLocation = document.getElementById('current-location');
    const playerStatsList = document.getElementById('player-stats-list'); // 新增：玩家属性列表
    const cooldownList = document.getElementById('cooldown-list');
    const inventoryList = document.getElementById('inventory-list');
    const changeGameAiBtn = document.getElementById('change-game-ai-btn');
    const backToMenuBtn = document.getElementById('back-to-menu-btn');

    // AI Config View
    const aiConfigList = document.getElementById('ai-config-list');
    const showAddConfigModalBtn = document.getElementById('show-add-config-modal-btn');
    const backToMenuFromConfigBtn = document.getElementById('back-to-menu-from-config-btn');

    // AI Config Modal
    const aiConfigModal = document.getElementById('ai-config-modal');
    const aiConfigForm = document.getElementById('ai-config-form');
    const modalTitle = document.getElementById('modal-title');
    const closeModalBtn = aiConfigModal.querySelector('.close-btn');
    const configIdInput = document.getElementById('config-id');


    // --- API Helper ---
    async function fetchWithAuth(endpoint, options = {}) {
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };
        if (state.token) {
            headers['Authorization'] = `Bearer ${state.token}`;
        }

        const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers });

        // Only treat 401 as an expired session if we were actually sending a token
        if (response.status === 401 && state.token) {
            handleLogout();
            return null;
        }
        return response;
    }

    // --- View Management ---
    function showView(viewId) {
        views.forEach(view => view.style.display = 'none');
        const targetView = document.getElementById(viewId);
        if (targetView) targetView.style.display = 'block';
    }

    // --- Auth Logic ---
    async function handleLogin(e) {
        e.preventDefault();
        authError.textContent = '';
        try {
            const username = document.getElementById('login-username').value;
            const password = document.getElementById('login-password').value;

            const response = await fetchWithAuth('/login', {
                method: 'POST',
                body: JSON.stringify({ username, password }),
            });

            const data = await response.json();
            if (response.ok) {
                state.token = data.access_token;
                console.log("Token received and stored:", state.token); // Diagnostic log
                localStorage.setItem('jwt_token', state.token);
                await loadAndShowMainMenu();
            } else {
                authError.textContent = data.error || '登录失败';
            }
        } catch (error) {
            console.error("An error occurred during the login process:", error);
            authError.textContent = '登录过程中发生意外错误。请检查控制台。';
        }
    }

    async function handleRegister(e) {
        e.preventDefault();
        authError.textContent = '';
        const username = document.getElementById('register-username').value;
        const password = document.getElementById('register-password').value;

        const response = await fetchWithAuth('/register', {
            method: 'POST',
            body: JSON.stringify({ username, password }),
        });

        const data = await response.json();
        if (response.ok) {
            alert('注册成功！请使用新账户登录。');
            loginForm.reset();
            registerForm.reset();
        } else {
            authError.textContent = data.error || '注册失败';
        }
    }

    function handleLogout() {
        state.token = null;
        state.currentSessionId = null;
        state.currentWorldName = null;
        localStorage.removeItem('jwt_token');
        console.log("Logging out, token was:", state.token); // Diagnostic log

        showView('auth-view');
    }

    async function handleDeleteSession(sessionId, elementToRemove) {
        // Ask for confirmation before this irreversible action
        if (!confirm(`你确定要删除这个纪传吗？此操作不可撤销。`)) {
            return;
        }

        const response = await fetchWithAuth(`/sessions/${sessionId}`, {
            method: 'DELETE',
        });

        if (response && response.ok) {
            // Add a nice fade-out effect for better UX
            elementToRemove.style.transition = 'opacity 0.3s ease-out';
            elementToRemove.style.opacity = '0';
            setTimeout(() => {
                elementToRemove.remove();
                if (sessionList.children.length === 0) {
                    sessionList.innerHTML = '<p>尚无纪传。咏唱创世之言以开启新的篇章。</p>';
                }
            }, 300);
        } else {
            alert('删除失败。');
        }
    }

    // --- Main Menu Logic ---

    async function loadAndShowMainMenu() {
        const response = await fetchWithAuth('/sessions');
        if (response && response.ok) { // This is the success path
            const sessions = await response.json();
            renderSessions(sessions);
            showView('main-menu-view');
        } else { // This is the failure path
            // If we fail to get sessions, it's likely an auth issue.
            // Log the error and consider logging the user out or showing an error.
            console.error("Failed to load sessions. Status:", response ? response.status : 'No response');
            // Throw an error to be caught by the caller
            throw new Error(`Failed to load sessions with status: ${response ? response.status : 'N/A'}`);
        }
    }


    function renderSessions(sessions) {
        sessionList.innerHTML = '';
        if (sessions.length === 0) {
            sessionList.innerHTML = '<p>尚无纪传。咏唱创世之言以开启新的篇章。</p>';
            return;
        }
        sessions.forEach(session => {
            const item = document.createElement('div');
            item.className = 'session-item';
            item.dataset.sessionId = session.session_id;
            item.innerHTML = `
                <div class="session-item-info">
                    <h3>${session.world_name}</h3>
                    <p>上次封存于: ${new Date(session.last_played).toLocaleString()}</p>
                </div>
                <div class="session-item-actions">
                    <button class="continue-btn" data-session-id="${session.session_id}">继续</button>
                    <button class="set-session-ai-btn" data-session-id="${session.session_id}">设置AI</button>
                    <button class="delete-btn" data-session-id="${session.session_id}">删除</button>
                </div>
            `;
            sessionList.appendChild(item);
        });
    }

    sessionList.addEventListener('click', (e) => {
        const target = e.target;
        // 使用 .closest() 查找按钮，这样即使用户点到按钮内的图标也能正确响应
        const button = target.closest('button');
        if (!button) return;

        const itemElement = target.closest('.session-item');
        const sessionId = itemElement.dataset.sessionId;

        if (button.classList.contains('continue-btn')) {
            loadSessionAndStartGame(sessionId);
        } else if (button.classList.contains('set-session-ai-btn')) {
            handleChangeGameAi(sessionId);
        } else if (button.classList.contains('delete-btn')) {
            handleDeleteSession(sessionId, itemElement);
        }
    });


    // --- World Creation Logic ---
    async function showCreateWorldView() {
        // 在显示视图前，先获取AI配置并填充下拉菜单
        await populateAiConfigSelect(creationAiConfigSelect, state.activeAiConfigId);
        showView('create-world-view');
    }
    // --- World Creation Logic ---
    async function handleCreateWorld(e) {
        e.preventDefault();
        const submitBtn = createWorldForm.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.textContent;

        showWorldFormSkeleton();
        submitBtn.disabled = true;
        assistCreateWorldBtn.disabled = true;
        cancelCreateWorldBtn.disabled = true;
        submitBtn.textContent = '创造中...';

        try {
            const worldName = document.getElementById('world-name').value;
            const worldRules = document.getElementById('world-rules').value;
            const initialScene = document.getElementById('initial-scene').value;
            const narrativePrinciples = document.getElementById('narrative-principles').value;

            const worldKeywords = `世界名称: ${worldName}; 核心规则: ${worldRules}; 初始场景: ${initialScene}; 叙事原则: ${narrativePrinciples}`;

            const worldData = {
                world_keywords: worldKeywords,
                player_description: document.getElementById('character-description').value,
                active_ai_config_id: creationAiConfigSelect.value
            };

            const response = await fetchWithAuth('/worlds', {
                method: 'POST',
                body: JSON.stringify(worldData),
            });

            if (response && response.ok) {
                const data = await response.json();
                createWorldForm.reset();
                loadSessionAndStartGame(data.session_id);
            } else {
                const errorData = response ? await response.json().catch(() => ({})) : { error: '未知错误' };
                alert(`世界创造失败: ${errorData.details || errorData.error || '请检查输入或后台日志。'}`);
            }
        } catch (error) {
            console.error('World creation failed:', error);
            alert('创造世界时发生网络错误，请重试。');
        } finally {
            hideWorldFormSkeleton();
            submitBtn.disabled = false;
            assistCreateWorldBtn.disabled = false;
            cancelCreateWorldBtn.disabled = false;
            submitBtn.textContent = originalBtnText;
        }
    }


    async function handleAssistCreateWorld() {
        const currentData = {
            world_name: document.getElementById('world-name').value,
            character_description: document.getElementById('character-description').value,
            world_rules: document.getElementById('world-rules').value,
            initial_scene: document.getElementById('initial-scene').value,
            narrative_principles: document.getElementById('narrative-principles').value,
            // 修改：从创世页面的下拉菜单中获取AI配置ID
            active_ai_config_id: creationAiConfigSelect.value
        };

        showWorldFormSkeleton();

        assistCreateWorldBtn.disabled = true;
        assistCreateWorldBtn.textContent = '咏唱中...';

        try {
            const response = await fetchWithAuth('/worlds/assist', {
                method: 'POST',
                body: JSON.stringify(currentData),
            });

            if (response && response.ok) {
                const assistedData = await response.json();
                if (assistedData.error) {
                    alert(`AI辅助失败: ${assistedData.error}`);
                    return;
                }
                document.getElementById('world-name').value = assistedData.world_name || '';
                document.getElementById('character-description').value = assistedData.character_description || '';
                document.getElementById('world-rules').value = assistedData.world_rules || '';
                document.getElementById('initial-scene').value = assistedData.initial_scene || '';
                document.getElementById('narrative-principles').value = assistedData.narrative_principles || '';
            } else {
                const errorData = response ? await response.json().catch(() => ({ error: '无法解析错误响应' })) : { error: '未知网络错误' };
                alert(`AI辅助失败: ${errorData.error || '请稍后再试。'}`);
            }
        } catch (error) {
            console.error('AI辅助请求时发生网络错误:', error);
            alert('AI辅助请求失败，请检查网络连接或稍后再试。');
        } finally {
            assistCreateWorldBtn.disabled = false;
            assistCreateWorldBtn.textContent = 'AI辅助咏唱';
            hideWorldFormSkeleton();
        }
    }


    // --- Game Logic ---
    async function loadSessionAndStartGame(sessionId) { // 负责加载
        console.log("准备加载纪事，ID:", sessionId);
        const response = await fetchWithAuth(`/sessions/${sessionId}`);

        if (response && response.ok) {
            const sessionData = await response.json();
            startGame(sessionData); // 将完整的存档数据传递给开始游戏的函数
        } else {
            alert('加载纪事失败。');
            console.error("无法加载会话:", response);
        }
    }


    function startGame(sessionData) { // 负责根据数据渲染游戏界面
        console.log("正在开始游戏，读取到的存档数据:", sessionData);
        state.currentSessionId = sessionData.session_id;
        state.currentWorldName = sessionData.world_name;

        gameWorldName.textContent = state.currentWorldName;
        gameLog.innerHTML = '';
        actionInput.value = '';

        // 游戏开始时，渲染一次玩家状态
        const currentState = sessionData.current_state || {};
        renderPlayerStatus(currentState);

        showView('game-view');

        // 恢复游戏日志
        if (currentState.recent_history && currentState.recent_history.length > 0) {
            // 历史记录是倒序存的（最新在前），所以渲染时要反转回来
            [...currentState.recent_history].reverse().forEach(entry => {
                appendLog(entry.content, entry.role);
            });
        }

        // 只有在历史记录完全不存在或为空时，才视为新游戏并“环顾四周”
        if (!currentState.recent_history || currentState.recent_history.length === 0) {
            console.log("这是一个新游戏或空存档，正在自动'环顾四周'。");
            handleActionSubmit(null, "环顾四周");
        } else {
            // 如果是加载的旧游戏，恢复上次的建议选项
            console.log("已成功加载存档，正在恢复建议选项。");
            const lastAiResponse = currentState.last_ai_response || {};
            renderGameSuggestions(lastAiResponse.suggested_choices);
            // 确保日志滚动到底部
            gameLog.scrollTop = gameLog.scrollHeight;
        }
    }

    async function handleActionSubmit(e, actionText) {
        if (e) e.preventDefault();
        const action = actionText || actionInput.value.trim();
        if (!action) return;

        state.lastPlayerAction = action; // 存储行动

        if (!actionText) { // Only clear input if it was typed by user
            actionInput.value = '';
        }

        // Display player action immediately
        appendLog(action, 'player');

        // --- UI Loading State ---
        let requestSucceeded = false;
        retryAiBtn.style.display = 'none';
        actionInput.disabled = true;
        gameSuggestions.querySelectorAll('button').forEach(btn => btn.disabled = true);

        // Create and append the skeleton placeholder for the AI response
        const skeletonEntry = document.createElement('div');
        skeletonEntry.className = 'log-entry ai skeleton';
        // Add some placeholder lines to make it look like text is loading
        skeletonEntry.innerHTML = '<span>&nbsp;</span><span>&nbsp;</span><span>&nbsp;</span>';
        gameLog.appendChild(skeletonEntry);
        gameLog.scrollTop = gameLog.scrollHeight;

        try {
            const response = await fetchWithAuth(`/sessions/${state.currentSessionId}/action`, {
                method: 'POST',
                body: JSON.stringify({ action }),
            });

            gameLog.removeChild(skeletonEntry);

            if (response && response.ok) {
                const data = await response.json();
                renderGameTurn(data);
                requestSucceeded = true;
            } else {
                const errorData = response ? await response.json().catch(() => ({})) : { error: '未知错误' };
                appendLog(`世界之灵没有回应... (${errorData.error || '请重试'})`, 'message');
            }
        } catch (error) {
            console.error('Action submission failed:', error);
            if (skeletonEntry.parentNode === gameLog) {
                gameLog.removeChild(skeletonEntry);
            }
            appendLog('与世界之灵的连接中断，请检查网络并重试。', 'message');
        } finally {
            retryAiBtn.style.display = 'inline-block';
            actionInput.disabled = false;
            actionInput.focus();
            if (!requestSucceeded) {
                gameSuggestions.querySelectorAll('button').forEach(btn => btn.disabled = false);
            }
        }
    }


    // 为重试按钮绑定事件监听
    retryAiBtn.addEventListener('click', () => {
        if (state.lastPlayerAction) {
            // 重新发送最后一次玩家行动
            handleActionSubmit(null, state.lastPlayerAction);
        } else {
            // 如果没有找到玩家行动，显示提示信息
            alert('没有找到上次的玩家行动。');
        }
    });


    function renderGameTurn(data) {
        if (data.description) {
            appendLog(data.description, 'ai');
        }
        if (data.player_message) {
            appendLog(data.player_message, 'message');
        }

        // 新增：如果API返回了当前状态，则渲染玩家状态侧边栏
        if (data.current_state) {
            renderPlayerStatus(data.current_state);
        }

        renderGameSuggestions(data.suggested_choices);
    }


    function renderGameSuggestions(choices) {
        gameSuggestions.innerHTML = '';
        if (choices && choices.length > 0) {
            choices.forEach(choice => {
                const btn = document.createElement('button');
                btn.className = 'suggestion-btn';
                // 检查choice是对象还是旧的字符串格式，以实现向后兼容
                if (typeof choice === 'object' && choice !== null && choice.display_text) {
                    btn.textContent = choice.display_text;
                    // 如果action_command存在，则使用它，否则回退到使用display_text
                    const actionCommand = choice.action_command !== undefined ? choice.action_command : choice.display_text;
                    btn.addEventListener('click', () => handleActionSubmit(null, actionCommand));

                    // 新增：如果建议包含详细信息，则显示它们
                    if (choice.details && Array.isArray(choice.details)) {
                        const detailsSpan = document.createElement('span');
                        detailsSpan.className = 'suggestion-details';
                        detailsSpan.textContent = `(${choice.details.join(', ')})`;
                        btn.appendChild(detailsSpan);
                    }
                } else {
                    // 对旧格式（纯字符串）的兼容处理
                    btn.textContent = choice;
                    btn.addEventListener('click', () => handleActionSubmit(null, choice));
                }
                gameSuggestions.appendChild(btn);
            });
        }
    }


    function appendLog(text, type) {
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        entry.textContent = text;
        gameLog.appendChild(entry);
        gameLog.scrollTop = gameLog.scrollHeight; // Auto-scroll to bottom
    }


    function renderPlayerStatus(currentState) {
        // 1. 渲染玩家属性
        playerStatsList.innerHTML = '';
        const attributes = currentState.attributes || {};
        if (Object.keys(attributes).length === 0) {
            playerStatsList.innerHTML = '<li>属性未知</li>';
        } else {
            for (const [name, value] of Object.entries(attributes)) {
                const li = document.createElement('li');
                // 将数字值四舍五入到两位小数以获得更好的显示效果
                const displayValue = typeof value === 'number' ? Math.round(value * 100) / 100 : value;
                li.innerHTML = `<strong>${name}:</strong> ${displayValue}`;
                playerStatsList.appendChild(li);
            }
        }

        // 新增：渲染当前位置
        currentLocation.textContent = currentState.current_location || '未知之地';

        // 2. 渲染物品清单
        inventoryList.innerHTML = '';
        const inventory = currentState.inventory || [];
        if (inventory.length === 0) {
            inventoryList.innerHTML = '<li>空空如也</li>';
        } else {
            inventory.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                inventoryList.appendChild(li);
            });
        }

        // 3. 渲染任务列表
        questList.innerHTML = '';
        const quests = currentState.active_quests || {};
        if (Object.keys(quests).length === 0) {
            questList.innerHTML = '<li>暂无任务</li>';
        } else {
            for (const [name, status] of Object.entries(quests)) {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${name}:</strong> ${status}`;
                questList.appendChild(li);
            }
        }

        // 4. 渲染技能冷却
        cooldownList.innerHTML = '';
        const cooldowns = currentState.cooldowns || {};
        if (Object.keys(cooldowns).length === 0) {
            cooldownList.innerHTML = '<li>无</li>';
        } else {
            for (const [name, turns] of Object.entries(cooldowns)) {
                const li = document.createElement('li');
                // 技能名称和剩余回合数
                li.innerHTML = `<strong>${name}:</strong> ${turns} 回合`;
                cooldownList.appendChild(li);
            }
        }
    }

    // --- AI Config Logic ---
    async function populateAiConfigSelect(selectElement, selectedId) {
        // 这是一个辅助函数，用于使用AI配置填充<select>元素
        if (state.aiConfigs.length === 0) {
            const response = await fetchWithAuth('/ai-configs');
            if (response && response.ok) {
                state.aiConfigs = await response.json();
            } else {
                console.error("无法加载AI配置列表");
                selectElement.innerHTML = '<option value="">无法加载AI配置</option>';
                return;
            }
        }

        selectElement.innerHTML = '';
        if (state.aiConfigs.length === 0) {
            selectElement.innerHTML = '<option value="" disabled>请先在“管理AI模型”中添加配置</option>';
            return;
        }

        state.aiConfigs.forEach(config => {
            const option = document.createElement('option');
            option.value = config.id;
            option.textContent = `${config.config_name} (${config.api_type})`;
            if (config.id == selectedId) {
                option.selected = true;
            }
            selectElement.appendChild(option);
        });
    }


    async function handleChangeGameAi(sessionId) {
        // “更换AI模型”按钮的处理器
        // 如果AI配置列表为空，先加载它
        if (state.aiConfigs.length === 0) {
            await showAiConfigView();
            showView('main-menu-view'); // 加载后切回主菜单
        }
        const options = state.aiConfigs.map(c => `${c.id}: ${c.config_name} (${c.api_type})`).join('\n');
        const chosenId = prompt(`请选择要用于此纪事的AI配置，输入前面的数字ID：\n\n${options}`);

        if (chosenId && state.aiConfigs.some(c => c.id == chosenId)) {
            const response = await fetchWithAuth(`/sessions/${sessionId}/set-ai-config`, {
                method: 'POST',
                body: JSON.stringify({ config_id: parseInt(chosenId) })
            });

            if (response && response.ok) {
                alert('此纪事的AI配置已成功更新！');
            } else {
                alert('更新失败。');
            }
        } else if (chosenId) {
            alert('无效的ID。');
        }
    }

    // --- AI Config Logic ---
    async function showAiConfigView() {
        const response = await fetchWithAuth('/ai-configs');
        if (response && response.ok) {
            state.aiConfigs = await response.json();
            renderAiConfigs();
            showView('ai-config-view');
        } else {
            alert('获取AI配置失败。');
        }
    }


    function renderAiConfigs() {
        aiConfigList.innerHTML = '';
        if (state.aiConfigs.length === 0) {
            aiConfigList.innerHTML = '<tr><td colspan="4" style="text-align:center;">尚无配置。请添加一个新配置。</td></tr>';
            return;
        }
        state.aiConfigs.forEach(config => {
            const row = document.createElement('tr');
            // 如果当前配置是激活的，给它一个特殊的类以高亮显示
            if (config.id == state.activeAiConfigId) {
                row.classList.add('active-config');
            }
            row.innerHTML = `
                <td>${config.config_name}</td>
                <td>${config.api_type}</td>
                <td>${config.model_name || 'N/A'}</td>
                <td class="action-buttons">
                    <button class="set-active-config-btn" data-id="${config.id}" ${config.id == state.activeAiConfigId ? 'disabled' : ''}>
                        ${config.id == state.activeAiConfigId ? '当前默认' : '设为默认'}
                    </button>
                    <button class="edit-config-btn" data-id="${config.id}">编辑</button>
                    <button class="delete-config-btn delete-btn" data-id="${config.id}">删除</button>
                </td>
            `;
            aiConfigList.appendChild(row);
        });
    }


    function handleSetActiveAiConfig(configId) {
        state.activeAiConfigId = configId;
        localStorage.setItem('active_ai_config_id', configId);
        alert('默认AI配置已更新！');
        renderAiConfigs(); // 重新渲染列表以更新按钮状态和高亮
    }


    function openAiConfigModal(config = null) {
        aiConfigForm.reset();
        if (config) {
            modalTitle.textContent = '编辑AI配置';
            configIdInput.value = config.id;
            document.getElementById('config-name').value = config.config_name;
            document.getElementById('api-type').value = config.api_type;
            document.getElementById('model-name').value = config.model_name || '';
            document.getElementById('base-url').value = config.base_url || '';
            // API Key is sensitive, so we don't pre-fill it. We show a placeholder.
            document.getElementById('api-key').placeholder = '若需更新，请在此输入新的API Key';
        } else {
            modalTitle.textContent = '添加新配置';
            configIdInput.value = '';
            document.getElementById('api-key').placeholder = 'API Key (敏感信息，保存后不回显)';
        }
        aiConfigModal.style.display = 'flex';
    }


    function closeAiConfigModal() {
        aiConfigModal.style.display = 'none';
    }

    async function handleAiConfigFormSubmit(e) {

        e.preventDefault();
        const configId = configIdInput.value;
        const data = {
            config_name: document.getElementById('config-name').value,
            api_type: document.getElementById('api-type').value,
            model_name: document.getElementById('model-name').value,
            api_key: document.getElementById('api-key').value,
            base_url: document.getElementById('base-url').value,
        };

        // 如果是编辑模式且API Key为空，则不发送该字段，以避免后端清空它
        if (configId && !data.api_key) {
            delete data.api_key;
        }

        const url = configId ? `/ai-configs/${configId}` : '/ai-configs';
        const method = configId ? 'PUT' : 'POST';

        const response = await fetchWithAuth(url, { method, body: JSON.stringify(data) });
        if (response && response.ok) {
            closeAiConfigModal();
            await showAiConfigView(); // 重新加载并显示配置列表
        } else {
            const errorData = response ? await response.json() : { error: '未知错误' };
            alert(`保存失败: ${errorData.error}`);
        }
    }


    async function handleDeleteAiConfig(configId) {
        if (!confirm('确定要删除这个AI配置吗？')) return;

        const response = await fetchWithAuth(`/ai-configs/${configId}`, { method: 'DELETE' });
        if (response && response.ok) {
            await showAiConfigView();
        } else {
            alert('删除失败。');
        }
    }

    function showWorldFormSkeleton() {
        const formElements = [
            'world-name',
            'character-description',
            'world-rules',
            'initial-scene',
            'narrative-principles'
        ];

        formElements.forEach(id => {
            const element = document.getElementById(id);
            element.classList.add('skeleton');
            element.disabled = true;
        });
    }

    function hideWorldFormSkeleton() {
        const formElements = [
            'world-name',
            'character-description',
            'world-rules',
            'initial-scene',
            'narrative-principles'
        ];

        formElements.forEach(id => {
            const element = document.getElementById(id);
            element.classList.remove('skeleton');
            element.disabled = false;
        });
    }

    // --- Initializer ---
    function init() {
        // Auth
        loginForm.addEventListener('submit', handleLogin);
        registerForm.addEventListener('submit', handleRegister);

        // Auth view toggling
        showRegisterLink.addEventListener('click', (e) => {
            e.preventDefault();
            loginForm.style.display = 'none';
            registerForm.style.display = 'block';
            authError.textContent = '';
        });

        showLoginLink.addEventListener('click', (e) => {
            e.preventDefault();
            loginForm.style.display = 'block';
            registerForm.style.display = 'none';
            authError.textContent = '';
        });

        logoutBtn.addEventListener('click', handleLogout);

        // Main Menu
        showCreateWorldBtn.addEventListener('click', showCreateWorldView);
        manageAiConfigsBtn.addEventListener('click', showAiConfigView);

        // Create World
        createWorldForm.addEventListener('submit', handleCreateWorld);
        assistCreateWorldBtn.addEventListener('click', handleAssistCreateWorld);
        cancelCreateWorldBtn.addEventListener('click', () => showView('main-menu-view'));

        // Game
        actionForm.addEventListener('submit', handleActionSubmit);
        backToMenuBtn.addEventListener('click', loadAndShowMainMenu);
        changeGameAiBtn.addEventListener('click', () => {
            if (state.currentSessionId) {
                handleChangeGameAi(state.currentSessionId);
            } else {
                alert("没有正在进行的游戏。");
            }
        });

        // AI Config View
        backToMenuFromConfigBtn.addEventListener('click', () => showView('main-menu-view'));
        showAddConfigModalBtn.addEventListener('click', () => openAiConfigModal());

        // AI Config Modal
        closeModalBtn.addEventListener('click', closeAiConfigModal);
        aiConfigModal.addEventListener('click', (e) => {
            if (e.target === aiConfigModal) closeAiConfigModal();
        });
        aiConfigForm.addEventListener('submit', handleAiConfigFormSubmit);

        // AI Config List (Event Delegation)
        aiConfigList.addEventListener('click', (e) => {
            if (e.target.classList.contains('edit-config-btn')) {
                const configId = e.target.dataset.id;
                const config = state.aiConfigs.find(c => c.id == configId);
                openAiConfigModal(config);
            } else if (e.target.classList.contains('delete-config-btn')) {
                const configId = e.target.dataset.id;
                handleDeleteAiConfig(configId);
            } else if (e.target.classList.contains('set-active-config-btn')) {
                const configId = e.target.dataset.id;
                handleSetActiveAiConfig(configId);
            }
        });

        // Initial view check
        if (state.token) {
            loadAndShowMainMenu().catch(error => {
                console.error("Failed to auto-login with stored token:", error);
                // 如果自动登录失败（例如token过期），则清理并返回登录页
                handleLogout(); // Clear bad token and show auth view
            });
        } else {
            showView('auth-view');
        }
    }


    init();

});
