/**
 * 리치마작 웹 GUI 클라이언트 스크립트
 */

const KANJI_NUMS = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
const HONOR_NAMES = ["", "東", "南", "西", "北", "白", "發", "中"];
const WIND_NAMES = ["", "동", "남", "서", "북"];

let gameState = null;
let declareRiichiNext = false;
let riichiEntryAnimationPending = false;
let isWaitingAi = false;
let isSendingAction = false;
let connectionError = "";
let isPaused = false;
let previousHumanMeldSignatures = null;
let previousAiMeldSignatures = null;
const pendingHumanMeldEffects = new Map();
const pendingAiMeldEffects = new Map();
const RECORD_STORAGE_KEY = "riichi-mahjong.match-history.v1";
const MAX_SAVED_RECORDS = 30;
const MOTION_PREFERENCE_KEY = "riichi-mahjong.reduce-action-motion.v1";

function readReduceActionMotion() {
  try { return localStorage.getItem(MOTION_PREFERENCE_KEY) === "true"; }
  catch (err) { return false; }
}

function applyReduceActionMotion(enabled) {
  document.documentElement.dataset.reduceActionMotion = enabled ? "true" : "false";
  try { localStorage.setItem(MOTION_PREFERENCE_KEY, String(enabled)); }
  catch (err) { /* 저장 불가여도 설정은 현재 화면에 즉시 적용한다. */ }
}

function resetSavedRecords() {
  try {
    localStorage.setItem(RECORD_STORAGE_KEY, JSON.stringify({ version: 1, records: [] }));
  } catch (err) {
    console.warn("대국 기록 저장소를 초기화하지 못했습니다.", err);
  }
  return [];
}

function readSavedRecords() {
  try {
    const raw = localStorage.getItem(RECORD_STORAGE_KEY);
    if (raw == null || raw === "") return resetSavedRecords();
    const parsed = JSON.parse(raw);
    const validRecord = record => record && typeof record === "object"
      && typeof record.game_id === "string" && record.game_id.length > 0
      && ["win", "loss", "draw"].includes(record.result)
      && typeof record.ended_at === "number"
      && Array.isArray(record.yaku) && record.yaku.every(name => typeof name === "string");
    if (!parsed || parsed.version !== 1 || !Array.isArray(parsed.records)
      || parsed.records.length > MAX_SAVED_RECORDS || !parsed.records.every(validRecord)) {
      return resetSavedRecords();
    }
    return parsed.records;
  } catch (err) {
    return resetSavedRecords();
  }
}

function writeSavedRecords(records) {
  try {
    localStorage.setItem(RECORD_STORAGE_KEY, JSON.stringify({ version: 1, records }));
    return true;
  } catch (err) {
    console.warn("대국 기록을 저장하지 못했습니다.", err);
    return false;
  }
}

function renderSavedRecords() {
  if (!savedRecordsListEl || !historyCountEl) return;
  const records = readSavedRecords();
  historyCountEl.textContent = `보존 기록: ${records.length}`;
  savedRecordsListEl.innerHTML = "";
  records.slice().reverse().forEach(record => {
    const item = document.createElement("li");
    const label = record.result === "win" ? "승리" : record.result === "loss" ? "패배" : "무승부";
    const method = record.winning_type === "tsumo" ? "쯔모" : record.winning_type === "ron" ? "론" : "유국";
    const yaku = record.yaku.length ? ` · ${record.yaku.join(", ")}` : "";
    item.textContent = `${label} · ${method}${yaku} · ${new Date(record.ended_at).toLocaleString("ko-KR")}`;
    savedRecordsListEl.appendChild(item);
  });
  if (records.length === 0) {
    const item = document.createElement("li");
    item.textContent = "아직 저장된 대국 기록이 없습니다.";
    savedRecordsListEl.appendChild(item);
  }
}

function recordCompletedGame(state) {
  if (!state || !state.is_game_over || typeof state.game_id !== "string" || !state.game_id) return;
  const records = readSavedRecords();
  if (records.some(record => record.game_id === state.game_id)) return;
  const result = state.winning_type === "draw" ? "draw" : state.winner === 0 ? "win" : "loss";
  records.push({
    game_id: state.game_id,
    result,
    winning_type: state.winning_type || "draw",
    ended_at: Date.now(),
    yaku: (state.winning_yaku || []).map(yaku => yaku.name).filter(name => typeof name === "string")
  });
  writeSavedRecords(records.slice(-MAX_SAVED_RECORDS));
  renderSavedRecords();
}

function acceptState(data) {
  if (gameState && data.revision < gameState.revision) return false;
  if (gameState && data.revision !== gameState.revision) {
    document.querySelectorAll(".kan-choice").forEach(button => button.remove());
  }
  gameState = data;
  recordCompletedGame(data);
  return true;
}

function getDrawnTileIndex(state) {
  if (state.current_turn !== 0 || state.pending_reaction || state.is_game_over || state.must_discard_after_call) return -1;
  const human = state.players[0];
  const tiles = human.concealed_tiles;
  if (Number.isInteger(state.current_drawn_index) && state.current_drawn_index >= 0 && state.current_drawn_index < tiles.length) {
    return state.current_drawn_index;
  }
  if (Object.prototype.hasOwnProperty.call(state, "current_drawn_tile")) {
    if (state.current_drawn_tile == null) return -1;
    // 정렬되거나 같은 종류의 패가 있어도 서버의 패 코드·적패 여부로 찾는다.
    for (let i = tiles.length - 1; i >= 0; i--) {
      if (tiles[i].code === state.current_drawn_tile.code && tiles[i].is_aka === state.current_drawn_tile.is_aka) return i;
    }
    return -1;
  }
  // 실행 중인 구버전 서버에는 쯔모패 필드가 없다. 문전/리치의 14장 상태는
  // 마지막에 추가된 패가 쯔모패이므로 기존 대국을 계속 진행할 수 있다.
  if ((human.is_riichi || human.melds.length === 0) && tiles.length === 14 - 3 * human.melds.length) {
    return tiles.length - 1;
  }
  return -1;
}

// DOM 요소들
const wallCountEl = document.getElementById("wall-count");
const doraTileEl = document.getElementById("dora-tile");
const roundWindEl = document.getElementById("round-wind");

const aiHandTilesEl = document.getElementById("ai-hand-tiles");
const aiMeldsEl = document.getElementById("ai-melds");
const aiDiscardsEl = document.getElementById("ai-discards");
const aiWindEl = document.getElementById("ai-wind");
const aiRiichiBadgeEl = document.getElementById("ai-riichi-badge");

const humanHandTilesEl = document.getElementById("human-hand-tiles");
const drawnTileSlotEl = document.getElementById("drawn-tile-slot");
const humanMeldsEl = document.getElementById("human-melds");
const humanDiscardsEl = document.getElementById("human-discards");
const humanWindEl = document.getElementById("human-wind");
const humanRiichiBadgeEl = document.getElementById("human-riichi-badge");

const turnIndicatorEl = document.getElementById("turn-indicator");
const centerBannerEl = document.getElementById("center-banner");

const tenpaiBarEl = document.getElementById("tenpai-bar");
const tenpaiTilesEl = document.getElementById("tenpai-tiles");
const furitenLabelEl = document.getElementById("furiten-label");

const btnTsumo = document.getElementById("btn-tsumo");
const btnTsumogiri = document.getElementById("btn-tsumogiri");
const btnRiichi = document.getElementById("btn-riichi");
const riichiStatus = document.getElementById("riichi-status");
const btnKan = document.getElementById("btn-kan");
const btnRestart = document.getElementById("btn-restart");
const btnPause = document.getElementById("btn-pause");
const pauseModal = document.getElementById("pause-modal");
const btnResume = document.getElementById("btn-resume");
const startModal = document.getElementById("start-modal");
const gameContainer = document.getElementById("game-container");
const startError = document.getElementById("start-error");
const btnStartGame = document.getElementById("btn-start-game");
const btnHowToPlay = document.getElementById("btn-how-to-play");
const howToPlayPanel = document.getElementById("how-to-play-panel");
const difficultySelectEl = document.getElementById("difficulty-select");
const difficultyDescriptionEl = document.getElementById("difficulty-description");
const difficultyTargetYakuEl = document.getElementById("difficulty-target-yaku");
const reduceMotionToggle = document.getElementById("reduce-motion-toggle");
reduceMotionToggle.checked = readReduceActionMotion();
applyReduceActionMotion(reduceMotionToggle.checked);

const reactionModal = document.getElementById("reaction-modal");
const reactionButtons = document.getElementById("reaction-buttons");
const reactionTargetTile = document.getElementById("reaction-target-tile");

const gameoverModal = document.getElementById("gameover-modal");
const gameoverTitle = document.getElementById("gameover-title");
const gameoverWinnerBadge = document.getElementById("gameover-winner-badge");
const gameoverWinTile = document.getElementById("gameover-win-tile");
const gameoverHand = document.getElementById("gameover-hand");
const gameoverYakuList = document.getElementById("gameover-yaku-list");
const btnModalRestart = document.getElementById("btn-modal-restart");
const savedRecordsListEl = document.getElementById("saved-records-list");
const historyCountEl = document.getElementById("history-count");

renderSavedRecords();

/**
 * 마작패 DOM 엘리먼트 생성기
 */
function createTileElement(tile, options = {}) {
  const el = document.createElement("div");
  const miniClass = options.isMini ? "tile-mini" : "";
  const lockedClass = options.isLocked ? "locked" : "";
  const akaClass = tile.is_aka ? "is-aka" : "";
  const riichiTurnClass = options.isRiichiTurn ? "riichi-turn" : "";
  const riichiCandClass = options.isRiichiCandidate
    ? `riichi-candidate${options.animateRiichiCandidate ? " entry-motion" : ""}` : "";
  const meldEntryClass = options.meldEntry ? "meld-tile-entry" : "";
  if (options.isTsumogiri) el.title = "쯔모기리";

  el.className = `tile suit-${tile.suit} tile-code-${tile.code} ${miniClass} ${lockedClass} ${akaClass} ${riichiTurnClass} ${riichiCandClass} ${meldEntryClass}`.trim();
  if (options.meldEntry) el.style.animationDelay = `${(options.meldEntryIndex || 0) * 55}ms`;

  let topChar = "";
  let botChar = "";

  if (tile.suit === "m") {
    topChar = KANJI_NUMS[tile.value] || tile.value;
    botChar = "萬";
  } else if (tile.suit === "p") {
    topChar = tile.value;
    botChar = "筒";
  } else if (tile.suit === "s") {
    topChar = tile.value;
    botChar = "索";
  } else if (tile.suit === "z") {
    topChar = HONOR_NAMES[tile.value] || tile.value;
    botChar = "";
  }

  el.innerHTML = `
    <div class="tile-content">
      <span class="tile-char-top">${topChar}</span>
      ${botChar ? `<span class="tile-char-bot">${botChar}</span>` : ""}
    </div>
  `;

  if (options.onClick) {
    el.addEventListener("click", options.onClick);
  }

  return el;
}

/**
 * API 호출 래퍼
 */
async function fetchState() {
  if (isSendingAction) return false;
  try {
    const res = await fetch("/api/state?t=" + Date.now());
    if (!res.ok) throw new Error("서버 응답 오류: " + res.status);
    const data = await res.json();
    if (!data || !Array.isArray(data.players) || data.players.length < 2 || !Array.isArray(data.players[0].concealed_tiles)) {
      throw new Error("서버에서 손패 정보를 받지 못했습니다.");
    }
    if (!acceptState(data)) return true;
    connectionError = "";
    if (!render()) throw new Error("게임 화면을 표시하지 못했습니다.");
    startError.textContent = "";
    if (startModal.style.display !== "none" && !btnStartGame.disabled) {
      btnStartGame.textContent = "🀄 게임 시작";
    }

    // AI 턴 진행이 필요할 경우 스케줄링
    checkAiTurn();
    return true;
  } catch (err) {
    console.error("상태 로드 에러:", err);
    startError.textContent = typeof location !== "undefined" && location.protocol === "file:"
      ? "게임 파일을 직접 열지 말고 mazak.py를 실행해 주세요."
      : "서버 연결 또는 손패 표시에 실패했습니다. 잠시 후 다시 시도해 주세요.";
    if (centerBannerEl) {
      centerBannerEl.textContent = "서버에 연결 중입니다... (잠시만 기다려주세요)";
    }
    return false;
  }
}

async function sendAction(actionData) {
  if (isSendingAction || isPaused) return;
  isSendingAction = true;
  render();
  try {
    const res = await fetch("/api/action?t=" + Date.now(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...actionData, revision: gameState.revision })
    });
    if (!res.ok) throw new Error("액션 응답 오류: " + res.status);
    const data = await res.json();
    if (!acceptState(data)) return;
    connectionError = "";
    declareRiichiNext = false;
    if (actionData.action === "restart") {
      startModal.style.display = "flex";
      gameContainer.style.visibility = "hidden";
    }
    render();
  } catch (err) {
    console.error("액션 실행 에러:", err);
    connectionError = "동작을 처리하지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.";
  } finally {
    isSendingAction = false;
    render();
    checkAiTurn();
  }
}

/**
 * AI 턴 자동 실행
 */
function checkAiTurn() {
  if (!gameState || gameState.is_game_over || isPaused || isSendingAction || startModal.style.display !== "none") return;

  // AI 턴이고 대기 중인 상태면 AI 턴 진행 요청
  if (gameState.current_turn === 1 && !isWaitingAi && (!gameState.pending_reaction || gameState.pending_reaction.player_idx !== 0)) {
    isWaitingAi = true;
    setTimeout(async () => {
      try {
        if (gameState.current_turn === 1 && !gameState.pending_reaction && !gameState.is_game_over) {
          await sendAction({ action: "ai_step" });
        }
      } finally {
        isWaitingAi = false;
        checkAiTurn();
      }
    }, 600); // 0.6초 딜레이로 생각하는 연출
  }
}

/**
 * 전체 렌더링
 */
function setActionVisibility(element, visible) {
  const wasVisible = element.style.display !== "none";
  element.style.display = visible ? "inline-block" : "none";
  if (visible && !wasVisible) {
    element.classList.add("entry-motion");
    element.addEventListener("animationend", () => element.classList.remove("entry-motion"), { once: true });
  }
}

function getMeldEntryEffectIndexes(signatures, previousSignatures, pendingEffects) {
  const now = Date.now();
  if (previousSignatures) {
    signatures.forEach((signature, index) => {
      if (previousSignatures[index] !== signature) {
        pendingEffects.set(index, { signature, expiresAt: now + 900 });
      }
    });
  }
  const activeIndexes = new Set();
  for (const [index, effect] of pendingEffects) {
    if (effect.expiresAt <= now || signatures[index] !== effect.signature) {
      pendingEffects.delete(index);
    } else {
      activeIndexes.add(index);
    }
  }
  return activeIndexes;
}

function render() {
  if (!gameState) return false;

  try {
    // 헤더 정보
    wallCountEl.textContent = gameState.wall_remaining;
    roundWindEl.textContent = `${WIND_NAMES[gameState.round_wind] || "동"} 1국`;

  // 도라 표시패
  doraTileEl.innerHTML = "";
  if (gameState.dora_indicator) {
    doraTileEl.appendChild(createTileElement(gameState.dora_indicator, { isMini: true }));
  }

  const human = gameState.players[0];
  const ai = gameState.players[1];

  const difficulty = gameState.difficulty || "medium";
  const difficultyLabels = { low: "하", medium: "중", high: "상" };
  const difficultySummary = {
    low: "리치·핑후만 AI 목표 역으로 허용합니다.",
    medium: "리치·핑후·탕야오·치토이츠를 AI 목표 역으로 허용합니다.",
    high: "게임에서 지원하는 모든 역을 AI 목표 역으로 허용합니다."
  };
  difficultySelectEl.value = difficulty;
  difficultySelectEl.disabled = isSendingAction || gameState.can_change_difficulty === false;
  difficultyDescriptionEl.textContent = gameState.can_change_difficulty === false
    ? `현재 대국에서는 난이도를 바꿀 수 없습니다. 새 게임을 시작하면 변경할 수 있습니다. (${difficultyLabels[difficulty] || "중"})`
    : difficultySummary[difficulty] || difficultySummary.medium;
  difficultyTargetYakuEl.innerHTML = "";
  (gameState.difficulty_target_yaku || []).forEach(name => {
    const item = document.createElement("li");
    item.textContent = name;
    difficultyTargetYakuEl.appendChild(item);
  });

  // 1. AI 렌더링
  aiWindEl.textContent = WIND_NAMES[ai.seat_wind] || "";
  aiRiichiBadgeEl.style.display = ai.is_riichi ? "inline-block" : "none";
  const aiMeldSignatures = ai.melds.map(meld => JSON.stringify(meld));
  const animateAiMeldIndices = getMeldEntryEffectIndexes(aiMeldSignatures, previousAiMeldSignatures, pendingAiMeldEffects);

  aiHandTilesEl.innerHTML = "";
  for (let i = 0; i < ai.concealed_count; i++) {
    const backTile = document.createElement("div");
    backTile.className = "tile-back";
    aiHandTilesEl.appendChild(backTile);
  }

  // AI 울기 멘츠
  aiMeldsEl.innerHTML = "";
  ai.melds.forEach((meld, index) => {
    const group = document.createElement("div");
    const isChangedMeld = animateAiMeldIndices.has(index);
    group.className = `meld-group${isChangedMeld ? " meld-entry-flash" : ""}`;
    if (isChangedMeld) setTimeout(() => group.classList.remove("meld-entry-flash"), 900);
    meld.tiles.forEach((t, tileIndex) => {
      const meldTile = createTileElement(t, { isMini: true, meldEntry: isChangedMeld, meldEntryIndex: tileIndex });
      if (isChangedMeld) meldTile.addEventListener("animationend", () => meldTile.classList.remove("meld-tile-entry"), { once: true });
      group.appendChild(meldTile);
    });
    aiMeldsEl.appendChild(group);
  });
  previousAiMeldSignatures = aiMeldSignatures;

  // AI 버림패
  aiDiscardsEl.innerHTML = "";
  ai.discards.forEach(item => {
    aiDiscardsEl.appendChild(createTileElement(item.tile, {
      isMini: true,
      isTsumogiri: item.is_tsumogiri,
      isRiichiTurn: item.is_riichi
    }));
  });

  // 2. 플레이어 렌더링
  humanWindEl.textContent = WIND_NAMES[human.seat_wind] || "";
  humanRiichiBadgeEl.style.display = human.is_riichi ? "inline-block" : "none";
  const humanMeldSignatures = human.melds.map(meld => JSON.stringify(meld));
  const animateHumanMeldIndices = getMeldEntryEffectIndexes(humanMeldSignatures, previousHumanMeldSignatures, pendingHumanMeldEffects);

  // 버림패
  humanDiscardsEl.innerHTML = "";
  human.discards.forEach(item => {
    humanDiscardsEl.appendChild(createTileElement(item.tile, {
      isMini: true,
      isTsumogiri: item.is_tsumogiri,
      isRiichiTurn: item.is_riichi
    }));
  });

  // 손패
  humanHandTilesEl.innerHTML = "";
  drawnTileSlotEl.innerHTML = "";

  const isMyTurn = (gameState.current_turn === 0 && !gameState.pending_reaction && !gameState.is_game_over && !isPaused);
  const myTiles = human.concealed_tiles;
  const isRiichiLocked = human.is_riichi;
  const turnActions = gameState.human_turn_actions || {};
  const riichiCandidates = turnActions.riichi_candidates || [];

  // 쯔모패 분리
  const drawnIndex = getDrawnTileIndex(gameState);
  const hasDrawnTile = drawnIndex >= 0;
  const standingTiles = myTiles.map((tile, index) => ({ tile, index })).filter(item => item.index !== drawnIndex);
  const drawnTile = hasDrawnTile ? myTiles[drawnIndex] : null;

  standingTiles.forEach(({tile, index}) => {
    const isCand = declareRiichiNext && riichiCandidates.some(c => c.code === tile.code);
    const tileEl = createTileElement(tile, {
      isLocked: !isMyTurn || isSendingAction || isRiichiLocked || (declareRiichiNext && !isCand),
      isRiichiCandidate: isCand,
      animateRiichiCandidate: isCand && riichiEntryAnimationPending,
      onClick: () => {
        if (!isMyTurn || isSendingAction || isRiichiLocked || (declareRiichiNext && !isCand)) return;
        sendAction({
          action: "discard",
          index,
          riichi: declareRiichiNext
        });
      }
    });
    humanHandTilesEl.appendChild(tileEl);
  });

  if (drawnTile) {
    const isCand = declareRiichiNext && riichiCandidates.some(c => c.code === drawnTile.code);
    const drawnEl = createTileElement(drawnTile, {
      isLocked: !isMyTurn || isSendingAction || (declareRiichiNext && !isCand),
      isRiichiCandidate: isCand,
      animateRiichiCandidate: isCand && riichiEntryAnimationPending,
      onClick: () => {
        if (!isMyTurn || isSendingAction || (declareRiichiNext && !isCand)) return;
        sendAction({
          action: "discard",
          index: drawnIndex,
          riichi: declareRiichiNext
        });
      }
    });
    drawnEl.title = "쯔모패 · 클릭하여 버리기";
    drawnTileSlotEl.appendChild(drawnEl);
  }
  riichiEntryAnimationPending = false;

  // 플레이어 울기 멘츠
  humanMeldsEl.innerHTML = "";
  human.melds.forEach((meld, index) => {
    const group = document.createElement("div");
    const isChangedMeld = animateHumanMeldIndices.has(index);
    group.className = `meld-group${isChangedMeld ? " meld-entry-flash" : ""}`;
    if (isChangedMeld) setTimeout(() => group.classList.remove("meld-entry-flash"), 900);
    meld.tiles.forEach((t, tileIndex) => {
      const meldTile = createTileElement(t, { isMini: true, meldEntry: isChangedMeld, meldEntryIndex: tileIndex });
      if (isChangedMeld) meldTile.addEventListener("animationend", () => meldTile.classList.remove("meld-tile-entry"), { once: true });
      group.appendChild(meldTile);
    });
    humanMeldsEl.appendChild(group);
  });
  previousHumanMeldSignatures = humanMeldSignatures;

  // 3. 텐파이 및 대기패
  if (gameState.human_waits && gameState.human_waits.length > 0) {
    tenpaiBarEl.style.display = "flex";
    tenpaiTilesEl.innerHTML = "";
    gameState.human_waits.forEach(w => {
      tenpaiTilesEl.appendChild(createTileElement(w, { isMini: true }));
    });
    furitenLabelEl.style.display = gameState.is_human_furiten ? "inline-block" : "none";
  } else {
    tenpaiBarEl.style.display = "none";
  }

  // 4. 중앙 상태 안내
  if (gameState.is_game_over) {
    turnIndicatorEl.textContent = "대국이 종료되었습니다";
    turnIndicatorEl.style.borderColor = "#94a3b8";
    turnIndicatorEl.style.color = "#94a3b8";
  } else if (isPaused) {
    turnIndicatorEl.textContent = "일시정지 중입니다";
    turnIndicatorEl.style.borderColor = "#94a3b8";
    turnIndicatorEl.style.color = "#94a3b8";
  } else if (isMyTurn) {
    turnIndicatorEl.textContent = "당신의 턴입니다";
    turnIndicatorEl.style.borderColor = "var(--gold)";
    turnIndicatorEl.style.color = "var(--gold)";
  } else {
    turnIndicatorEl.textContent = "상대 AI의 턴입니다";
    turnIndicatorEl.style.borderColor = "#94a3b8";
    turnIndicatorEl.style.color = "#94a3b8";
  }

  if (connectionError) {
    centerBannerEl.textContent = connectionError;
  } else if (declareRiichiNext) {
    centerBannerEl.textContent = "★ 리치: 황금빛 후보 패를 선택하세요. 다른 패는 버릴 수 없습니다.";
  } else if (isMyTurn && isRiichiLocked && hasDrawnTile && !turnActions.can_tsumo) {
    centerBannerEl.textContent = "리치 중입니다. 오른쪽 쯔모패를 클릭하거나 ‘쯔모패 버리기’를 눌러 진행하세요.";
  } else if (gameState.last_message) {
    centerBannerEl.textContent = gameState.last_message;
  } else {
    centerBannerEl.textContent = "";
  }

  // 5. 턴 액션 버튼 (쯔모, 리치, 깡)
  btnTsumo.style.display = (isMyTurn && turnActions.can_tsumo) ? "inline-block" : "none";
  btnTsumogiri.style.display = (isMyTurn && isRiichiLocked && hasDrawnTile) ? "inline-block" : "none";
  btnTsumogiri.disabled = isSendingAction;
  setActionVisibility(btnRiichi, isMyTurn && !human.is_riichi);
  btnRiichi.disabled = isSendingAction || !turnActions.can_riichi;
  riichiStatus.textContent = isMyTurn && !human.is_riichi && !turnActions.can_riichi
    ? (turnActions.riichi_unavailable_reason || "리치는 문전 상태에서 한 장을 버려 텐파이가 될 때 가능합니다.") : "";
  btnRiichi.textContent = declareRiichiNext ? "리치 취소" : "리치 선언";
  btnRiichi.style.background = declareRiichiNext ? "#4b5563" : "";
  setActionVisibility(btnKan, isMyTurn && turnActions.kans && turnActions.kans.length > 0);

  // 6. 상대 타패 반응 모달 (론 / 퐁 / 치 / 깡 / 패스)
  const pendingReaction = gameState.pending_reaction;
  if (startModal.style.display === "none" && pendingReaction && pendingReaction.player_idx === 0 && pendingReaction.actions.length > 0) {
    showReactionModal(pendingReaction);
  } else {
    reactionModal.style.display = "none";
  }

  // 7. 대국 종료 모달
  if (startModal.style.display === "none" && gameState.is_game_over) {
    pauseModal.style.display = "none";
    gameoverModal.style.zIndex = "130";
    showGameOverModal();
  } else {
    gameoverModal.style.display = "none";
    pauseModal.style.display = isPaused && startModal.style.display === "none" ? "flex" : "none";
  }
  return true;
  } catch (err) {
    console.error("렌더링 도중 예외 발생:", err);
    return false;
  }
}

/**
 * 반응 모달 팝업 표시
 */
function showReactionModal(pending) {
  reactionModal.style.display = "flex";
  reactionButtons.innerHTML = "";
  reactionTargetTile.innerHTML = "";

  const targetTile = pending.target_tile;
  reactionTargetTile.appendChild(createTileElement(targetTile));

  const actions = pending.actions;

  actions.forEach((act, idx) => {
    const btn = document.createElement("button");
    btn.className = "btn";

    if (act.type === "ron") {
      btn.className += " btn-win btn-action";
      btn.textContent = "론(Ron) 화료!!";
    } else if (act.type === "pon") {
      btn.className += " btn-meld";
      btn.textContent = "퐁(Pon)";
    } else if (act.type === "chi") {
      btn.className += " btn-meld";
      const partnerStr = act.partner ? ` (${act.partner.map(p => p.name).join(" ")})` : "";
      btn.textContent = `치(Chi)${partnerStr}`;
    } else if (act.type === "kan") {
      btn.className += " btn-meld";
      btn.textContent = "대명깡(Kan)";
    }
    if (["chi", "pon", "kan"].includes(act.type)) btn.classList.add("entry-motion");

    btn.addEventListener("click", () => {
      sendAction({ action: "reaction", choice: act });
    });
    reactionButtons.appendChild(btn);
  });

  // 패스 버튼
  const passBtn = document.createElement("button");
  passBtn.className = "btn btn-secondary";
  passBtn.textContent = "패스(Pass)";
  passBtn.addEventListener("click", () => {
    sendAction({ action: "reaction", choice: { type: "pass" } });
  });
  reactionButtons.appendChild(passBtn);
}

/**
 * 대국 종료 모달
 */
function showGameOverModal() {
  gameoverModal.style.display = "flex";
  gameoverYakuList.innerHTML = "";
  gameoverHand.innerHTML = "";
  gameoverWinTile.innerHTML = "";

  if (gameState.winning_type === "draw") {
    gameoverTitle.textContent = "유 국 (Draw)";
    gameoverWinnerBadge.textContent = "패산이 소진되어 무승부로 종료되었습니다.";
  } else {
    const winnerName = gameState.winner === 0 ? "당신" : "상대 AI";
    const winTypeStr = gameState.winning_type === "tsumo" ? "쯔모(Tsumo) 화료!" : "론(Ron) 화료!";
    gameoverTitle.textContent = gameState.winner === 0 ? "🎉 승리 (Win)! 🎉" : "대국 패배 (Lose)";
    gameoverWinnerBadge.textContent = `${winnerName}의 ${winTypeStr}`;

    if (gameState.winning_tile) {
      gameoverWinTile.appendChild(createTileElement(gameState.winning_tile));
    }

    const winnerHand = gameState.winning_hand;
    if (winnerHand) {
      winnerHand.forEach(t => gameoverHand.appendChild(createTileElement(t, { isMini: true })));
    }
    (gameState.winning_melds || []).forEach(meld => {
      const group = document.createElement("div");
      group.className = "meld-group";
      meld.tiles.forEach(t => group.appendChild(createTileElement(t, { isMini: true })));
      gameoverHand.appendChild(group);
    });

    if (gameState.winning_yaku && gameState.winning_yaku.length > 0) {
      gameState.winning_yaku.forEach(y => {
        const li = document.createElement("li");
        li.textContent = `${y.name} (${y.romaji})`;
        gameoverYakuList.appendChild(li);
      });
    } else {
      const li = document.createElement("li");
      li.textContent = "역 없음";
      gameoverYakuList.appendChild(li);
    }
  }
}

// 이벤트 리스너 바인딩
btnHowToPlay.addEventListener("click", () => {
  const expanded = btnHowToPlay.getAttribute ? btnHowToPlay.getAttribute("aria-expanded") === "true" : !howToPlayPanel.hidden;
  howToPlayPanel.hidden = expanded;
  btnHowToPlay.setAttribute?.("aria-expanded", String(!expanded));
  btnHowToPlay.textContent = expanded ? "게임 방법" : "게임 방법 닫기";
});

reduceMotionToggle.addEventListener("change", () => {
  applyReduceActionMotion(reduceMotionToggle.checked);
});

difficultySelectEl.addEventListener("change", () => {
  if (gameState && gameState.can_change_difficulty !== false && !isSendingAction) {
    sendAction({ action: "set_difficulty", difficulty: difficultySelectEl.value });
  }
});

btnPause.addEventListener("click", () => {
  if (!gameState || gameState.is_game_over || startModal.style.display !== "none") return;
  isPaused = true;
  render();
});

btnResume.addEventListener("click", () => {
  isPaused = false;
  render();
  checkAiTurn();
});

btnStartGame.addEventListener("click", async () => {
  btnStartGame.disabled = true;
  btnStartGame.textContent = "게임을 불러오는 중...";
  try {
    if (await fetchState()) {
      startModal.style.display = "none";
      gameContainer.style.visibility = "visible";
      if (!render()) {
        startModal.style.display = "flex";
        gameContainer.style.visibility = "hidden";
        startError.textContent = "손패를 표시하지 못했습니다. 다시 시도해 주세요.";
        btnStartGame.textContent = "다시 시도";
        return;
      }
      checkAiTurn();
    } else {
      btnStartGame.textContent = "연결 실패 · 다시 시도";
    }
  } finally {
    btnStartGame.disabled = false;
  }
});

btnTsumo.addEventListener("click", () => {
  sendAction({ action: "tsumo" });
});

btnTsumogiri.addEventListener("click", () => {
  const index = getDrawnTileIndex(gameState);
  if (!isSendingAction && gameState.players[0].is_riichi && index >= 0) {
    sendAction({ action: "discard", index });
  }
});

btnRiichi.addEventListener("click", () => {
  if (!gameState || !gameState.human_turn_actions.can_riichi || isSendingAction) return;
  declareRiichiNext = !declareRiichiNext;
  riichiEntryAnimationPending = declareRiichiNext;
  render();
});

btnKan.addEventListener("click", () => {
  const kans = gameState.human_turn_actions.kans || [];
  if (kans.length <= 1) {
    sendAction({ action: "kan" });
    return;
  }
  // 복수의 깡 후보를 각각 선택할 수 있도록 기존 액션 바에 표시한다.
  document.querySelectorAll(".kan-choice").forEach(button => button.remove());
  kans.forEach((kan, index) => {
    const button = document.createElement("button");
    button.className = "btn btn-meld kan-choice entry-motion";
    button.textContent = `${kan.kan_type === "ankan" ? "암깡" : "가깡"} ${kan.tile.name}`;
    button.addEventListener("click", () => {
      document.querySelectorAll(".kan-choice").forEach(choice => choice.remove());
      sendAction({ action: "kan", kan_index: index });
    });
    btnKan.parentElement.appendChild(button);
  });
});

btnRestart.addEventListener("click", () => {
  if (confirm("새 게임을 시작하시겠습니까?")) {
    sendAction({ action: "restart" });
  }
});

btnModalRestart.addEventListener("click", () => {
  sendAction({ action: "restart" });
});

// 초기화 시작 및 주기적 동기화 폴링 (1.5초)
fetchState();
setInterval(fetchState, 1500);
