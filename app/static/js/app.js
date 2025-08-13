document.addEventListener('DOMContentLoaded', function() {
    // --- Constants & State ---
    const API_URL = '/api';
    const state = {
        accessToken: localStorage.getItem('access_token'), // 修改：更精确地命名为accessToken
        currentSessionId: null,
        activeAiConfigId: localStorage.getItem('active_ai_config_id'), // 新增：从本地存储加载激活的AI配置ID
        currentWorldName: null,
        lastPlayerAction: null, // 新增：存储上一次玩家的行动
        aiConfigs: [], // 新增：缓存用户的AI配置
    };


    // --- DOM Elements ---
    const views = document.querySelectorAll('.view');
    const authError = document.getElementById('auth-error');
    const globalError = document.getElementById('global-error'); // 新增：全局错误显示区域

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
            // 总是尝试发送 Cookie (如果启用)，即使是跨域请求
            'credentials': 'include',
            ...options.headers,
        };
        // 修改：使用 accessToken
        if (state.accessToken) {
            headers['Authorization'] = `Bearer ${state.accessToken}`;
        } 

        const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers });

        // 核心修改：处理 access token 过期的情况
        if (response.status === 401) {
            const responseData = await response.json();
            if (responseData && responseData.error === 'token_expired') {
                // 尝试刷新 access token
                const refreshSuccessful = await refreshToken();
                if (refreshSuccessful) {
                    // 刷新成功后，重新发起原始请求
                    return fetchWithAuth(endpoint, options);
                } else {
                    // 刷新失败，登出
                    handleLogout();
                    return null; // 确保调用者知道请求失败
                }
            } else {
                // 如果不是 token 过期错误，也登出
                // 修改：使用全局错误处理显示错误信息
                handleApiError('登录状态已过期，请重新登录。', handleLogout);
                return null;
            }
        }

        return response;
    }

    // --- Error Handling Module ---
    function handleApiError(message, retryCallback = null, feedback = false) {
        // 清空之前的错误信息和按钮
        globalError.innerHTML = '';

        globalError.textContent = message;
        globalError.style.display = 'block';

        if (retryCallback) {
            // 加个空格，让按钮和文字有点距离
            globalError.appendChild(document.createTextNode(' '));

            const retryBtn = document.createElement('button');
            retryBtn.textContent = '重试';
            retryBtn.onclick = () => {
                globalError.style.display = 'none';
                retryCallback();
            };
            globalError.appendChild(retryBtn);
        }

        if (feedback) {
            // TODO: Implement feedback mechanism (e.g., link to contact form)
            globalError.appendChild(document.createTextNode(' '));
            const feedbackLink = document.createElement('a');
            globalError.appendChild(feedbackLink);
        }
    }

    // 核心新增：刷新令牌的函数
    async function refreshToken() {
        const refreshToken = localStorage.getItem('refresh_token');
        if (!refreshToken) {
            console.warn("No refresh token available.");
            return false;
        }

        const response = await fetch('/api/refresh', { // 注意：这里没有使用 fetchWithAuth
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }) // 明确地传递 refresh token
        });

        const data = await response.json();
        if (response.ok) {
            localStorage.setItem('access_token', data.access_token);
            state.accessToken = data.access_token;
            return true;
        } else {
            console.error("Failed to refresh token:", data.error);
            return false;
        }
    }

    // --- View Management ---
    function showView(viewId) {
        // 清除全局错误提示
        globalError.style.display = 'none';
        globalError.innerHTML = '';
        
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
                // 存储 access token 和 refresh token
                state.accessToken = data.access_token;
                localStorage.setItem('access_token', data.access_token);
                localStorage.setItem('refresh_token', data.refresh_token);
                await loadAndShowMainMenu();
                console.log("Access Token received and stored:", state.accessToken);
                console.log("Refresh Token received and stored");
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
        state.accessToken = null;
        state.currentSessionId = null;
        state.currentWorldName = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        console.log("Logging out, token was:", state.accessToken); // Diagnostic log
        showView('auth-view');
    }

    async function handleDeleteSession(sessionId, elementToRemove) {
        // Ask for confirmation before this irreversible action
        if (!confirm(`你确定要删除这个纪传吗？此操作不可撤销。`)) {
            return;
        }

        try {
            const response = await fetchWithAuth(`/sessions/${sessionId}`, {
                method: 'DELETE',
            });

            if (response && response.ok) {
                // 如果有元素需要从DOM中移除
                if (elementToRemove) {
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
                    // 如果没有提供元素，则刷新整个会话列表
                    console.log('删除成功，正在刷新会话列表...');
                    await loadAndShowMainMenu();
                }
            } else {
                handleApiError('删除纪传失败，请重试。', () => handleDeleteSession(sessionId, elementToRemove));
            }
        } catch (error) {
            console.error('删除会话时发生错误:', error);
            handleApiError('删除纪传时发生错误，请重试。', () => handleDeleteSession(sessionId, elementToRemove));
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

        // 优先从按钮的data-session-id属性获取sessionId
        let sessionId = button.dataset.sessionId;
        
        // 如果按钮上没有sessionId，则从父元素.session-item获取
        if (!sessionId) {
            const itemElement = target.closest('.session-item');
            if (itemElement) {
                sessionId = itemElement.dataset.sessionId;
            }
        }
        
        // 确保我们有sessionId
        if (!sessionId) {
            console.error('无法获取会话ID');
            return;
        }
        
        const itemElement = target.closest('.session-item');
        
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
    
        // 添加前端验证，确保world_name不为空
        const worldName = document.getElementById('world-name').value.trim();
        if (!worldName) {
            handleApiError('世界创造失败: 创世设定不完整，必须提供 \'world_name\' 的内容。', null);
            return;
        }
    
        showWorldFormSkeleton();
        submitBtn.disabled = true;
        assistCreateWorldBtn.disabled = true;
        cancelCreateWorldBtn.disabled = true;
        submitBtn.textContent = '创造中...';
    
        try {
            // 核心修复：构建与后端 /worlds 端点期望的 `initial_settings` 结构完全匹配的JSON对象。
            const worldData = {
                world_name: worldName,
                character_description: document.getElementById('character-description').value.trim(),
                world_rules: document.getElementById('world-rules').value.trim(),
                initial_scene: document.getElementById('initial-scene').value.trim(),
                narrative_principles: document.getElementById('narrative-principles').value.trim(),
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
                handleApiError(`世界创造失败: ${errorData.details || errorData.error || '请检查输入或后台日志。'}`, () => handleCreateWorld(e));
            }
        } catch (error) {
            console.error('World creation failed:', error);
            handleApiError('创造世界时发生网络错误，请重试。', () => handleCreateWorld(e));
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
            world_name: document.getElementById('world-name').value.trim(),
            character_description: document.getElementById('character-description').value.trim(),
            world_rules: document.getElementById('world-rules').value.trim(),
            initial_scene: document.getElementById('initial-scene').value.trim(),
            narrative_principles: document.getElementById('narrative-principles').value.trim(),
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
    
                // 确保AI返回的world_name不为空，如果为空则保留用户原来输入的值
                const worldName = assistedData.world_name ? assistedData.world_name.trim() : currentData.world_name;
                document.getElementById('world-name').value = worldName;
    
                document.getElementById('character-description').value = assistedData.character_description || '';
                document.getElementById('world-rules').value = assistedData.world_rules || '';
                document.getElementById('initial-scene').value = assistedData.initial_scene || '';
                document.getElementById('narrative-principles').value = assistedData.narrative_principles || '';
                
                // 如果AI没有生成world_name，提示用户
                if (!worldName) {
                    alert('AI未能生成世界名称，请手动填写后再创建世界。');
                }
            } else {
                const errorData = response ? await response.json().catch(() => ({ error: '无法解析错误响应' })) : { error: '未知网络错误' };
                handleApiError(`AI辅助失败: ${errorData.error || '请稍后再试。'}`, handleAssistCreateWorld);
            }
        } catch (error) {
            console.error('AI辅助请求时发生网络错误:', error);
            handleApiError('AI辅助请求失败，请检查网络连接或稍后再试。', handleAssistCreateWorld);
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
            // 增加详细日志，便于调试后端返回的数据结构
            console.log("从后端收到的完整存档数据:", JSON.stringify(sessionData, null, 2));
            startGame(sessionData); // 将存档数据和操作意图一起传递
        } else {
            handleApiError('加载纪事失败，请重试。', () => loadSessionAndStartGame(sessionId));
            console.error("无法加载会话:", response);
        }
    }


    function startGame(sessionData) { // 负责根据数据渲染游戏界面
        console.log("startGame 函数接收到的数据:", sessionData);
        const currentState = sessionData.current_state;

        // 关键检查：确认存档数据是否有效。一个有效的存档必须包含 current_state。
        // 如果缺少，说明存档可能已损坏或后端未正确返回数据，这是导致问题的主要原因。
        if (!currentState) {
            console.error("存档数据无效或已损坏：缺少 'current_state'。无法继续游戏。", sessionData);
            handleApiError("加载存档失败：存档数据似乎已损坏或不完整，无法从上次的进度继续。");
            return; // 终止函数执行，防止游戏“重新开始”
        }

        state.currentSessionId = sessionData.session_id;
        state.currentWorldName = sessionData.world_name;

        gameWorldName.textContent = state.currentWorldName;
        gameLog.innerHTML = '';
        actionInput.value = '';
        renderPlayerStatus(currentState);

        showView('game-view');

        if (currentState.recent_history && currentState.recent_history.length > 0) {
            // 如果历史记录不为空，说明是正在进行的游戏，恢复所有状态
            console.log("检测到有效的游戏历史，正在恢复游戏进度...");
            // 历史记录是倒序存的（最新在前），所以渲染时要反转回来
            // 同时为AI生成的内容提供历史记录索引，以便编辑时同步到后端
            const reversedHistory = [...currentState.recent_history].reverse();
            reversedHistory.forEach((entry, displayIndex) => {
                // 计算在原始历史记录中的索引（因为显示时是反转的）
                const originalIndex = currentState.recent_history.length - 1 - displayIndex;
                const historyIndex = entry.role === 'assistant' ? originalIndex : null;
                appendLog(entry.content, entry.role, historyIndex);
            });

            // 如果是加载的旧游戏，恢复上次的建议选项
            console.log("已成功加载存档，正在恢复建议选项。");
            const lastAiResponse = currentState.last_ai_response || {};
            renderGameSuggestions(lastAiResponse.suggested_choices);
            // 确保日志滚动到底部
            gameLog.scrollTop = gameLog.scrollHeight;
        } else {
            // 如果历史记录为空，则这是一个新游戏或从未开始过的游戏。
            // 1. 显示创世时生成的初始场景描述。
            console.log("历史记录为空，开始新游戏流程...");
            if (currentState.current_location) {
                appendLog(currentState.current_location, 'ai');
            }
            // 2. 自动执行“环顾四周”来获取第一组互动选项，正式开始游戏。
            console.log("自动执行 '环顾四周' 以获取初始选项。");
            handleActionSubmit(null, "环顾四周");
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
        const originalRetryBtnText = retryAiBtn.textContent; // Store original text
        retryAiBtn.disabled = true; // Disable the button
        retryAiBtn.textContent = '重试中...'; // Change the text
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
            retryAiBtn.disabled = false; // Re-enable the button
            retryAiBtn.textContent = originalRetryBtnText; // Restore original text
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
            // 新生成的AI剧情总是添加到历史记录的开头（索引0）
            appendLog(data.description, 'ai', 0);
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


    function appendLog(text, type, historyIndex = null) {
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        
        // 为AI生成的剧情添加编辑功能
        if (type === 'ai') {
            const contentDiv = document.createElement('div');
            contentDiv.className = 'narrative-content';
            contentDiv.textContent = text;
            
            const editBtn = document.createElement('button');
            editBtn.className = 'edit-narrative-btn';
            editBtn.textContent = '编辑剧情';
            editBtn.onclick = () => editNarrative(entry, contentDiv, text, historyIndex);
            
            entry.appendChild(contentDiv);
            entry.appendChild(editBtn);
        } else {
            entry.textContent = text;
        }
        
        gameLog.appendChild(entry);
        gameLog.scrollTop = gameLog.scrollHeight; // Auto-scroll to bottom
    }

    // 剧情编辑功能
    function editNarrative(entryElement, contentDiv, originalText, historyIndex) {
        // 创建编辑界面
        const editContainer = document.createElement('div');
        editContainer.className = 'narrative-edit-container';
        
        const textarea = document.createElement('textarea');
        textarea.className = 'narrative-edit-textarea';
        textarea.value = originalText;
        textarea.rows = Math.max(3, originalText.split('\n').length + 1);
        
        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'narrative-edit-buttons';
        
        const saveBtn = document.createElement('button');
        saveBtn.className = 'save-narrative-btn';
        saveBtn.textContent = '保存修改';
        saveBtn.onclick = () => saveNarrativeEdit(entryElement, contentDiv, textarea.value, originalText, historyIndex);
        
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'cancel-narrative-btn';
        cancelBtn.textContent = '取消';
        cancelBtn.onclick = () => cancelNarrativeEdit(entryElement, contentDiv, originalText, historyIndex);
        
        buttonContainer.appendChild(saveBtn);
        buttonContainer.appendChild(cancelBtn);
        editContainer.appendChild(textarea);
        editContainer.appendChild(buttonContainer);
        
        // 替换内容为编辑界面
        entryElement.innerHTML = '';
        entryElement.appendChild(editContainer);
        
        // 聚焦到文本框
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }
    
    async function saveNarrativeEdit(entryElement, contentDiv, newText, originalText, historyIndex) {
        if (newText.trim() === '') {
            alert('剧情内容不能为空');
            return;
        }
        
        // 如果有历史记录索引，则同步到后端
        if (historyIndex !== null && historyIndex !== undefined) {
            try {
                const response = await fetchWithAuth(`/sessions/${state.currentSessionId}/update_narrative`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        narrative: newText,
                        history_index: historyIndex
                    })
                });
                
                if (!response.ok) {
                    const errorData = await response.json();
                    alert(`更新失败: ${errorData.error || '未知错误'}`);
                    return;
                }
                
                console.log('剧情已同步到后端历史记录');
            } catch (error) {
                console.error('同步剧情到后端失败:', error);
                alert('同步到服务器失败，修改仅在本地生效');
            }
        }
        
        // 恢复显示界面，使用新文本
        contentDiv.textContent = newText;
        
        const editBtn = document.createElement('button');
        editBtn.className = 'edit-narrative-btn';
        editBtn.textContent = '编辑剧情';
        editBtn.onclick = () => editNarrative(entryElement, contentDiv, newText, historyIndex);
        
        entryElement.innerHTML = '';
        entryElement.appendChild(contentDiv);
        entryElement.appendChild(editBtn);
        
        // 如果内容有变化，添加修改标记
        if (newText !== originalText) {
            entryElement.classList.add('narrative-edited');
            const editedMark = document.createElement('span');
            editedMark.className = 'narrative-edited-mark';
            editedMark.textContent = '(已修改)';
            entryElement.appendChild(editedMark);
        }
    }
    
    function cancelNarrativeEdit(entryElement, contentDiv, originalText, historyIndex) {
        // 恢复原始显示
        const editBtn = document.createElement('button');
        editBtn.className = 'edit-narrative-btn';
        editBtn.textContent = '编辑剧情';
        editBtn.onclick = () => editNarrative(entryElement, contentDiv, originalText, historyIndex);
        
        entryElement.innerHTML = '';
        entryElement.appendChild(contentDiv);
        entryElement.appendChild(editBtn);
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

        // 3. 渲染任务列表（聚合显示）
        questList.innerHTML = '';
        const activeQuests = currentState.active_quests || {};
        const completedQuests = currentState.completed_quests || [];
        
        // 显示活跃任务（最多显示5个）
        const activeQuestEntries = Object.entries(activeQuests);
        if (activeQuestEntries.length === 0) {
            questList.innerHTML = '<li class="quest-section"><strong>当前任务:</strong> 暂无</li>';
        } else {
            const questHeader = document.createElement('li');
            questHeader.className = 'quest-section';
            questHeader.innerHTML = `<strong>当前任务 (${activeQuestEntries.length}):</strong>`;
            questList.appendChild(questHeader);
            
            // 显示前5个活跃任务
            const displayQuests = activeQuestEntries.slice(0, 5);
            for (const [name, status] of displayQuests) {
                const li = document.createElement('li');
                li.className = 'quest-item';
                li.innerHTML = `• ${name}: ${status}`;
                questList.appendChild(li);
            }
            
            // 如果有更多任务，显示折叠提示
            if (activeQuestEntries.length > 5) {
                const moreQuests = document.createElement('li');
                moreQuests.className = 'quest-more';
                moreQuests.innerHTML = `<span class="quest-toggle" onclick="toggleQuestDetails()">... 还有 ${activeQuestEntries.length - 5} 个任务 (点击展开)</span>`;
                moreQuests.style.cursor = 'pointer';
                moreQuests.style.color = '#666';
                questList.appendChild(moreQuests);
            }
        }
        
        // 显示最近完成的任务（最多3个）
        if (completedQuests.length > 0) {
            const completedHeader = document.createElement('li');
            completedHeader.className = 'quest-section';
            completedHeader.innerHTML = `<strong>最近完成 (${completedQuests.length}):</strong>`;
            completedHeader.style.marginTop = '10px';
            questList.appendChild(completedHeader);
            
            const recentCompleted = completedQuests.slice(-3); // 显示最近3个
            for (const quest of recentCompleted) {
                const li = document.createElement('li');
                const isSuccess = quest.is_success !== false; // 默认为成功，除非明确标记为失败
                li.className = isSuccess ? 'quest-completed' : 'quest-failed';
                li.innerHTML = `• ${quest.name}: ${quest.status}`;
                if (isSuccess) {
                    li.style.color = '#28a745'; // 绿色表示成功
                } else {
                    li.style.color = '#dc3545'; // 红色表示失败
                }
                li.style.fontSize = '0.9em';
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

    // --- Quest Management Logic ---
    let questDetailsExpanded = false;
    
    // 将函数设为全局，以便HTML onclick可以调用
    window.toggleQuestDetails = function() {
        const questList = document.getElementById('quest-list');
        const activeQuests = state.currentState?.active_quests || {};
        const activeQuestEntries = Object.entries(activeQuests);
        
        if (!questDetailsExpanded && activeQuestEntries.length > 5) {
            // 展开显示所有任务
            questDetailsExpanded = true;
            
            // 移除"更多任务"提示
            const moreQuestsElement = questList.querySelector('.quest-more');
            if (moreQuestsElement) {
                moreQuestsElement.remove();
            }
            
            // 添加剩余的任务
            const remainingQuests = activeQuestEntries.slice(5);
            for (const [name, status] of remainingQuests) {
                const li = document.createElement('li');
                li.className = 'quest-item quest-expanded';
                li.innerHTML = `• ${name}: ${status}`;
                questList.appendChild(li);
            }
            
            // 添加折叠按钮
            const collapseBtn = document.createElement('li');
            collapseBtn.className = 'quest-more';
            collapseBtn.innerHTML = `<span class="quest-toggle" onclick="toggleQuestDetails()">收起任务列表</span>`;
            collapseBtn.style.cursor = 'pointer';
            collapseBtn.style.color = '#666';
            questList.appendChild(collapseBtn);
        } else if (questDetailsExpanded) {
            // 折叠任务列表
            questDetailsExpanded = false;
            renderPlayerStatus(state.currentState); // 重新渲染任务列表
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
                handleApiError('更新AI配置失败，请重试。', () => handleChangeGameAi(sessionId));
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
            handleApiError('获取AI配置失败，请重试。', showAiConfigView);
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
            handleApiError(`保存失败: ${errorData.error}`, () => handleAiConfigFormSubmit(e));
       }
    }


    async function handleDeleteAiConfig(configId) {
        if (!confirm('确定要删除这个AI配置吗？')) return;

        const response = await fetchWithAuth(`/ai-configs/${configId}`, { method: 'DELETE' });
        if (response && response.ok) {
            await showAiConfigView();
        } else {
            handleApiError('删除失败，请重试。', () => handleDeleteAiConfig(configId));
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

        // 初始化时隐藏全局错误区域
        globalError.style.display = 'none';

        // Initial view check
        if (state.accessToken) {
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
