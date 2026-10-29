/**
 * 沿长科技 · 音乐创作主 Agent 协同控制台 (Cyber-Studio Web App)
 */

// Global App State
let currentProjectId = "";
let projectDetail = null;
let presetBriefs = [];
let audioContext = null;
let audioSource = null;
let analyserNode = null;
let animFrameId = null;
let isAudioPlaying = false;
let currentRejectStage = "lyrics";
let projectPollTimer = null;
let projectIsRunning = false;
let cachedRuntimeStatus = null;
let isLyricsDiffView = false;

const FSM_STEPS = [
  { key: "new", name: "需求定界" },
  { key: "lyrics_ready", name: "歌词初稿" },
  { key: "lyrics_approved", name: "歌词审批" },
  { key: "audio_ready", name: "音频合成" },
  { key: "audio_approved", name: "音频审批" },
  { key: "package_ready", name: "发行封包" },
];

// Document Ready
document.addEventListener("DOMContentLoaded", () => {
  initUIElements();
  initAudioPlayer();
  loadProjectsList();
  loadPresetBriefs();
  loadRuntimeStatus();
});

function initUIElements() {
  document.getElementById("projectSelect").addEventListener("change", (e) => {
    if (e.target.value) {
      loadProject(e.target.value);
    }
  });

  document.getElementById("btnNewProject").addEventListener("click", () => {
    document.getElementById("modalNewBrief").classList.remove("hidden");
  });

  document.getElementById("btnCloseNewBriefModal").addEventListener("click", () => {
    document.getElementById("modalNewBrief").classList.add("hidden");
  });
  document.getElementById("btnCancelNewBrief").addEventListener("click", () => {
    document.getElementById("modalNewBrief").classList.add("hidden");
  });

  document.getElementById("btnSubmitNewBrief").addEventListener("click", handleCreateProject);

  document.getElementById("btnCloseRejectModal").addEventListener("click", () => {
    document.getElementById("modalReject").classList.add("hidden");
  });
  document.getElementById("btnCancelReject").addEventListener("click", () => {
    document.getElementById("modalReject").classList.add("hidden");
  });

  document.getElementById("btnConfirmReject").addEventListener("click", handleConfirmReject);

  document.getElementById("btnViewReport").addEventListener("click", () => {
    if (!currentProjectId) {
      showToast("请先选择或创建一个项目", "error");
      return;
    }
    openReportDrawer();
  });

  document.getElementById("btnCloseReportDrawer").addEventListener("click", () => {
    document.getElementById("drawerReport").classList.add("hidden");
  });

  // Drawer Tabs
  document.getElementById("tabBtnReport").addEventListener("click", () => {
    document.getElementById("tabBtnReport").classList.add("active");
    document.getElementById("tabBtnManifest").classList.remove("active");
    document.getElementById("tabContentReport").classList.remove("hidden");
    document.getElementById("tabContentManifest").classList.add("hidden");
  });
  document.getElementById("tabBtnManifest").addEventListener("click", () => {
    document.getElementById("tabBtnManifest").classList.add("active");
    document.getElementById("tabBtnReport").classList.remove("active");
    document.getElementById("tabContentManifest").classList.remove("hidden");
    document.getElementById("tabContentReport").classList.add("hidden");
  });

  // Top Download Package Button
  document.getElementById("btnDownloadPackageTop")?.addEventListener("click", handleDownloadPackage);

  // Top Brief Detail Modal
  document.getElementById("btnViewBriefDetail")?.addEventListener("click", handleOpenBriefDetail);
  document.getElementById("btnCloseBriefModal")?.addEventListener("click", () => {
    document.getElementById("modalBriefDetail").classList.add("hidden");
  });
  document.getElementById("btnCloseBriefBtn")?.addEventListener("click", () => {
    document.getElementById("modalBriefDetail").classList.add("hidden");
  });

  // Lyrics Toolbar
  document.getElementById("btnLyricsViewCards")?.addEventListener("click", () => {
    document.getElementById("btnLyricsViewCards").classList.add("active");
    document.getElementById("btnLyricsViewFull").classList.remove("active");
    document.getElementById("lyricsContainer").classList.remove("hidden");
    document.getElementById("lyricsFullContainer").classList.add("hidden");
  });
  document.getElementById("btnLyricsViewFull")?.addEventListener("click", () => {
    document.getElementById("btnLyricsViewFull").classList.add("active");
    document.getElementById("btnLyricsViewCards").classList.remove("active");
    document.getElementById("lyricsContainer").classList.add("hidden");
    document.getElementById("lyricsFullContainer").classList.remove("hidden");
  });

  document.getElementById("btnCopyLyrics")?.addEventListener("click", handleCopyLyrics);
  document.getElementById("btnDownloadLyricsTxt")?.addEventListener("click", () => handleDownloadLyrics("txt"));
  document.getElementById("btnDownloadLyricsLrc")?.addEventListener("click", () => handleDownloadLyrics("lrc"));

  // Cover Art Generation & Upload
  document.getElementById("btnAutoFixCover")?.addEventListener("click", handleGenerateCover);
  document.getElementById("btnGenerateCoverRight")?.addEventListener("click", handleGenerateCover);
  document.getElementById("btnUploadCover")?.addEventListener("click", () => {
    document.getElementById("inputCoverFile")?.click();
  });
  document.getElementById("btnUploadCoverRight")?.addEventListener("click", () => {
    document.getElementById("inputCoverFile")?.click();
  });
  document.getElementById("inputCoverFile")?.addEventListener("change", handleUploadCoverFile);

  // Full Audio Synthesize & WAV Download
  document.getElementById("btnSynthesizeFullTrack")?.addEventListener("click", handleSynthesizeFullTrack);
  document.getElementById("btnDownloadAudioWav")?.addEventListener("click", handleDownloadAudio);

  // Drawer Downloads
  document.getElementById("btnDownloadReportMd")?.addEventListener("click", handleDownloadReportMd);
  document.getElementById("btnDownloadManifestJson")?.addEventListener("click", handleDownloadManifestJson);

  document.getElementById("btnGenNewProjectId")?.addEventListener("click", () => {
    const txt = document.getElementById("txtBriefJson");
    if (!txt || !txt.value.trim()) {
      showToast("请先选择一个样例或输入 Brief JSON", "info");
      return;
    }
    try {
      const data = JSON.parse(txt.value);
      const randSuffix = Math.random().toString(36).substring(2, 8);
      data.project_id = `song_${randSuffix}`;
      txt.value = JSON.stringify(data, null, 2);
      setCreateStatus(`已分配新项目 ID：${data.project_id}`);
      showToast(`已赋予全新工程 ID: ${data.project_id}`, "success");
    } catch (e) {
      showToast("当前 JSON 格式有误，无法解析修改 project_id", "error");
    }
  });
}

// --- Audio Player & Canvas Waveform Visualizer ---
function initAudioPlayer() {
  const audio = document.getElementById("nativeAudio");
  const btnPlayPause = document.getElementById("btnPlayPause");
  const playIcon = document.getElementById("playIcon");
  const pauseIcon = document.getElementById("pauseIcon");
  const seekSlider = document.getElementById("seekSlider");
  const volumeSlider = document.getElementById("volumeSlider");
  const currentTimeEl = document.getElementById("currentTime");
  const totalDurationEl = document.getElementById("totalDuration");

  btnPlayPause.addEventListener("click", () => {
    if (audio.paused) {
      // Initialize Web Audio Context on first user click
      if (!audioContext) {
        setupWebAudio(audio);
      }
      audio.play().catch(err => showToast("播放失败: " + err.message, "error"));
    } else {
      audio.pause();
    }
  });

  audio.addEventListener("play", () => {
    isAudioPlaying = true;
    playIcon.classList.add("hidden");
    pauseIcon.classList.remove("hidden");
    startWaveformAnimation();
  });

  audio.addEventListener("pause", () => {
    isAudioPlaying = false;
    playIcon.classList.remove("hidden");
    pauseIcon.classList.add("hidden");
    drawIdleWaveform();
  });

  audio.addEventListener("timeupdate", () => {
    if (!isNaN(audio.duration)) {
      seekSlider.value = (audio.currentTime / audio.duration) * 100;
      currentTimeEl.textContent = formatTime(audio.currentTime);
      totalDurationEl.textContent = formatTime(audio.duration);
    }
  });

  seekSlider.addEventListener("input", (e) => {
    if (!isNaN(audio.duration)) {
      audio.currentTime = (e.target.value / 100) * audio.duration;
    }
  });

  volumeSlider.addEventListener("input", (e) => {
    audio.volume = e.target.value;
  });

  drawIdleWaveform();
}

function setupWebAudio(audioElement) {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass();
    audioSource = audioContext.createMediaElementSource(audioElement);
    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = 256;
    audioSource.connect(analyserNode);
    analyserNode.connect(audioContext.destination);
  } catch (e) {
    console.warn("Web Audio API not fully available, falling back to simulated wave", e);
  }
}

function startWaveformAnimation() {
  const canvas = document.getElementById("waveformCanvas");
  const ctx = canvas.getContext("2d");
  const bufferLength = analyserNode ? analyserNode.frequencyBinCount : 64;
  const dataArray = new Uint8Array(bufferLength);

  function renderFrame() {
    if (!isAudioPlaying) return;
    animFrameId = requestAnimationFrame(renderFrame);

    if (analyserNode) {
      analyserNode.getByteFrequencyData(dataArray);
    } else {
      for (let i = 0; i < bufferLength; i++) {
        dataArray[i] = Math.floor(Math.random() * 120 + 30);
      }
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const barWidth = (canvas.width / bufferLength) * 1.5;
    let x = 0;

    for (let i = 0; i < bufferLength; i++) {
      const barHeight = (dataArray[i] / 255) * canvas.height * 0.85;

      const gradient = ctx.createLinearGradient(0, canvas.height, 0, canvas.height - barHeight);
      gradient.addColorStop(0, "#00f0ff");
      gradient.addColorStop(0.6, "#10b981");
      gradient.addColorStop(1, "#8b5cf6");

      ctx.fillStyle = gradient;
      ctx.fillRect(x, canvas.height - barHeight, barWidth - 1, barHeight);

      x += barWidth + 1;
      if (x > canvas.width) break;
    }
  }

  renderFrame();
}

function drawIdleWaveform() {
  const canvas = document.getElementById("waveformCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.beginPath();
  ctx.moveTo(0, canvas.height / 2);
  for (let x = 0; x < canvas.width; x += 6) {
    const y = canvas.height / 2 + Math.sin(x * 0.05) * 6;
    ctx.lineTo(x, y);
  }
  ctx.strokeStyle = "rgba(0, 240, 255, 0.25)";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

// --- Data Fetching & Rendering ---

async function loadProjectsList() {
  try {
    const resp = await fetch("/api/projects");
    const projects = await resp.json();
    const select = document.getElementById("projectSelect");
    select.innerHTML = "";

    if (projects.length === 0) {
      select.innerHTML = '<option value="">暂无工程，请新建</option>';
      return;
    }

    const STATE_NAMES = {
      "new": "待任务规划",
      "lyrics_ready": "待审核歌词",
      "lyrics_approved": "歌词已批准·待合成音频",
      "audio_ready": "🎵 待试听审批音频",
      "audio_approved": "音频已批准·待封包",
      "package_ready": "✅ 发行物料包就绪",
      "package_needs_info": "⚠️ 物料包待补充",
    };

    projects.forEach((p, idx) => {
      const opt = document.createElement("option");
      opt.value = p.project_id;
      const stateLabel = STATE_NAMES[p.state] || p.state;
      const sourceLabel = p.audio_source?.mode === "mock" || p.lyrics_source?.mode === "mock" ? " · 离线演示" : p.lyrics_source?.mode === "unknown" ? " · 来源未核实" : "";
      opt.textContent = `${p.project_id} · 《${p.title}》 [${stateLabel}]${sourceLabel}`;
      select.appendChild(opt);
    });

    // Default select first or keep current
    if (!currentProjectId || !projects.some(p => p.project_id === currentProjectId)) {
      currentProjectId = projects[0].project_id;
    }
    select.value = currentProjectId;
    await loadProject(currentProjectId);
  } catch (err) {
    showToast("拉取工程列表失败: " + err.message, "error");
  }
}

async function loadProject(projectId) {
  clearTimeout(projectPollTimer);
  // Safety: Stop any currently playing audio on project switch
  const audio = document.getElementById("nativeAudio");
  if (audio && !audio.paused) {
    audio.pause();
    audio.currentTime = 0;
    isAudioPlaying = false;
    document.getElementById("playIcon")?.classList.remove("hidden");
    document.getElementById("pauseIcon")?.classList.add("hidden");
    drawIdleWaveform();
  }

  currentProjectId = projectId;
  try {
    const resp = await fetch(`/api/projects/${projectId}`);
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const detail = await resp.json();
    if (currentProjectId !== projectId) return;
    projectDetail = detail;
    renderProjectDetail(projectDetail);
    const progressResponse = await fetch(`/api/projects/${encodeURIComponent(projectId)}/progress`);
    if (progressResponse.ok && currentProjectId === projectId) {
      updateProjectProgress(await progressResponse.json());
    }
  } catch (err) {
    showToast(`加载项目 [${projectId}] 失败: ${err.message}`, "error");
  }
}

function renderProjectDetail(data) {
  const ckpt = data.checkpoint || {};
  const brief = data.brief || {};
  const lyrics = data.lyrics || {};
  const comp = data.composition || {};
  const state = ckpt.state || "new";

  // 1. Render FSM Nodes
  renderFSMTracker(state);

  // 2. Render Left Panel (Brief & Lyrics & Full Text)
  renderBriefPills(brief);
  renderAnomalies(ckpt.detected_anomalies || []);
  renderLyrics(lyrics, ckpt.lyrics_version, data.all_lyrics, data.lyrics_history);
  renderFullLyrics(lyrics, brief);
  if (document.getElementById("rightsArtist")) {
    document.getElementById("rightsArtist").value = brief.artist_name || "";
    document.getElementById("rightsStatement").value = brief.copyright_statement || "";
    document.getElementById("rightsConfirmed").checked = !!brief.rights_confirmed;
  }

  // 3. Render Right Panel (Composition & Audio & Cover)
  renderCoverArt(data.cover_url, brief);
  renderComposition(comp, ckpt.audio_version, data.has_audio);
  renderAudioPlayerState(data.audio_url, comp.audio_metadata);
  const regenerate = document.getElementById("btnSynthesizeFullTrack");
  if (regenerate) regenerate.disabled = !!ckpt.pending || !["lyrics_approved","audio_ready","audio_approved","package_ready","package_needs_info"].includes(ckpt.state);

  // 4. Render Bottom HITL Action Bar
  renderHITLActionBar(state, ckpt);
  const sources = document.getElementById("artifactSources");
  const sourceText = (label, source) => `${label}：${source?.message || "来源未核实"}${source?.model ? ` · ${source.model}` : ""}`;
  sources.textContent = [sourceText("当前歌词", data.lyrics_source), sourceText("当前音频", data.audio_source)].join("\n");
  sources.classList.toggle("warning", [data.lyrics_source, data.audio_source].some(s => ["mock", "unknown"].includes(s?.mode)));
}

function renderFSMTracker(currentState) {
  const container = document.getElementById("fsmNodes");
  container.innerHTML = '<div class="fsm-node-connector"></div>';

  const stateRank = {
    "new": 0,
    "lyrics_ready": 1,
    "lyrics_approved": 2,
    "audio_ready": 3,
    "audio_approved": 4,
    "package_ready": 5,
    "package_needs_info": 5,
  };

  const currentRank = stateRank[currentState] ?? 0;

  FSM_STEPS.forEach((step, idx) => {
    const item = document.createElement("div");
    item.className = "fsm-node-item";

    let circleClass = "";
    if (idx < currentRank) {
      item.classList.add("completed");
    } else if (idx === currentRank) {
      item.classList.add("active");
      if (currentState === "package_needs_info") {
        item.classList.add("needs_info");
      }
    }

    item.innerHTML = `
      <div class="fsm-node-circle">${idx < currentRank ? "✓" : idx + 1}</div>
      <div class="fsm-node-title">${step.name}</div>
    `;
    container.appendChild(item);
  });
}

function renderBriefPills(brief) {
  const container = document.getElementById("briefPills");
  container.innerHTML = "";

  const pills = [
    { label: "主题", val: brief.theme || "--" },
    { label: "曲风", val: brief.genre || "--" },
    { label: "情绪", val: brief.mood || "--" },
    { label: "时长", val: brief.duration_text || (brief.duration_seconds ? brief.duration_seconds + "秒" : "--") },
    { label: "受众", val: brief.audience || "通用" },
    { label: "主平台", val: brief.primary_platform || (brief.platform?.[0] || "--") },
  ];

  pills.forEach(p => {
    const pill = document.createElement("div");
    pill.className = "pill-item";
    pill.innerHTML = `<span class="pill-label">${p.label}:</span><span class="pill-val">${escapeHtml(p.val)}</span>`;
    container.appendChild(pill);
  });
}

function renderAnomalies(anomalies) {
  const box = document.getElementById("anomalyBox");
  const list = document.getElementById("anomalyList");
  list.innerHTML = "";

  if (!anomalies || anomalies.length === 0) {
    box.classList.add("hidden");
    return;
  }

  box.classList.remove("hidden");
  anomalies.forEach(a => {
    const li = document.createElement("li");
    li.textContent = `[${a.issue_type}] ${a.field}: ${a.message}`;
    list.appendChild(li);
  });

  const existingBtn = box.querySelector(".autofix-btn");
  if (existingBtn) existingBtn.remove();

  const btnFix = document.createElement("button");
  btnFix.className = "autofix-btn";
  btnFix.innerHTML = `<span>⚡ 一键智能对齐需求单冲突</span>`;
  btnFix.onclick = async () => {
    btnFix.disabled = true;
    showToast("正在执行需求单智能对齐...", "info");
    try {
      const res = await requestApi(`/api/projects/${currentProjectId}/brief/auto-fix`, { method: "POST" });
      showToast(res.message || "需求单已自动对齐修复！", "success");
      await loadProject(currentProjectId);
    } catch (e) {
      showToast("修复失败: " + e.message, "error");
    } finally {
      btnFix.disabled = false;
    }
  };
  box.appendChild(btnFix);
}

function renderLyrics(lyrics, version, allLyrics = {}, lyricsHistory = []) {
  window.switchLyricsVersion = function(ver) {
    const targetLyrics = (projectDetail?.all_lyrics && projectDetail.all_lyrics[ver]) ? projectDetail.all_lyrics[ver] : lyrics;
    doRenderLyrics(targetLyrics, ver, allLyrics, lyricsHistory);
  };
  window.toggleLyricsDiff = function() {
    isLyricsDiffView = !isLyricsDiffView;
    const curVer = document.getElementById("lyricsVersionBadge").textContent || version;
    const targetLyrics = (projectDetail?.all_lyrics && projectDetail.all_lyrics[curVer]) ? projectDetail.all_lyrics[curVer] : lyrics;
    doRenderLyrics(targetLyrics, curVer, allLyrics, lyricsHistory);
  };
  doRenderLyrics(lyrics, version, allLyrics, lyricsHistory);
}

function doRenderLyrics(lyrics, version, allLyrics = {}, lyricsHistory = []) {
  const container = document.getElementById("lyricsContainer");
  document.getElementById("lyricsVersionBadge").textContent = version || "v1";

  if (!lyrics || !lyrics.sections || lyrics.sections.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>暂无歌词数据，等待作词子 Agent 执行生成。</p>
      </div>`;
    return;
  }

  let html = "";
  if (lyricsHistory && lyricsHistory.length > 1) {
    html += `
      <div class="lyrics-version-tabs">
        <span class="version-tabs-label">版本演进:</span>
        ${lyricsHistory.map(h => `
          <button type="button" class="btn-version-pill ${h.version === version ? 'active' : ''}" onclick="window.switchLyricsVersion('${h.version}')">
            ${h.version} ${h.version === projectDetail?.checkpoint?.lyrics_version ? '(当前审核)' : ''}
          </button>
        `).join("")}
        <button type="button" class="btn-diff-toggle ${isLyricsDiffView ? 'active' : ''}" onclick="window.toggleLyricsDiff()">
          ${isLyricsDiffView ? '✓ 退出对比' : '⚡ 对比上一版本 (Diff)'}
        </button>
      </div>
    `;
  }

  html += `
    <div class="lyrics-title-header">《${escapeHtml(lyrics.title)}》</div>
    <div class="lyrics-structure-sub">结构编排: ${escapeHtml(lyrics.structure_summary || "--")}</div>
  `;

  const curVerNum = parseInt((version || "v1").replace("v", ""), 10);
  const prevLyrics = (isLyricsDiffView && curVerNum > 1 && allLyrics) ? allLyrics[`v${curVerNum - 1}`] : null;

  lyrics.sections.forEach((sec, sIdx) => {
    const prevSec = prevLyrics?.sections?.[sIdx];
    const prevLinesSet = new Set(prevSec?.lines || []);
    const curLinesSet = new Set(sec.lines || []);

    html += `
      <div class="lyrics-section">
        <div class="section-tag-row">
          <span class="section-name">[${escapeHtml(sec.section_name)}]</span>
          <span class="section-emotion">${escapeHtml(sec.emotion_tag || "标准")}</span>
          ${isLyricsDiffView && prevLyrics ? `<span style="font-size:0.75rem; color:var(--text-muted); margin-left:auto;">vs v${curVerNum - 1}</span>` : ""}
        </div>
        <ul class="lyrics-lines">
          ${isLyricsDiffView && prevSec ?
            (prevSec.lines || []).filter(l => !curLinesSet.has(l)).map(l => `<li class="diff-line-del">- ${escapeHtml(l)}</li>`).join("") +
            (sec.lines || []).map(l => {
              const isAdd = !prevLinesSet.has(l);
              return `<li class="${isAdd ? 'diff-line-add' : ''}">${isAdd ? '+ ' : ''}${escapeHtml(l)}</li>`;
            }).join("")
            : (sec.lines || []).map(l => `<li>${escapeHtml(l)}</li>`).join("")
          }
        </ul>
      </div>
    `;
  });

  container.innerHTML = html;
}

function renderComposition(comp, audioVersion, hasAudio) {
  const vocals = comp.vocal_requirements || projectDetail?.requested_vocals || projectDetail?.brief?.vocals;
  const voiceNames = { female: "女声主唱", male: "男声主唱", mixed: "男女对唱", unspecified: "未指定主唱类型" };
  const voiceEl = document.getElementById("vocalRequirements");
  const voiceLabel = vocals ? voiceNames[vocals.lead] || "待确认" : "历史版本未独立记录，请对照需求试听";
  voiceEl.textContent = `人声目标：${voiceLabel}${vocals?.style ? ` · ${vocals.style}` : ""}\n文件格式检查已与内容审核分开；主唱类型、音色和歌词演唱准确性需人工试听确认。`;
  document.getElementById("audioVersionBadge").textContent = audioVersion || "v1";
  const statusBadge = document.getElementById("audioStatusBadge");

  if (hasAudio) {
    statusBadge.textContent = "已就绪";
    statusBadge.className = "badge badge-emerald";
  } else {
    statusBadge.textContent = "未生成";
    statusBadge.className = "badge badge-amber";
  }

  document.getElementById("valBPM").textContent = comp.bpm ? `${comp.bpm} BPM` : "--";
  document.getElementById("valKey").textContent = comp.key || "--";
  document.getElementById("valModel").textContent = projectDetail?.audio_source?.mode === "mock" ? "离线演示合成" : (projectDetail?.audio_source?.mode === "unknown" ? "历史来源未核实" : (comp.music_model_params?.provider || "待歌词审核后生成"));

  const notesEl = document.getElementById("arrangementContent");
  notesEl.textContent = comp.arrangement_notes || "暂无编曲方案，需等歌词审核批准后调用作曲子 Agent 生成。";

  // Audio Duration Meta
  const durSec = comp.audio_metadata?.duration_seconds;
  const trackDurEl = document.getElementById("trackDurationType");
  if (trackDurEl) {
    trackDurEl.textContent = durSec ? `已生成音轨 (${durSec.toFixed(1)}s)` : "尚未生成";
  }
  const targetDurEl = document.getElementById("targetFullDuration");
  if (targetDurEl) {
    const brief = projectDetail?.brief || {};
    targetDurEl.textContent = brief.duration_text || (brief.duration_seconds ? brief.duration_seconds + "s" : "--");
  }
}

function renderAudioPlayerState(audioUrl, audioMeta) {
  const audio = document.getElementById("nativeAudio");
  const btnPlayPause = document.getElementById("btnPlayPause");
  const seekSlider = document.getElementById("seekSlider");
  const overlay = document.getElementById("canvasOverlay");
  const shaEl = document.getElementById("audioSha256");
  const btnDownloadWav = document.getElementById("btnDownloadAudioWav");

  if (audioUrl) {
    if (audio.getAttribute("src") !== audioUrl) audio.src = audioUrl;
    btnPlayPause.disabled = false;
    seekSlider.disabled = false;
    if (btnDownloadWav) btnDownloadWav.disabled = false;
    overlay.classList.add("hidden");
    if (audioMeta?.sha256) {
      shaEl.textContent = audioMeta.sha256;
      shaEl.title = audioMeta.sha256;
    }
  } else {
    audio.removeAttribute("src");
    btnPlayPause.disabled = true;
    seekSlider.disabled = true;
    if (btnDownloadWav) btnDownloadWav.disabled = true;
    overlay.classList.remove("hidden");
    document.getElementById("canvasOverlayText").textContent = "音频尚未生成，待歌词审核后推进";
    shaEl.textContent = "--";
  }
}

function renderHITLActionBar(state, ckpt) {
  const actionDot = document.getElementById("actionDot");
  const mainText = document.getElementById("instructionMain");
  const subText = document.getElementById("instructionSub");
  const buttonsGroup = document.getElementById("actionButtons");
  buttonsGroup.innerHTML = "";

  if (ckpt.pending || ckpt.last_error) {
    actionDot.style.background = "#f59e0b";
    mainText.textContent = ckpt.last_error || "创作任务进行中";
    subText.textContent = ckpt.pending ? `待完成阶段：${ckpt.pending.stage} · 版本 ${ckpt.pending.version}` : "请检查物料或服务配置";
    if (ckpt.pending) buttonsGroup.appendChild(createActionButton("恢复 / 重试原任务", "btn-primary", handleResume));
    return;
  }
  if (state === "new") {
    actionDot.style.background = "#00f0ff";
    mainText.textContent = "需求单已录入，正在生成任务规划与歌词初稿";
    subText.textContent = "系统正在驱动作词子 Agent，请稍候...";
  } else if (state === "lyrics_ready") {
    actionDot.style.background = "#f59e0b";
    mainText.textContent = "【人机审核关卡 1】请制作人审查分段歌词，准予通过或打回修改";
    subText.textContent = "遵循代码级硬门禁 R2：歌词批准前绝对禁止调用作曲子 Agent";

    const btnApprove = createActionButton("批准歌词通过", "btn-success", () => handleApprove("lyrics", true));
    const btnReject = createActionButton("打回修改", "btn-danger", () => openRejectModal("lyrics"));
    buttonsGroup.appendChild(btnReject);
    buttonsGroup.appendChild(btnApprove);
  } else if (state === "lyrics_approved") {
    actionDot.style.background = "#10b981";
    mainText.textContent = "歌词审核已批准通过！准备推进作曲与音频生成";
    subText.textContent = "将调用作曲/音频子 Agent 生成 44.1kHz 16-bit PCM 二进制 RIFF/WAVE 文件";

    const btnResume = createActionButton("推进生成作曲与音频", "btn-primary", handleResume);
    buttonsGroup.appendChild(btnResume);
  } else if (state === "audio_ready") {
    actionDot.style.background = "#f59e0b";
    mainText.textContent = "【人机审核关卡 2】音频已合成，请在上方视听波形并执行审核确认";
    subText.textContent = "请先核对主唱类型、空灵等音色要求、歌词演唱和整体听感；文件质检通过不代表内容符合需求。确认满意后再批准。";

    const btnApprove = createActionButton("试听满意 · 批准音频", "btn-success", () => handleApprove("audio", true));
    const btnReject = createActionButton("打回重调音频", "btn-danger", () => openRejectModal("audio"));
    buttonsGroup.appendChild(btnReject);
    buttonsGroup.appendChild(btnApprove);
  } else if (state === "audio_approved") {
    actionDot.style.background = "#10b981";
    mainText.textContent = "音频审核已批准通过！所有创作资产已就绪";
    subText.textContent = "可构建标准发行物料包 release-package/，计算全量 SHA-256 防篡改数字指纹";

    const btnReject = createActionButton("打回重做音频", "btn-danger", () => openRejectModal("audio"));
    const btnExport = createActionButton("一键构建标准发行物料包", "btn-primary", handleExport);
    buttonsGroup.appendChild(btnReject);
    buttonsGroup.appendChild(btnExport);
  } else if (state === "package_ready") {
    actionDot.style.background = "#10b981";
    mainText.textContent = "🎉 发行物料包封包完成，状态判定: [package_ready]";
    subText.textContent = "物料与审核记录校验完成，可下载本地发行包；生成来源见上方标识";

    const btnReject = createActionButton("打回重做音频 (自增版本)", "btn-danger", () => openRejectModal("audio"));
    const btnDownloadZip = createActionButton("📥 下载发行物料包 (.ZIP)", "btn-primary", handleDownloadPackage);
    const btnView = createActionButton("查验 Manifest 审计清单", "btn-secondary", openReportDrawer);
    const btnExportAgain = createActionButton("重新构建导出", "btn-ghost", handleExport);
    buttonsGroup.appendChild(btnReject);
    buttonsGroup.appendChild(btnDownloadZip);
    buttonsGroup.appendChild(btnExportAgain);
    buttonsGroup.appendChild(btnView);
  } else if (state === "package_needs_info") {
    actionDot.style.background = "#f59e0b";
    mainText.textContent = "⚠️ 发行物料包已生成，但降级标记为: [package_needs_info]";
    subText.textContent = "遵循 R5 完备性门禁：检测到缺失封面、音频或版权项，阻断标记 ready";

    const btnReject = createActionButton("打回重做音频 (自增版本)", "btn-danger", () => openRejectModal("audio"));
    const btnDownloadZip = createActionButton("📥 下载现有物料 (.ZIP)", "btn-primary", handleDownloadPackage);
    const btnView = createActionButton("查看物料缺失清单", "btn-secondary", openReportDrawer);
    const btnExportAgain = createActionButton("重新校验封包", "btn-ghost", handleExport);
    buttonsGroup.appendChild(btnReject);
    buttonsGroup.appendChild(btnDownloadZip);
    buttonsGroup.appendChild(btnExportAgain);
    buttonsGroup.appendChild(btnView);
  }
}

function createActionButton(text, className, onClick) {
  const btn = document.createElement("button");
  btn.className = `btn ${className}`;
  btn.textContent = text;
  btn.addEventListener("click", async (e) => {
    if (btn.disabled) return;
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.classList.add("loading");
    try {
      await onClick(e);
    } finally {
      btn.disabled = false;
      btn.classList.remove("loading");
      btn.textContent = oldText;
    }
  });
  return btn;
}

// --- Action Handlers ---

async function handleApprove(stage, approved, feedback = "") {
  if (!currentProjectId) return;
  showToast(`正在提交 [${stage}] 阶段审批...`, "info");

  try {
    const resp = await fetch(`/api/projects/${currentProjectId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage: stage,
        approved: approved,
        feedback: feedback,
        reviewer: "Web Studio Reviewer",
      }),
    });

    const result = await resp.json();
    if (!resp.ok) {
      throw new Error(result.detail || "审批失败");
    }

    showToast(result.message || "审批成功！", "success");
    await loadProjectsList();
    loadProject(currentProjectId);
  } catch (err) {
    showToast("审批操作失败: " + err.message, "error");
  }
}

async function handleResume() {
  if (!currentProjectId) return;
  showToast("正在恢复或推进当前任务…", "info");

  try {
    if (cachedRuntimeStatus && !cachedRuntimeStatus.production_ready) {
      const result = await requestApi(`/api/projects/${currentProjectId}/resume`, { method: "POST" });
      showToast(result.message || "推进完成！", "success");
      await loadProjectsList();
      await loadProject(currentProjectId);
      return;
    }
    const result = await requestApi(`/api/projects/${currentProjectId}/execute`, { method: "POST" });
    updateProjectProgress(result);
  } catch (err) {
    showToast("执行失败: " + err.message, "error");
  }
}

async function handleExport() {
  if (!currentProjectId) return;
  showToast("正在执行全量文件哈希校验并封包...", "info");

  try {
    const resp = await fetch(`/api/projects/${currentProjectId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    const result = await resp.json();
    if (!resp.ok) {
      throw new Error(result.detail || "导出失败");
    }

    showToast(`物料包封包完成！状态: [${result.package_status}]`, result.package_status === "ready" ? "success" : "info");
    await loadProjectsList();
    loadProject(currentProjectId);
  } catch (err) {
    showToast("导出失败: " + err.message, "error");
  }
}

// --- Modals Logic ---

function openRejectModal(stage) {
  currentRejectStage = stage;
  const modal = document.getElementById("modalReject");
  document.getElementById("rejectModalTitle").textContent = `打回 ${stage === "lyrics" ? "歌词" : "音频"} 修改`;
  document.getElementById("txtRejectFeedback").value = "";
  modal.classList.remove("hidden");
}

function handleConfirmReject() {
  const feedback = document.getElementById("txtRejectFeedback").value.trim();
  if (!feedback) {
    showToast("打回修改必须填写批注意见，以便子 Agent 针对性重制！", "error");
    return;
  }

  document.getElementById("modalReject").classList.add("hidden");
  handleApprove(currentRejectStage, false, feedback);
}

async function handleCreateProject() {
  const submitBtn = document.getElementById("btnSubmitNewBrief");
  if (submitBtn.disabled) return;
  const jsonText = document.getElementById("txtBriefJson").value.trim();
  if (!jsonText) {
    setCreateStatus("请输入或选择 Brief 需求单内容", true);
    return;
  }

  let briefData;
  try {
    briefData = JSON.parse(jsonText);
  } catch (e) {
    setCreateStatus("JSON 语法解析错误，请检查格式", true);
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.classList.add("loading");
    submitBtn.textContent = "正在提交任务…";
  }

  setCreateStatus("正在校验需求并保存任务…");
  try {
    if (cachedRuntimeStatus && !cachedRuntimeStatus.production_ready) {
      const result = await requestApi("/api/projects/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief: briefData }),
      });
      document.getElementById("modalNewBrief").classList.add("hidden");
      currentProjectId = result.project_id;
      showToast(`[离线仿真模式] 项目 [${result.project_id}] 初始化成功，已生成任务规划与初稿歌词`, "info");
      await loadProjectsList();
      await loadProject(currentProjectId);
      return;
    }

    const result = await requestApi("/api/projects/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief: briefData }),
    });

    document.getElementById("modalNewBrief").classList.add("hidden");
    currentProjectId = result.project_id;
    showToast(`项目 [${result.project_id}] 已接收，正在真实调用规划和作词服务`, "info");
    await loadProjectsList();
    updateProjectProgress(result);
  } catch (err) {
    setCreateStatus("新建项目失败：" + err.message, true);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.classList.remove("loading");
      submitBtn.textContent = "启动 Agent 创制流水线";
    }
  }
}

async function loadPresetBriefs() {
  try {
    const resp = await fetch("/api/fixtures/briefs");
    presetBriefs = await resp.json();
  } catch (e) {
    console.warn("Failed to load preset briefs", e);
  }
}

window.loadPresetBrief = function(projectId) {
  const item = presetBriefs.find(b => b.project_id === projectId);
  if (item) {
    const brief = { ...item.brief,
      project_id: `${projectId}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
      artist_name: "", copyright_statement: "", rights_confirmed: false, cover_placeholder_path: null };
    document.getElementById("txtBriefJson").value = JSON.stringify(brief, null, 2);
    setCreateStatus(`已分配新项目 ID：${brief.project_id}。启动后将推进创作流水线。`);
  } else {
    setCreateStatus("需求模板尚未加载，请稍后重新选择或直接输入 JSON", true);
  }
};

function setCreateStatus(message, error = false) {
  const el = document.getElementById("createProjectStatus");
  el.textContent = message;
  el.classList.remove("hidden");
  el.classList.toggle("error", error);
}

async function requestApi(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("无法连接工作台服务，请检查服务是否已启动；已提交的任务可通过工程列表恢复");
  }
  let data;
  try { data = await response.json(); }
  catch (error) { throw new Error(`服务响应异常（HTTP ${response.status}），请检查服务日志`); }
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail) ? detail.map(item => `${(item.loc || []).filter(p => p !== "body").join(".")}：${item.msg}`).join("\n") : typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return data;
}

async function loadRuntimeStatus() {
  const el = document.getElementById("runtimeStatus");
  try {
    const status = await requestApi("/api/runtime");
    cachedRuntimeStatus = status;
    const modeLabel = status.production_ready ? "真实生产模式" : "离线仿真模式（开箱即用）";
    el.textContent = `运行模式：${modeLabel} · 文本 ${status.text.model || status.text.provider}（${status.text.mode === "real" ? "真实" : status.text.mode === "mock" ? "演示" : "未配置"}） · 音乐 ${status.music.model || status.music.provider}（${status.music.mode === "real" ? "真实" : status.music.mode === "mock" ? "演示" : "未配置"}）\n${status.message}`;
    el.classList.toggle("ready", status.production_ready);
    el.classList.toggle("warning", !status.production_ready);
  } catch (error) {
    el.textContent = `服务检查失败：${error.message}`;
    el.classList.add("warning");
  }
}

function updateProjectProgress(progress) {
  if (progress.project_id !== currentProjectId) return;
  clearTimeout(projectPollTimer);
  const wasRunning = projectIsRunning;
  projectIsRunning = ["queued", "running"].includes(progress.execution_status);
  if (projectIsRunning) {
    document.getElementById("btnSynthesizeFullTrack").disabled = true;
    document.getElementById("instructionMain").textContent = progress.message;
    document.getElementById("instructionSub").textContent = "任务已保存，页面每 2 秒更新进度；生成完成后等待人工审核";
    document.getElementById("actionButtons").innerHTML = "";
  }
  if (projectIsRunning) {
    projectPollTimer = setTimeout(() => pollProjectProgress(progress.project_id), 2000);
  } else if (wasRunning) {
    showToast(progress.last_error || "本阶段执行完成，请查看产物并进行审核", progress.last_error ? "error" : "success");
    loadProjectsList();
  }
}

async function pollProjectProgress(projectId) {
  if (currentProjectId !== projectId) return;
  try {
    const progress = await requestApi(`/api/projects/${encodeURIComponent(projectId)}/progress`);
    updateProjectProgress(progress);
  } catch (error) {
    document.getElementById("instructionSub").textContent = error.message + "，正在重新连接…";
    projectPollTimer = setTimeout(() => pollProjectProgress(projectId), 5000);
  }
}

async function openReportDrawer() {
  if (!currentProjectId) return;
  const drawer = document.getElementById("drawerReport");
  drawer.classList.remove("hidden");

  try {
    const resp = await fetch(`/api/projects/${currentProjectId}/report`);
    const data = await resp.json();
    document.getElementById("preReportMarkdown").textContent = data.markdown || "暂无运行报告记录";

    if (projectDetail && projectDetail.manifest) {
      document.getElementById("preManifestJson").textContent = JSON.stringify(projectDetail.manifest, null, 2);
    } else {
      document.getElementById("preManifestJson").textContent = "物料包尚未构建，暂无 manifest.json";
    }
  } catch (err) {
    showToast("获取报告失败: " + err.message, "error");
  }
}

// --- Toast System ---
function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// --- Cover Art Rendering & Handlers ---
function renderCoverArt(coverUrl, brief) {
  const imgEl = document.getElementById("coverPreviewImg");
  const placeholderEl = document.getElementById("coverEmptyPlaceholder");
  const albumTitleEl = document.getElementById("coverAlbumTitle");
  const statusTextEl = document.getElementById("coverStatusText");

  albumTitleEl.textContent = brief.theme ? `《${brief.theme}》专辑视觉` : "单曲视觉物料";

  if (coverUrl) {
    imgEl.src = coverUrl;
    imgEl.classList.remove("hidden");
    placeholderEl.classList.add("hidden");
    statusTextEl.textContent = "✅ 已齐备合法封面图，SHA-256 数字指纹将写入物料包";
    statusTextEl.style.color = "var(--accent-emerald)";
  } else {
    imgEl.removeAttribute("src");
    imgEl.classList.add("hidden");
    placeholderEl.classList.remove("hidden");
    statusTextEl.textContent = "遵循 R5 完备性规范：缺失封面将判定为 package_needs_info";
    statusTextEl.style.color = "var(--accent-amber)";
  }
}

async function handleGenerateCover() {
  if (!currentProjectId) {
    showToast("请先选择一个工程", "error");
    return;
  }
  showToast("正在运用 PIL 生成赛博朋克风格专属专辑封面...", "info");
  try {
    const resp = await fetch(`/api/projects/${currentProjectId}/cover/generate`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "生成封面失败");
    showToast(data.message || "封面生成成功！", "success");
    await loadProject(currentProjectId);
    await loadProjectsList();
  } catch (err) {
    showToast("生成封面异常: " + err.message, "error");
  }
}

async function handleUploadCoverFile(e) {
  const file = e.target.files?.[0];
  if (!file || !currentProjectId) return;
  const formData = new FormData();
  formData.append("file", file);

  showToast("正在上传封面文件...", "info");
  try {
    const resp = await fetch(`/api/projects/${currentProjectId}/cover/upload`, {
      method: "POST",
      body: formData,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "上传失败");
    showToast("封面替换成功！", "success");
    e.target.value = "";
    await loadProject(currentProjectId);
  } catch (err) {
    showToast("上传封面失败: " + err.message, "error");
  }
}

// --- Full Lyrics Rendering & Handlers ---
function renderFullLyrics(lyrics, brief) {
  const container = document.getElementById("lyricsFullContainer");
  if (!lyrics || !lyrics.sections || lyrics.sections.length === 0) {
    container.innerHTML = '<p class="text-muted">暂无歌词全文数据</p>';
    return;
  }

  let html = `
    <div class="full-lyrics-header">
      <div class="full-lyrics-title">《${escapeHtml(lyrics.title)}》</div>
      <div class="full-lyrics-meta">
        主题: ${escapeHtml(lyrics.theme || brief.theme || "--")} · 
        曲风: ${escapeHtml(brief.genre || "--")} · 
        情绪: ${escapeHtml(brief.mood || "--")} · 
        语言: ${escapeHtml(brief.lyrics_language || "中文")} · 
        版本: ${escapeHtml(projectDetail?.checkpoint?.lyrics_version || "v1")}
      </div>
    </div>
  `;

  lyrics.sections.forEach(sec => {
    html += `
      <div class="section-tag">[${escapeHtml(sec.section_name)} - ${escapeHtml(sec.emotion_tag || "标准")}]</div>
      ${(sec.lines || []).map(l => `<div class="verse-line">${escapeHtml(l)}</div>`).join("")}
    `;
  });

  container.innerHTML = html;
}

function handleCopyLyrics() {
  const lyrics = projectDetail?.lyrics;
  if (!lyrics || !lyrics.sections) {
    showToast("暂无可复制的歌词", "info");
    return;
  }

  let text = `《${lyrics.title}》\n主题: ${lyrics.theme || ""}\n\n`;
  lyrics.sections.forEach(sec => {
    text += `[${sec.section_name} - ${sec.emotion_tag || ""}]\n`;
    (sec.lines || []).forEach(l => {
      text += `  ${l}\n`;
    });
    text += "\n";
  });

  navigator.clipboard.writeText(text).then(() => {
    showToast("已成功复制完整歌词全文到剪贴板！", "success");
  }).catch(() => {
    showToast("复制失败，请手动选取文本", "error");
  });
}

function handleDownloadLyrics(format) {
  if (!currentProjectId) return;
  window.location.href = `/api/projects/${currentProjectId}/download/lyrics?format=${format}`;
  showToast(`已开始下载 ${format.toUpperCase()} 歌词文件`, "info");
}

// --- Audio & Package Download Handlers ---
function handleDownloadAudio() {
  if (!currentProjectId) return;
  window.location.href = `/api/projects/${currentProjectId}/download/audio`;
  showToast("正在下载WAV 音频...", "info");
}

function handleDownloadPackage() {
  if (!currentProjectId) {
    showToast("请先选择一个工程", "error");
    return;
  }
  window.location.href = `/api/projects/${currentProjectId}/download/package`;
  showToast(`正在导出并下载 [${currentProjectId}] 标准发行物料包 (.ZIP)...`, "info");
}

async function handleSynthesizeFullTrack() {
  if (!currentProjectId) return;
  const brief = projectDetail?.brief || {};
  const duration = brief.duration_seconds || 60;

  showToast(`正在按需求规格合成 ${duration} 秒完整音频...`, "info");
  try {
    const resp = await fetch(`/api/projects/${currentProjectId}/audio/generate_full?duration=${duration}`, {
      method: "POST",
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "合成全曲失败");
    showToast(data.message || "全曲合成完成！", "success");
    await loadProject(currentProjectId);
  } catch (err) {
    showToast("合成全曲失败: " + err.message, "error");
  }
}

// --- Brief Snapshot Modal Handler ---
function handleOpenBriefDetail() {
  if (!projectDetail) {
    showToast("请先选择一个项目", "error");
    return;
  }
  const brief = projectDetail.brief || {};
  const container = document.getElementById("briefDetailContent");

  const fields = [
    { label: "工程编号 (Project ID)", val: brief.project_id || currentProjectId },
    { label: "歌曲主题 (Theme)", val: brief.theme || "--" },
    { label: "音乐曲风 (Genre)", val: brief.genre || "--" },
    { label: "情绪基调 (Mood)", val: brief.mood || "--" },
    { label: "时长规划 (Duration)", val: `${brief.duration_seconds || '--'} 秒 (${brief.duration_text || '--'})` },
    { label: "目标受众 (Audience)", val: brief.audience || "通用大众" },
    { label: "发布主平台 (Primary Platform)", val: brief.primary_platform || "--" },
    { label: "全部发行渠道 (Platforms)", val: (brief.platform || []).join(", ") || "--" },
    { label: "歌词语种 (Language)", val: brief.lyrics_language || "中文" },
    { label: "允许版权采样 (Allow Sampling)", val: brief.allow_sampling ? "是" : "否 (禁止未授权采样)" },
    { label: "参考对标作品 (References)", val: (brief.references || []).join(" | ") || "无", full: true },
    { label: "创作约束条件 (Constraints)", val: (brief.constraints || []).join("； ") || "无", full: true },
    { label: "封面占位图路径 (Cover Path)", val: brief.cover_placeholder_path || "未指定 (可一键自动生成或上传)", full: true },
  ];

  container.innerHTML = fields.map(f => `
    <div class="brief-detail-item ${f.full ? 'full-width' : ''}">
      <div class="brief-detail-label">${f.label}</div>
      <div class="brief-detail-val">${escapeHtml(f.val)}</div>
    </div>
  `).join("");

  document.getElementById("modalBriefDetail").classList.remove("hidden");
}

// --- Drawer Downloads ---
function handleDownloadReportMd() {
  const content = document.getElementById("preReportMarkdown").textContent;
  if (!content) return;
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${currentProjectId}_run_report.md`;
  a.click();
  showToast("已下载运行报告 Markdown 文件", "info");
}

function handleDownloadManifestJson() {
  const content = document.getElementById("preManifestJson").textContent;
  if (!content) return;
  const blob = new Blob([content], { type: "application/json;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${currentProjectId}_manifest.json`;
  a.click();
  showToast("已下载 Manifest JSON 文件", "info");
}


async function handleSaveRights(event) {
  event.preventDefault();
  if (!currentProjectId) return;
  try {
    const response = await fetch(`/api/projects/${currentProjectId}/rights`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({artist_name: document.getElementById("rightsArtist").value,
        copyright_statement: document.getElementById("rightsStatement").value,
        rights_confirmed: document.getElementById("rightsConfirmed").checked})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "保存失败");
    showToast(result.message,"success");
    await loadProject(currentProjectId);
  } catch (error) { showToast(error.message,"error"); }
}
