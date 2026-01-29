let currentPath = window.SERVER_CONFIG.projectRoot;
let currentSource = 'runtime';

// Tabs
function switchTab(id) {
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    
    document.getElementById(id).classList.add('active');
    const btn = Array.from(document.querySelectorAll('.nav-btn')).find(b => b.getAttribute('onclick').includes(id));
    if(btn) btn.classList.add('active');
}

function setMode(mode) {
    currentSource = mode;
    const badge = document.getElementById('mode-badge');
    const input = document.getElementById('addr');
    
    if (mode === 'build') {
        badge.style.display = 'inline-block';
        input.style.borderColor = '#d29922';
    } else {
        badge.style.display = 'none';
        input.style.borderColor = 'var(--border)';
    }
    refresh();
}

async function nav(path) {
    currentPath = path;
    document.getElementById('addr').value = path;
    const tbody = document.getElementById('file-list');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding: 20px;">Loading...</td></tr>';

    try {
        const res = await fetch(`/api/list?path=${encodeURIComponent(path)}&source=${currentSource}`);
        if(!res.ok) throw await res.text();
        const data = await res.json();
        
        tbody.innerHTML = '';
        if(!data.items || data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding: 20px; color: var(--text-muted)">Directory is empty</td></tr>';
            return;
        }

        data.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.className = 'item-row';
            const icon = item.is_dir ? '📁' : '📄';
            
            // Action Buttons
            let actions = '';
            if (!item.is_dir && currentSource === 'runtime') {
                actions += `<button class="btn" style="padding:2px 6px; margin-right:5px" onclick="event.stopPropagation(); window.open('/api/download?path=${encodeURIComponent(item.path)}')">⬇</button>`;
                actions += `<button class="btn" style="padding:2px 6px; color:var(--danger)" onclick="del(event, '${item.path}')">✕</button>`;
            } else if (!item.is_dir && currentSource === 'build') {
                actions = '<span class="text-muted" style="font-size:11px">Read Only</span>';
            }

            tr.innerHTML = `
                <td><span class="icon">${icon}</span> ${item.name}</td>
                <td style="font-family:var(--mono); color:var(--text-muted)">${item.size}</td>
                <td><span class="tag">${item.ext || 'DIR'}</span></td>
                <td style="text-align:right">${actions}</td>
            `;
            tr.onclick = (e) => {
                if(e.target.tagName === 'BUTTON') return;
                if (item.is_dir) nav(item.path);
                else if (currentSource === 'runtime') viewFile(item.path);
                else alert("Build snapshot files cannot be viewed directly via API.");
            };
            tbody.appendChild(tr);
        });
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-danger" style="text-align:center; padding: 20px;">Error: ${e}</td></tr>`;
    }
}

function upDir() {
    const parts = currentPath.split('/').filter(p => p);
    parts.pop();
    nav(parts.length ? '/' + parts.join('/') : '/');
}

function refresh() { nav(currentPath); }

// File Viewing
async function viewFile(path) {
    const res = await fetch(`/api/view?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    document.getElementById('modal-title').innerText = path.split('/').pop();
    document.getElementById('modal-text').innerText = data.content || data.error;
    document.getElementById('file-modal').style.display = 'flex';
}
function closeModal() { document.getElementById('file-modal').style.display = 'none'; }

// Deletion
async function del(e, path) {
    e.stopPropagation();
    if(!confirm(`Delete ${path}?`)) return;
    await fetch(`/api/delete?path=${encodeURIComponent(path)}`);
    refresh();
}

// Terminal
const termIn = document.getElementById('term-in');
const termOut = document.getElementById('term-out');
termIn.addEventListener('keypress', async (e) => {
    if(e.key === 'Enter') {
        const cmd = termIn.value;
        termIn.value = '';
        termOut.innerText += `\n$ ${cmd}`;
        if(cmd === 'clear') { termOut.innerText = ''; return; }
        
        try {
            const res = await fetch(`/api/shell?cmd=${encodeURIComponent(cmd)}`);
            const data = await res.json();
            termOut.innerText += `\n${data.out}`;
        } catch(e) {
            termOut.innerText += `\nError: ${e}`;
        }
        termOut.scrollTop = termOut.scrollHeight;
    }
});

// Stats
async function loadStats() {
    const res = await fetch('/api/stats');
    const data = await res.json();
    
    // Runtime Info
    const info = data.runtime;
    document.getElementById('sys-info').innerHTML = `
        <b>OS:</b> ${info.os} (${info.platform})<br>
        <b>Python:</b> ${info.python} &nbsp;|&nbsp; <b>Glibc:</b> ${info.glibc}<br>
        <b>AV Support:</b> ${data.av}<br>
        <b>Build Index:</b> ${data.has_build_index ? '<span class="text-success">✅ Loaded</span>' : '<span class="text-danger">❌ Missing</span>'}
    `;

    // Inodes
    const iBody = document.getElementById('inode-list');
    iBody.innerHTML = '';
    data.inodes.forEach(i => {
         iBody.innerHTML += `<tr><td style="font-family:var(--mono)">${i.path}</td><td style="font-family:var(--mono)">${i.inode}</td><td>${i.status}</td></tr>`;
    });

    // Tools
    const tBody = document.getElementById('tool-comp-list');
    tBody.innerHTML = '';
    data.tools.forEach(t => {
        const cls = t.status.includes('❌') ? 'text-danger' : t.status.includes('⛔') ? 'text-muted' : 'text-success';
        tBody.innerHTML += `<tr><td><b>${t.name}</b></td><td style="font-family:var(--mono);font-size:12px">${t.build}</td><td style="font-family:var(--mono);font-size:12px">${t.runtime}</td><td class="${cls}">${t.status}</td></tr>`;
    });

    // Storage
    const sList = document.getElementById('storage-list');
    sList.innerHTML = '';
    data.storage.forEach(s => {
        let rawSize = parseFloat(s.size); 
        if(s.size.includes('MB')) rawSize *= 1024*1024;
        if(s.size.includes('KB')) rawSize *= 1024;
        const pct = Math.min(100, (rawSize / (512*1024*1024)) * 100);
        
        sList.innerHTML += `
            <div style="margin-bottom:12px">
                <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px">
                    <span>${s.label} <span class="text-muted" style="font-size:11px">(${s.path})</span></span>
                    <span style="font-family:var(--mono)">${s.size}</span>
                </div>
                <div class="stat-bar"><div class="stat-fill" style="width:${pct}%"></div></div>
            </div>
        `;
    });
}

// TestFly
async function runFly() {
    const out = document.getElementById('fly-out');
    const provider = document.getElementById('fly-provider').value;
    const key = document.getElementById('fly-key').value;
    
    const payload = {
        url: document.getElementById('fly-url').value,
        cookies: document.getElementById('fly-cookies').value,
        chunk_size: document.getElementById('fly-chunk').value,
        limit_rate: document.getElementById('fly-limit').value,
        wait_time: document.getElementById('fly-wait').value,
        player_clients: document.getElementById('fly-clients').value,
        po_token: document.getElementById('fly-token').value,
        provider: provider,
        mode: document.getElementById('fly-mode').value,
        deepgram_key: (provider === 'deepgram') ? key : "",
        assemblyai_key: (provider === 'assemblyai') ? key : "",
        only_list_formats: document.getElementById('fly-list-formats').checked
    };
    
    if(!payload.url) return alert("Target URL is required");

    out.innerText = "🚀 Job Started...\n";
    
    try {
        const res = await fetch('/api/fly', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify(payload) 
        });
        
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        
        while(true) {
            const {value, done} = await reader.read();
            if(done) break;
            out.innerText += decoder.decode(value, {stream: true});
            out.scrollTop = out.scrollHeight;
        }
        out.innerText += "\n✅ Stream Closed.";
    } catch(e) { 
        out.innerText += `\n❌ Error: ${e}`; 
    }
}

// Init
nav(currentPath);