let modalMode = 'monitor'; 

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-links a').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    document.getElementById(`nav-${tabId}`).classList.add('active');

    if (tabId === 'home') setTimeout(renderWordCloud, 100);
    if (tabId === 'trend') { 
        // 1. 先加载监控列表和本地缓存趋势（瞬间完成，不用等网络）
        loadMonitorList(); 
        setTimeout(loadTrendChart, 100); 
        
        // 2. 加载情绪雷达（需要请求大模型，较慢）
        loadSentimentChart(); 
        
        // 3. 最后再在后台静默抓取最新粉丝数（因为有了并发，速度已经很快）
        loadCurrentFans(); 
    }
}

// 🌟 检查并显示预警横幅
async function checkAlerts() {
    try {
        const res = await fetch('/api/alerts');
        const data = await res.json();
        const banner = document.getElementById('alert-banner');
        if (data.alerts && data.alerts.length > 0) {
            let html = `<ul style="margin:0; padding-left:20px;">`;
            data.alerts.forEach(a => { html += `<li>[${a.time}] ${a.message}</li>`; });
            html += `</ul>`;
            banner.innerHTML = `🚨 <strong>智能体预警通知</strong> ${html}`;
            banner.style.display = 'block';
        } else {
            banner.style.display = 'none';
        }
    } catch(e) { console.log(e); }
}
window.onload = () => { renderWordCloud(); checkAlerts(); };

// ================= 首页词云 =================
let chartInstance = null;
function renderWordCloud() {
    let history = JSON.parse(localStorage.getItem('searchHistory') || '[]');
    const chartDom = document.getElementById('word-cloud');
    if (!chartDom) return;
    if (history.length === 0) { 
        chartDom.innerHTML = '<p style="text-align:center;color:#6ee7b7;padding-top:150px;">暂无搜索记录，快去微博追踪探索吧！</p>'; return; 
    }
    chartDom.style.width = '100%'; chartDom.style.height = '400px';
    if (!chartInstance) chartInstance = echarts.init(chartDom);
    const data = history.map(name => ({ name: name, value: Math.floor(Math.random() * 50) + 10 }));
    chartInstance.setOption({
        tooltip: { show: true },
        series: [{ type: 'wordCloud', shape: 'circle', sizeRange: [18, 80], rotationRange: [-45, 45], textStyle: { color: () => `hsl(${Math.random()*360}, 70%, 50%)` }, data: data }]
    });
    chartInstance.resize();
}

// ================= 微博追踪 =================
async function searchWeibo() {
    const inputVal = document.getElementById('weibo-names').value.trim();
    if(!inputVal) return;
    
    let names = inputVal.split(/[,，\s]+/).map(n => n.trim()).filter(n => n);
    if (names.length === 0) return;

    // 将所有的名字放入队列，并标记为“抓取微博”模式
    currentSearchQueue = [...names]; 
    modalMode = 'weibo'; 
    
    // 处理队列中的第一个名字
    processWeiboQueueItem();
}

// 新增：专门处理“抓取微博”模式下的队列
async function processWeiboQueueItem() {
    if (currentSearchQueue.length === 0) {
        return; // 队列为空，结束
    }
    
    let nextName = currentSearchQueue.shift();
    
    document.getElementById('user-select-modal').style.display = 'flex';
    document.getElementById('modal-search-term').innerText = nextName;
    document.getElementById('candidate-list').innerHTML = '<p style="text-align:center;">⏳ 正在获取候选账号...</p>';
    
    currentConfirmList = []; 
    
    try {
        const res = await fetch(`/api/search_users?query=${encodeURIComponent(nextName)}`);
        const data = await res.json();
        
        if (!data.users || data.users.length === 0) {
            // 没搜到，直接按原名加入最终抓取列表，跳过弹窗
            console.warn(`未找到 "${nextName}" 的候选账号，将使用原名抓取`);
            // 这里我们需要一个临时变量来收集所有最终要抓取的名字
            if (!window.finalWeiboSearchNames) window.finalWeiboSearchNames = [];
            window.finalWeiboSearchNames.push(nextName);
            
            // 继续处理下一个
            document.getElementById('user-select-modal').style.display = 'none';
            processWeiboQueueItem();
            return;
        }

        let html = '';
        data.users.forEach((u, index) => {
            let defaultAvatar = `https://api.dicebear.com/7.x/avataaars/svg?seed=${u.screen_name}`;
            let isChecked = (index === 0) ? 'checked' : '';
            
            html += `
            <label style="display:flex; align-items:center; gap:10px; padding:10px; border:1px solid #e5e7eb; border-radius:8px; cursor:pointer;">
                <input type="checkbox" value="${u.screen_name}" onchange="updateConfirmList(this)" ${isChecked}>
                <img src="${u.avatar || defaultAvatar}" referrerpolicy="no-referrer" onerror="this.src='${defaultAvatar}'" style="width:40px; height:40px; border-radius:50%; object-fit:cover; background:#f3f4f6;">
                <div style="flex:1;">
                    <div style="font-weight:bold; color:#065f46;">${u.screen_name}</div>
                    <div style="font-size:0.8rem; color:#666;">粉丝: ${u.followers}</div>
                </div>
            </label>`;
        });
        
        document.getElementById('candidate-list').innerHTML = html;
        currentConfirmList = [data.users[0].screen_name]; 
        
    } catch (e) {
        console.error(e);
        document.getElementById('user-select-modal').style.display = 'none';
        processWeiboQueueItem();
    }
}

// 🌟 新增：真正去抓取微博的函数
async function executeWeiboSearch(namesStr) {
    const resultsArea = document.getElementById('weibo-results');
    
    // 保存搜索历史
    let history = JSON.parse(localStorage.getItem('searchHistory') || '[]');
    let newNames = namesStr.split(/[,，\s]+/).map(n => n.trim()).filter(n => n);
    history = [...new Set([...newNames, ...history])].slice(0, 30);
    localStorage.setItem('searchHistory', JSON.stringify(history));

    resultsArea.innerHTML = '<p>⏳ 正在抓取微博动态，请稍候...</p>';
    try {
        const res = await fetch(`/api/weibo?nicknames=${encodeURIComponent(namesStr)}&limit=5`);
        const data = await res.json();
        
        // 如果你后端报错了（比如反爬），会走这里
        if (data.error) {
            resultsArea.innerHTML = `<p style="color:red;">❌ 抓取异常: ${data.error}</p>`;
            return;
        }

        let html = '';
        if (data.images && data.images.length > 0) {
            html += `<div class="image-wall">`; data.images.forEach(img => { html += `<img src="${img}" />`; }); html += `</div>`;
        }
        if(data.summary) html += `<div class="card"><h3>🌿 AI 总结</h3><p style="line-height:1.8;">${data.summary}</p></div>`;
        
        for (const [name, posts] of Object.entries(data.posts || {})) {
            html += `<div class="card"><h3>👤 ${name}</h3>`;
            posts.forEach(p => { html += `<p style="margin:10px 0;">[${p.time}] ${p.content.substring(0, 80)}... <a href="${p.url}" target="_blank" style="color:#10b981;">查看原帖</a></p>`; });
            html += `</div>`;
        }
        
        if (!html) html = '<p style="text-align:center; color:#666;">未抓取到动态，可能是该账号近期无发文。</p>';
        resultsArea.innerHTML = html;
        
    } catch (e) { 
        resultsArea.innerHTML = `<p style="color:red;">❌ 网络请求失败: ${e.message}</p>`; 
    }
}

// ================= 监控列表管理 =================
async function loadMonitorList() {
    const container = document.getElementById('monitor-list-container');
    try {
        const res = await fetch('/api/monitor/list');
        const data = await res.json();
        if (!data.names || data.names.length === 0) { container.innerHTML = '<p style="color:#86868b;">还没有监控任何人，快去添加吧。</p>'; return; }
        let html = '';
        data.names.forEach(name => {
            html += `<div style="background:#ecfdf5; border:1px solid #a7f3d0; padding: 5px 15px; border-radius: 20px; display: flex; align-items: center; gap: 10px;">
                <span style="color:#065f46; font-weight:600;">${name}</span>
                <span onclick="removeMonitor('${name}')" style="cursor:pointer; color:#ef4444; font-weight:bold;">✕</span></div>`;
        });
        container.innerHTML = html;
    } catch (e) { container.innerHTML = ''; }
}

async function removeMonitor(name) {
    if (!confirm(`确定不再监控 ${name} 吗？`)) return;
    await fetch(`/api/monitor/remove?name=${encodeURIComponent(name)}`);
    await loadMonitorList(); loadCurrentFans(); loadTrendChart(); loadSentimentChart();
}

// ================= 添加监控核心逻辑 (Agent工作流) =================
let currentSearchQueue = [];
let currentGroupData = null; 
let currentConfirmList = [];

async function addMonitor() {
    const inputVal = document.getElementById('add-monitor-name').value.trim();
    if (!inputVal) return;
    
    let namesToAdd = inputVal.split(/[,，\s]+/).map(n => n.trim()).filter(n => n);
    let firstQuery = namesToAdd[0]; 
    currentSearchQueue = namesToAdd.slice(1);

    currentGroupData = null; 
    document.getElementById('group-official-name').innerText = '...';
    document.getElementById('group-member-count').innerText = '...';
    document.getElementById('group-modal-query').innerText = firstQuery;
    
    const loadingEl = document.getElementById('group-loading');
    if(loadingEl) loadingEl.style.display = 'inline'; 
    
    document.getElementById('group-select-modal').style.display = 'flex';
    
    try {
        const res = await fetch(`/api/check_group?query=${encodeURIComponent(firstQuery)}`);
        const data = await res.json();
        
        if(loadingEl) loadingEl.style.display = 'none'; 

        if (data.is_group && data.members && data.members.length > 0) {
            currentGroupData = data;
            document.getElementById('group-official-name').innerText = data.group_name;
            document.getElementById('group-member-count').innerText = data.members.length;
            document.getElementById('group-opt-official').checked = true;
            document.getElementById('group-opt-members').checked = true;
        } else {
            document.getElementById('group-select-modal').style.display = 'none';
            currentSearchQueue.unshift(firstQuery); 
            processNextQueueItem();
        }
    } catch(e) {
        console.error(e);
        if(loadingEl) loadingEl.style.display = 'none';
        document.getElementById('group-select-modal').style.display = 'none';
        currentSearchQueue.unshift(firstQuery);
        processNextQueueItem();
    }
}

function confirmGroupSelection() {
    // 🌟 核心修复：加上安全锁。如果数据还没加载好就点确认，直接拦截！
    if (!currentGroupData) {
        alert("⏳ 正在智能解析组合信息，请稍等1-2秒再点击！");
        return;
    }

    document.getElementById('group-select-modal').style.display = 'none';
    
    let selectedNames = [];
    if (document.getElementById('group-opt-official').checked) {
        selectedNames.push(currentGroupData.group_name);
    }
    if (document.getElementById('group-opt-members').checked) {
        selectedNames = selectedNames.concat(currentGroupData.members);
    }
    
    // 将用户勾选的名字，全部塞进待确认队列的最前面
    currentSearchQueue = [...selectedNames, ...currentSearchQueue];
    
    // 开始依次弹出“账号精准确认”的窗口
    processNextQueueItem();
}

function closeGroupModal() {
    document.getElementById('group-select-modal').style.display = 'none';
    currentSearchQueue = [];
}

async function processNextQueueItem() {
    if (currentSearchQueue.length === 0) {
        document.getElementById('add-monitor-name').value = '';
        await loadMonitorList();
        loadCurrentFans(); 
        loadSentimentChart();
        return;
    }
    let nextName = currentSearchQueue.shift();
    await searchAndShowModal(nextName);
}

async function searchAndShowModal(name) {
    document.getElementById('user-select-modal').style.display = 'flex';
    document.getElementById('modal-search-term').innerText = name;
    document.getElementById('candidate-list').innerHTML = '<p style="text-align:center;">⏳ 正在获取候选账号...</p>';
    
    const masterCheckbox = document.getElementById('select-all-users');
    if (masterCheckbox) masterCheckbox.checked = false;
    
    currentConfirmList = []; 

    try {
        const res = await fetch(`/api/search_users?query=${encodeURIComponent(name)}`);
        const data = await res.json();
        
        if (!data.users || data.users.length === 0) {
            document.getElementById('candidate-list').innerHTML = `<p style="color:red; text-align:center;">未找到“${name}”的账号，自动跳过。</p>`;
            setTimeout(() => { closeModal(); processNextQueueItem(); }, 1500);
            return;
        }

        let html = '';
        data.users.forEach((u, index) => {
            let defaultAvatar = `https://api.dicebear.com/7.x/avataaars/svg?seed=${u.screen_name}`;
            let isChecked = (index === 0) ? 'checked' : '';
            
            html += `
            <label style="display:flex; align-items:center; gap:10px; padding:10px; border:1px solid #e5e7eb; border-radius:8px; cursor:pointer;">
                <input type="checkbox" value="${u.screen_name}" onchange="updateConfirmList(this)" ${isChecked}>
                <img src="${u.avatar || defaultAvatar}" referrerpolicy="no-referrer" onerror="this.src='${defaultAvatar}'" style="width:40px; height:40px; border-radius:50%; object-fit:cover; background:#f3f4f6;">
                <div style="flex:1;">
                    <div style="font-weight:bold; color:#065f46;">${u.screen_name}</div>
                    <div style="font-size:0.8rem; color:#666;">粉丝: ${u.followers}</div>
                </div>
            </label>`;
        });
        
        document.getElementById('candidate-list').innerHTML = html;
        currentConfirmList = [data.users[0].screen_name];
        
    } catch (e) {
        document.getElementById('candidate-list').innerHTML = '<p style="color:red;">搜索失败</p>';
    }
}

function toggleSelectAll(masterCheckbox) {
    const isChecked = masterCheckbox.checked;
    const checkboxes = document.querySelectorAll('#candidate-list input[type="checkbox"]');
    currentConfirmList = []; 

    checkboxes.forEach(cb => {
        cb.checked = isChecked;
        if (isChecked) {
            currentConfirmList.push(cb.value);
        }
    });
}

function updateConfirmList(checkbox) {
    if (checkbox.checked) {
        if(!currentConfirmList.includes(checkbox.value)){
            currentConfirmList.push(checkbox.value);
        }
    } else {
        currentConfirmList = currentConfirmList.filter(n => n !== checkbox.value);
    }

    const allCheckboxes = document.querySelectorAll('#candidate-list input[type="checkbox"]');
    const checkedCheckboxes = document.querySelectorAll('#candidate-list input[type="checkbox"]:checked');
    const masterCheckbox = document.getElementById('select-all-users');
    if (masterCheckbox) {
        masterCheckbox.checked = (allCheckboxes.length === checkedCheckboxes.length && allCheckboxes.length > 0);
    }
}

// 取消：直接放弃这一批次的添加
function closeModal() {
    document.getElementById('user-select-modal').style.display = 'none';
    currentSearchQueue = []; 
    modalMode = 'monitor'; // 🌟 核心：用完弹窗，状态重置回默认
}

// 确认添加：提交当前选中的账号，继续处理下一个
async function confirmAddMonitor() {
    if (currentConfirmList.length === 0) {
        alert("请至少勾选一个账号！");
        return;
    }
    
    if (modalMode === 'weibo') {
        // 初始化收集数组
        if (!window.finalWeiboSearchNames) window.finalWeiboSearchNames = [];
        // 把当前确认的名字加入总列表
        window.finalWeiboSearchNames.push(...currentConfirmList);
        
        closeModal(); 
        
        // 如果队列里还有名字，继续弹窗确认
        if (currentSearchQueue.length > 0) {
            processWeiboQueueItem();
        } else {
            // 所有名字都确认完了，真正开始抓取
            executeWeiboSearch(window.finalWeiboSearchNames.join(","));
            window.finalWeiboSearchNames = []; // 清空
        }
    } else {
        for (let name of currentConfirmList) {
            await fetch(`/api/monitor/add?name=${encodeURIComponent(name)}`);
        }
        closeModal(); 
        processNextQueueItem(); 
    }
}

// ================= 数据展示与图表 =================
async function loadCurrentFans() {
    const container = document.getElementById('current-fans-container');
    if(container.innerHTML.trim() === '') {
        container.innerHTML = '<p>⏳ 正在并发获取最新粉丝数...</p>';
    }
    try {
        const res = await fetch('/api/fans/current');
        const data = await res.json();
        if (!data.current || data.current.length === 0) { container.innerHTML = '<p>监控列表为空</p>'; return; }
        let html = '';
        data.current.forEach(item => {
            let numStr = item.followers >= 10000 ? (item.followers / 10000).toFixed(1) + ' 万' : item.followers;
            html += `<div class="card" style="flex: 1; min-width: 200px; text-align: center; padding: 20px; margin-bottom: 0;">
                <h3 style="color: #065f46;">${item.name}</h3>
                <p style="font-size: 2rem; font-weight: 800; color: #10b981; margin: 0;">${numStr}</p>
            </div>`;
        });
        container.innerHTML = html;
        loadTrendChart(); 
    } catch (e) { }
}

let sentimentChartInstance = null;
async function loadSentimentChart() {
    const chartDom = document.getElementById('sentiment-chart');
    const loadingText = document.getElementById('sentiment-loading');
    if (!chartDom) return;
    loadingText.style.display = 'block';
    if (!sentimentChartInstance) sentimentChartInstance = echarts.init(chartDom);

    try {
        const res = await fetch('/api/sentiment');
        const data = await res.json();
        let option = {
            tooltip: { trigger: 'item', formatter: '{b}: {c}条 ({d}%)' },
            legend: { bottom: '0%', left: 'center', textStyle: { color: '#047857' } },
            series: [{
                name: '情绪占比', type: 'pie', radius: ['45%', '70%'], avoidLabelOverlap: false,
                itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
                label: { show: true, formatter: '{b}\n{c}条', color: '#047857' },
                data: [
                    { value: data.positive || 0, name: '夸夸 (正向)', itemStyle: { color: '#10b981' } },
                    { value: data.negative || 0, name: '吐槽 (负向)', itemStyle: { color: '#ef4444' } },
                    { value: data.neutral || 0,  name: '吃瓜 (中立)', itemStyle: { color: '#94a3b8' } }
                ]
            }]
        };
        sentimentChartInstance.setOption(option, true);
        checkAlerts();
    } catch (e) { console.error(e); } finally { loadingText.style.display = 'none'; }
}

let trendChartInstance = null;
async function loadTrendChart() {
    const chartDom = document.getElementById('trend-chart');
    if (!chartDom) return;
    
    chartDom.style.width = '100%'; chartDom.style.height = '450px';
    if (!trendChartInstance) trendChartInstance = echarts.init(chartDom);
    
    try {
        const res = await fetch('/api/trend');
        const data = await res.json();
        
        if (!data.trends || data.trends.length === 0) { 
            trendChartInstance.clear();
            chartDom.innerHTML = "<div style='text-align:center; padding-top:150px; color:#10b981;'>暂无数据，请先添加监控账号</div>"; 
            return; 
        }
        
        let dates = [...new Set(data.trends.map(t => t.date))];
        let series = [];
        let names = [...new Set(data.trends.map(t => t.name))];
        const colors = ['#059669', '#3b82f6', '#f59e0b', '#8b5cf6', '#ef4444', '#ec4899', '#06b6d4', '#14b8a6', '#f97316', '#6366f1', '#d946ef', '#84cc16'];
        
        names.forEach((name, index) => {
            let followersData = dates.map(date => {
                let item = data.trends.find(t => t.date === date && t.name === name);
                return item && item.followers != null ? Number(item.followers) : null;
            });
            series.push({ 
                name: name, type: 'line', smooth: true, data: followersData, 
                itemStyle: { color: colors[index % colors.length] }, lineStyle: { width: 3 },
                symbolSize: 8
            });
        });

        if (dates.length === 1) {
            dates = [dates[0], ' ']; 
            series.forEach(s => s.data.push(null)); 
        }

        trendChartInstance.setOption({
            tooltip: { 
                trigger: 'axis',
                formatter: function(params) {
                    let html = params[0].axisValue + '<br/>';
                    params.forEach(p => {
                        if (p.value) html += `${p.marker} ${p.seriesName}: ${p.value} <br/>`;
                    });
                    return html;
                }
            },
            legend: { top: '0%', type: 'scroll', pageIconColor: '#10b981', pageTextStyle: { color: '#047857' }, textStyle: { color: '#047857' } }, 
            grid: { left: '5%', right: '5%', bottom: '10%', top: '15%', containLabel: true },
            xAxis: { type: 'category', data: dates, boundaryGap: false },
            yAxis: { type: 'value', scale: true, splitNumber: 5, axisLabel: { formatter: value => value >= 10000 ? (value / 10000).toFixed(0) + '万' : value } },
            series: series,
            dataZoom: dates.length <= 3 ? [] : [{ type: 'inside', start: 0, end: 100 }, { type: 'slider', height: 20, bottom: 0 }]
        }, true); 
        
        trendChartInstance.resize();
    } catch (e) { console.error(e); }
}

async function generateDraft() {
    const names = document.getElementById('draft-names').value;
    const resultDiv = document.getElementById('draft-result');
    resultDiv.style.display = 'block';
    resultDiv.innerText = '⏳ 主笔正在写作，主编正在审查中...';
    try {
        const res = await fetch(`/api/generate_draft?nicknames=${encodeURIComponent(names)}`);
        const data = await res.json();
        resultDiv.innerText = data.draft;
    } catch (e) { resultDiv.innerText = '生成失败'; }
}

async function askAI() {
    const query = document.getElementById('ai-query').value;
    if (!query) return;
    const chatBox = document.getElementById('chat-box');
    chatBox.innerHTML += `<div class="message user">${query}</div><div class="message ai" id="loading-msg">正在搜索...</div>`;
    chatBox.scrollTop = chatBox.scrollHeight;
    try {
        const res = await fetch(`/api/chat?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        document.getElementById('loading-msg').outerHTML = `<div class="message ai">${data.answer}</div>`;
    } catch (e) { document.getElementById('loading-msg').outerHTML = `<div class="message ai">请求失败</div>`; }
}

window.addEventListener('resize', () => { 
    if (chartInstance) chartInstance.resize(); 
    if (sentimentChartInstance) sentimentChartInstance.resize();
    if (trendChartInstance) trendChartInstance.resize();
});
