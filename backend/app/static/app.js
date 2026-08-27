// ============================================================================
// Mafia Mini App — client
// Talks to the FastAPI backend over REST (auth + join) and WebSocket (live
// game state). Every screen render is driven by the server's state push —
// this file never invents game facts the server hasn't sent.
// ============================================================================

const API = ""; // same-origin: this file is served by the FastAPI app itself

let sessionToken = null;
let myTelegramId = null;
let gameId = null;
let myPlayerId = null;
let ws = null;
let wsRetryDelay = 1500;
let currentState = null;   // last "state" payload from the server
let selectedTarget = null; // currently-highlighted player in night/vote lists
let lastShownNightDeathFor = -1; // night_number we've already shown the death interstitial for
let countdownTimer = null;

// ----------------------------------------------------------------- i18n ---
// Shared with the bot (app/i18n.py) via the language field on
// POST /auth/telegram, and via ?lang= for the bot's "Rollar" kiosk link —
// see applyLanguage() usage in boot() below. Covers the static UI chrome;
// role catalog desc/ability text lives in ROLE_I18N further down, next to
// the ROLES data it overrides.
let currentLang = "uz";
const I18N = {
  uz: {
    home_eyebrow: "Do'stlar davrasi", home_enter: "O'yinga kirish",
    home_rules_roles: "Qoidalar va rollar",
    home_notice: "Botni guruhingizga admin qiling va <b style=\"color:var(--gold)\">/start</b> buyrug'ini yuboring",
    lobby_title: "LOBBI", lobby_players_label: "O'YINCHILAR", lobby_start_btn: "O'yinni boshlash",
    lobby_notice: "25 taga to'lganda o'yin avtomatik boshlanadi",
    role_title: "SENING ROLING", role_understood_btn: "Tushundim",
    night_title: "TUN", night_action_label: "HARAKATINGIZ", day_title: "KUN",
    vote_title: "OVOZ BERISH", vote_submit_btn: "Ovozimni tasdiqlash",
    outcome_continue_btn: "Davom etish",
    roles_title: "ROLLAR", tab_all: "Hammasi", tab_mafia: "Mafia", tab_town: "Shahar", tab_neutral: "Neytral",
    nav_home: "Home", nav_lobby: "Lobby", nav_roles: "Rollar", nav_admin: "Admin",
    chat_placeholder: "Xabar yozing...", role_ability_label: "Qobiliyati",
  },
  ru: {
    home_eyebrow: "Круг друзей", home_enter: "Войти в игру",
    home_rules_roles: "Правила и роли",
    home_notice: "Сделайте бота админом группы и отправьте команду <b style=\"color:var(--gold)\">/start</b>",
    lobby_title: "ЛОББИ", lobby_players_label: "ИГРОКИ", lobby_start_btn: "Начать игру",
    lobby_notice: "Игра начнётся автоматически при 25 игроках",
    role_title: "ВАША РОЛЬ", role_understood_btn: "Понятно",
    night_title: "НОЧЬ", night_action_label: "ВАШЕ ДЕЙСТВИЕ", day_title: "ДЕНЬ",
    vote_title: "ГОЛОСОВАНИЕ", vote_submit_btn: "Подтвердить голос",
    outcome_continue_btn: "Продолжить",
    roles_title: "РОЛИ", tab_all: "Все", tab_mafia: "Мафия", tab_town: "Город", tab_neutral: "Нейтральные",
    nav_home: "Главная", nav_lobby: "Лобби", nav_roles: "Роли", nav_admin: "Админ",
    chat_placeholder: "Напишите сообщение...", role_ability_label: "Способность",
  },
  en: {
    home_eyebrow: "Circle of Friends", home_enter: "Enter the game",
    home_rules_roles: "Rules and roles",
    home_notice: "Make the bot a group admin and send the <b style=\"color:var(--gold)\">/start</b> command",
    lobby_title: "LOBBY", lobby_players_label: "PLAYERS", lobby_start_btn: "Start game",
    lobby_notice: "The game starts automatically once 25 players join",
    role_title: "YOUR ROLE", role_understood_btn: "Got it",
    night_title: "NIGHT", night_action_label: "YOUR ACTION", day_title: "DAY",
    vote_title: "VOTING", vote_submit_btn: "Confirm my vote",
    outcome_continue_btn: "Continue",
    roles_title: "ROLES", tab_all: "All", tab_mafia: "Mafia", tab_town: "Town", tab_neutral: "Neutral",
    nav_home: "Home", nav_lobby: "Lobby", nav_roles: "Roles", nav_admin: "Admin",
    chat_placeholder: "Type a message...", role_ability_label: "Ability",
  },
};

function applyLanguage(lang) {
  currentLang = I18N[lang] ? lang : "uz";
  const dict = I18N[currentLang];
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    if (dict[el.getAttribute("data-i18n")] !== undefined) el.textContent = dict[el.getAttribute("data-i18n")];
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    if (dict[el.getAttribute("data-i18n-html")] !== undefined) el.innerHTML = dict[el.getAttribute("data-i18n-html")];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    if (dict[el.getAttribute("data-i18n-placeholder")] !== undefined) el.placeholder = dict[el.getAttribute("data-i18n-placeholder")];
  });
  if (typeof renderRoles === "function") {
    const activeTab = document.querySelector(".tab.active");
    renderRoles(activeTab ? activeTab.dataset.fac : "all");
  }
}

// ---------------------------------------------------------------- boot ----

document.addEventListener("DOMContentLoaded", boot);

// ------------------------------------------------------- home hero art ----
// The home screen no longer ships one fixed picture baked into the HTML.
// Instead it cycles through the role card art (defined further down in
// ROLES) so a different role's image is showing each time, chosen at
// random and rotated on a timer.
const HOME_HERO_ROTATE_MS = 5000;
let homeHeroTimer = null;

function startHomeHeroRotation() {
  const el = document.getElementById("homeHero");
  if (!el || typeof ROLES === "undefined" || !ROLES.length) return;

  const images = ROLES.map((r) => r.card);
  let deck = [];
  let lastImage = null;

  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  // Preloads the candidate image before ever touching the visible
  // background, and — on a failed or still-loading request (a cold-started
  // free-tier instance can be slow to serve the very first image) — moves
  // on to another candidate instead of leaving the box on its plain
  // background-color indefinitely, which is what an unhandled load failure
  // here looks like: an empty dark box with no image and no error shown.
  function showNext(attemptsLeft) {
    if (!deck.length) deck = shuffle(images);
    let src = deck.pop();
    // Avoid showing the same image twice in a row when possible.
    if (src === lastImage && deck.length) src = deck.pop();

    const preload = new Image();
    preload.onload = () => {
      lastImage = src;
      el.style.backgroundImage = `url('${src}')`;
    };
    preload.onerror = () => {
      if (attemptsLeft > 0) showNext(attemptsLeft - 1);
    };
    preload.src = src;
  }

  showNext(images.length);
  if (homeHeroTimer) clearInterval(homeHeroTimer);
  homeHeroTimer = setInterval(() => showNext(images.length), HOME_HERO_ROTATE_MS);
}

async function boot() {
  startHomeHeroRotation();

  // Kiosk mode: the bot's "Rollar" menu button (app/telegram_bot.py) opens
  // this same page with ?view=roles so it lands straight on the role
  // catalog with nothing else navigable — no Telegram session needed for
  // that (it's static reference content), so this skips auth entirely
  // instead of failing on a missing/irrelevant initData.
  const requestedView = new URLSearchParams(location.search).get("view");
  if (requestedView === "roles") {
    document.body.classList.add("kiosk-roles");
    applyLanguage(new URLSearchParams(location.search).get("lang") || "uz");
    go("roles");
    return;
  }

  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor("#050403"); tg.setBackgroundColor("#050403"); } catch (e) {}
  }

  const initData = tg && tg.initData ? tg.initData : "";
  if (!initData) {
    // Opened outside Telegram (e.g. a plain browser). The rest of the app
    // needs a verified Telegram identity, so it stops here rather than
    // pretending to be a real session.
    document.getElementById("homeNotice").innerHTML =
      "Bu ilova faqat Telegram ichida, guruhdagi tugma orqali ochiladi.";
    document.getElementById("enterBtn").disabled = true;
    return;
  }

  try {
    const auth = await fetch(API + "/auth/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData }),
    }).then(mustOk);
    sessionToken = auth.session_token;
    myTelegramId = auth.telegram_user_id;
    window.__displayName = auth.display_name || "O'yinchi";
    isBotAdmin = !!auth.is_bot_admin;
    updateAdminNavVisibility();
    applyLanguage(auth.language || "uz");
  } catch (e) {
    document.getElementById("homeNotice").textContent =
      "Autentifikatsiya muvaffaqiyatsiz. Ilovani qayta oching.";
    document.getElementById("enterBtn").disabled = true;
    return;
  }

  // Reconnect scenario (spec item 6): Telegram was closed and reopened, the
  // WebApp was refreshed, or the connection just dropped — in every one of
  // these the page reloads from scratch and this whole file re-runs, so
  // gameId/myPlayerId/ws are all back to null even though the match on the
  // server is still going. As long as the group's chat_id is still in the
  // URL (which it is: Telegram reopens this exact link), there's no reason
  // to make the player tap "Kirish" again — rejoin automatically and let
  // the very next "state" push put them back on whatever screen (night,
  // day, vote, ...) the game is actually on, with their real role, alive
  // status, and timer, exactly where they left off.
  if (currentChatId()) {
    await enterLobby();
  }
}

function currentChatId() {
  const tg = window.Telegram && window.Telegram.WebApp;
  const fromTelegram = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
  if (fromTelegram) return fromTelegram;
  // Dev convenience only: ?chat_id=... in the URL when testing outside a
  // real bot-issued link. Telegram's own start_param is always preferred.
  return new URLSearchParams(location.search).get("chat_id");
}

// --------------------------------------------------------------- API/WS ---

function api(path, opts) {
  opts = opts || {};
  const headers = Object.assign(
    { "Content-Type": "application/json", "Authorization": "Bearer " + sessionToken },
    opts.headers || {}
  );
  return fetch(API + path, Object.assign({}, opts, { headers })).then(mustOk);
}

async function mustOk(res) {
  if (res.ok) return res.json();
  let detail = "Xatolik yuz berdi";
  try { detail = (await res.json()).detail || detail; } catch (e) {}
  const err = new Error(detail);
  err.status = res.status;
  throw err;
}

async function enterLobby() {
  const chatId = currentChatId();
  if (!chatId) {
    toast("Guruh aniqlanmadi. Iltimos, botning guruhdagi tugmasi orqali kiring.");
    return;
  }
  if (!sessionToken) { toast("Hali ulanmoqda, biroz kuting..."); return; }
  const btn = document.getElementById("enterBtn");
  btn.disabled = true;
  btn.textContent = "Ulanmoqda...";
  try {
    const res = await api("/games/for-chat", {
      method: "POST",
      body: JSON.stringify({ chat_id: chatId, display_name: window.__displayName || "O'yinchi" }),
    });
    gameId = res.game_id;
    myPlayerId = res.player_id;
    connectWS();
    go("lobby");
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "O'yinga kirish";
  }
}

function connectWS() {
  if (ws) { try { ws.close(); } catch (e) {} }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/games/${gameId}?token=${encodeURIComponent(sessionToken)}`);
  ws.onopen = () => { wsRetryDelay = 1500; setConnBanner(false); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") {
      currentState = msg.state;
      render();
    } else if (msg.type === "error") {
      toast(msg.message);
    }
  };
  ws.onclose = () => {
    setConnBanner(true);
    setTimeout(connectWS, wsRetryDelay);
    wsRetryDelay = Math.min(wsRetryDelay * 1.6, 15000);
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

function send(type, extra) {
  if (!ws || ws.readyState !== WebSocket.OPEN) { toast("Aloqa yo'q — qayta ulanmoqda..."); return; }
  ws.send(JSON.stringify(Object.assign({ type }, extra || {})));
}

function setConnBanner(show) {
  document.getElementById("connBanner").classList.toggle("show", show);
}

// ------------------------------------------------------------- toast/nav --

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

const screens = () => [...document.querySelectorAll(".screen")];
function go(id) {
  screens().forEach((s) => s.classList.toggle("active", s.id === id));
  document.querySelectorAll("[data-nav]").forEach((b) => b.classList.toggle("active", b.dataset.nav === id));
  window.scrollTo(0, 0);
}

function shareInvite() {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg && tg.switchInlineQuery) { tg.switchInlineQuery("mafia", ["groups"]); return; }
  toast("Guruhdagi bot tugmasi orqali ulashing");
}

// ---------------------------------------------------------- role catalog --
// Static reference data for the Rollar screen AND the lookup table the
// live Role/Night screens use to turn a bare role name from the server
// into an icon + description. Not game state — this never changes at runtime.

const ROLES = [
 {id:'don',apiName:'Don',fac:'mafia',name:'Don',icon:'/static/cards/thumb/don.jpg',card:'/static/cards/full/don.jpg',desc:"Mafiya yetakchisi. Mafiya a'zolarini biladi va ularni boshqaradi.",ability:"Har kecha mafiya a'zolari bilan maslahatlashadi va o'ldirish maqsadini belgilaydi. Tekshiruvchilar uchun \u201Ctoza\u201D natija ko'rinishi mumkin."},
 {id:'mafioso',apiName:'Mafioso',fac:'mafia',name:'Mafioso',icon:'/static/cards/thumb/mafioso.jpg',card:'/static/cards/full/mafioso.jpg',desc:"Mafiya a'zosi. Kechasi o'ldirishda ishtirok etadi.",ability:"Har kecha mafiya bilan birga o'ldirish maqsadini tanlaydi. Don o'lsa, uning o'rnini bosishi mumkin."},
 {id:'consigliere',apiName:'Consigliere',fac:'mafia',name:'Consigliere',icon:'/static/cards/thumb/consigliere.jpg',card:'/static/cards/full/consigliere.jpg',desc:"Mafiya a'zosi. Ma'lumot yig'ishda eng ishonchli odam.",ability:"Har kecha bitta o'yinchini tekshiradi va uning aniq rolini bilib oladi. Ma'lumot faqat mafiyaga."},
 {id:'framer',apiName:'Framer',fac:'mafia',name:'Framer',icon:'/static/cards/thumb/framer.jpg',card:'/static/cards/full/framer.jpg',desc:"Mafiya a'zosi. Aybni boshqa o'yinchiga yo'naltiradi.",ability:"Har kecha bitta o'yinchini ramkalaydi — u komissar tekshiruvida mafiyachidek ko'rinadi."},
 {id:'silencer',apiName:'Silencer',fac:'mafia',name:'Silencer',icon:'/static/cards/thumb/silencer.jpg',card:'/static/cards/full/silencer.jpg',desc:"Mafiya a'zosi. O'yinchilarning ovozini bostiradi.",ability:"Har kecha bitta o'yinchini sukutga oladi — u ertasi kuni gapira va ovoz bera olmaydi."},
 {id:'commissioner',apiName:'Commissioner',fac:'town',name:'Commissioner',icon:'/static/cards/thumb/commissioner.jpg',card:'/static/cards/full/commissioner.jpg',desc:"Tartibni saqlovchi komissar. U mafiyani to'xtatmoqchi.",ability:"Har kecha bitta o'yinchini tekshiradi: mafiya yoki tinch aholi ekanini biladi."},
 {id:'doctor',apiName:'Doctor',fac:'town',name:'Doctor',icon:'/static/cards/thumb/doctor.jpg',card:'/static/cards/full/doctor.jpg',desc:"Hayot saqlovchi doktor. U kechasi bir kishini himoya qiladi.",ability:"Har kecha bitta o'yinchini himoya qiladi. Ketma-ket ikki kecha o'zini davolay olmaydi."},
 {id:'investigator',apiName:'Investigator',fac:'town',name:'Investigator',icon:'/static/cards/thumb/investigator.jpg',card:'/static/cards/full/investigator.jpg',desc:"Tergovchi. O'yinchining rol turini aniqlaydi.",ability:"Har kecha bitta o'yinchini tekshiradi va uning rol kategoriyasini biladi (Mafiya/Shahar/Neytral)."},
 {id:'tracker',apiName:'Tracker',fac:'town',name:'Tracker',icon:'/static/cards/thumb/tracker.jpg',card:'/static/cards/full/tracker.jpg',desc:"Izquvar. O'yinchilar qayerga borganini kuzatadi.",ability:"Har kecha bitta o'yinchini tanlaydi va u kechasi kimning oldiga borganini ko'radi."},
 {id:'watcher',apiName:'Watcher',fac:'town',name:'Watcher',icon:'/static/cards/thumb/watcher.jpg',card:'/static/cards/full/watcher.jpg',desc:"Kuzatuvchi. U hammani kuzatadi, lekin aralashmaydi.",ability:"Har kecha bitta o'yinchini tanlaydi va kimlar uning oldiga kelganini ko'radi."},
 {id:'bodyguard',apiName:'Bodyguard',fac:'town',name:'Bodyguard',icon:'/static/cards/thumb/bodyguard.jpg',card:'/static/cards/full/bodyguard.jpg',desc:"Himoyachi. U doimo bir kishining hayotini qo'riqlaydi.",ability:"Har kecha bitta o'yinchini himoya qiladi. Hujumchi bilan birga halok bo'lishi mumkin."},
 {id:'mayor',apiName:'Mayor',fac:'town',name:'Mayor',icon:'/static/cards/thumb/mayor.jpg',card:'/static/cards/full/mayor.jpg',desc:"Shahar hokimi. Uning ovozi ikki baravar kuchli.",ability:"O'zini oshkor qilsa, ovoz berishda 2 baravar ovozga ega bo'ladi."},
 {id:'veteran',apiName:'Veteran',fac:'town',name:'Veteran',icon:'/static/cards/thumb/veteran.jpg',card:'/static/cards/full/veteran.jpg',desc:"Urush faxriysi. Birinchi hujumdan o'lmaydi.",ability:"Ehtiyot bo'lish rejimini yoqishi mumkin — shu kechasi kelgan barcha mehmonlarni yo'q qiladi."},
 {id:'medium',apiName:'Medium',fac:'town',name:'Medium',icon:'/static/cards/thumb/medium.jpg',card:'/static/cards/full/medium.jpg',desc:"Ruhlar bilan gaplashuvchi. O'liklarning sirlarini biladi.",ability:"O'limdan keyin bir marta o'yinda rol ochishga yordam beradi."},
 {id:'gunner',apiName:'Gunner',fac:'town',name:'Gunner',icon:'/static/cards/thumb/gunner.jpg',card:'/static/cards/full/gunner.jpg',desc:"Aniqotchi. U birinchi bo'lib o'q uzadi.",ability:"Kunduzi cheklangan miqdorda o'q otishi mumkin — o'q maqsadni o'ldiradi."},
 {id:'citizen',apiName:'Citizen',fac:'town',name:'Citizen',icon:'/static/cards/thumb/citizen.jpg',card:'/static/cards/full/citizen.jpg',desc:"Oddiy fuqaro. Lekin haqiqat uchun ovoz beradi.",ability:"Maxsus qobiliyatga ega emas. Muhokama va ovoz berish orqali g'alabaga hissa qo'shadi."},
 {id:'survivor',apiName:'Survivor',fac:'neutral',name:'Survivor',icon:'/static/cards/thumb/survivor.jpg',card:'/static/cards/full/survivor.jpg',desc:"Faqat o'z hayotini o'ylaydi.",ability:"Maxsus qobiliyatga ega emas. G'alaba — o'yin oxirigacha tirik qolish."},
 {id:'jester',apiName:'Jester',fac:'neutral',name:'Jester',icon:'/static/cards/thumb/jester.jpg',card:'/static/cards/full/jester.jpg',desc:"Kulgili, lekin yolg'iz o'ladi.",ability:"Maxsus qobiliyatga ega emas. Agar shahar uni osib qo'ysa — g'alaba qozonadi."},
 {id:'serialkiller',apiName:'Serial Killer',fac:'neutral',name:'Serial Killer',icon:'/static/cards/thumb/serialkiller.jpg',card:'/static/cards/full/serialkiller.jpg',desc:"Qotil. U faqat o'ldirishdan rohat topadi.",ability:"Har kecha bitta o'yinchini o'ldiradi. Yolg'iz harakat qiladi."},
 {id:'arsonist',apiName:'Arsonist',fac:'neutral',name:'Arsonist',icon:'/static/cards/thumb/arsonist.jpg',card:'/static/cards/full/arsonist.jpg',desc:"Yong'in tarqatuvchi. Hammani olovda yo'q qiladi.",ability:"Kechasi o'yinchilarni benzin bilan belgilaydi, keyinroq ularni bir zumda yoqishi mumkin."},
];
const FAC_LABEL = {
  uz: { mafia: "Mafia", town: "Shahar", neutral: "Neytral" },
  ru: { mafia: "Мафия", town: "Город", neutral: "Нейтральный" },
  en: { mafia: "Mafia", town: "Town", neutral: "Neutral" },
};
const roleByApiName = Object.fromEntries(ROLES.map((r) => [r.apiName, r]));

// ru/en text for each role's desc+ability, keyed by role id. Uzbek stays
// the base data embedded in ROLES above; role *names* (Don, Doctor, ...)
// are the same established Mafia-game terms in every language, so only
// desc/ability are translated here.
const ROLE_I18N = {
  don: { ru: { desc: "Лидер мафии. Знает всех членов мафии и руководит ими.", ability: "Каждую ночь советуется с мафией и выбирает цель для убийства. Может показаться «чистым» для проверяющих." }, en: { desc: "The mafia's leader. Knows every mafia member and directs them.", ability: "Consults with the mafia each night and sets the kill target. May appear \u201Cclean\u201D to investigators." } },
  mafioso: { ru: { desc: "Член мафии. Участвует в ночных убийствах.", ability: "Каждую ночь выбирает цель для убийства вместе с мафией. Может занять место Дона, если тот погибнет." }, en: { desc: "A mafia member. Takes part in the night kill.", ability: "Chooses the kill target together with the mafia each night. Can take over as Don if he dies." } },
  consigliere: { ru: { desc: "Член мафии. Самый надёжный для сбора информации.", ability: "Каждую ночь проверяет одного игрока и узнаёт его точную роль. Информация — только для мафии." }, en: { desc: "A mafia member. The most trusted for gathering information.", ability: "Investigates one player each night and learns their exact role. Info goes to the mafia only." } },
  framer: { ru: { desc: "Член мафии. Направляет подозрение на другого игрока.", ability: "Каждую ночь «подставляет» игрока — при проверке комиссаром тот будет выглядеть как мафиози." }, en: { desc: "A mafia member. Shifts suspicion onto another player.", ability: "Frames one player each night \u2014 they'll appear as mafia to the Commissioner's investigation." } },
  silencer: { ru: { desc: "Член мафии. Заглушает голос игроков.", ability: "Каждую ночь заставляет замолчать игрока — на следующий день он не может говорить и голосовать." }, en: { desc: "A mafia member. Silences players' voices.", ability: "Silences one player each night \u2014 they can't speak or vote the next day." } },
  commissioner: { ru: { desc: "Комиссар, поддерживающий порядок. Хочет остановить мафию.", ability: "Каждую ночь проверяет одного игрока: узнаёт, мафия он или мирный житель." }, en: { desc: "A commissioner keeping order. Wants to stop the mafia.", ability: "Investigates one player each night: learns whether they're mafia or a townsperson." } },
  doctor: { ru: { desc: "Доктор, спасающий жизни. Ночью защищает одного человека.", ability: "Каждую ночь защищает одного игрока. Не может лечить себя две ночи подряд." }, en: { desc: "A life-saving doctor. Protects one person each night.", ability: "Protects one player each night. Can't heal themselves two nights in a row." } },
  investigator: { ru: { desc: "Следователь. Определяет тип роли игрока.", ability: "Каждую ночь проверяет игрока и узнаёт категорию его роли (Мафия/Город/Нейтральный)." }, en: { desc: "An investigator. Determines a player's role type.", ability: "Investigates one player each night and learns their role category (Mafia/Town/Neutral)." } },
  tracker: { ru: { desc: "Следопыт. Отслеживает, куда ходят игроки.", ability: "Каждую ночь выбирает игрока и видит, к кому он приходил этой ночью." }, en: { desc: "A tracker. Watches where players go.", ability: "Chooses one player each night and sees who they visited." } },
  watcher: { ru: { desc: "Наблюдатель. Следит за всеми, но не вмешивается.", ability: "Каждую ночь выбирает игрока и видит, кто приходил к нему." }, en: { desc: "A watcher. Observes everyone but doesn't interfere.", ability: "Chooses one player each night and sees who visited them." } },
  bodyguard: { ru: { desc: "Телохранитель. Постоянно охраняет жизнь одного человека.", ability: "Каждую ночь защищает игрока. Может погибнуть вместе с нападавшим." }, en: { desc: "A bodyguard. Constantly guards one person's life.", ability: "Protects one player each night. May die together with the attacker." } },
  mayor: { ru: { desc: "Мэр города. Его голос вдвое сильнее.", ability: "Если раскроет себя, получает двойной голос при голосовании." }, en: { desc: "The town's mayor. Their vote counts double.", ability: "If they reveal themselves, their vote counts twice during voting." } },
  veteran: { ru: { desc: "Ветеран войны. Не умирает от первого нападения.", ability: "Может включить режим осторожности — уничтожает всех, кто пришёл к нему этой ночью." }, en: { desc: "A war veteran. Doesn't die from the first attack.", ability: "Can go on alert \u2014 kills everyone who visits them that night." } },
  medium: { ru: { desc: "Общается с духами. Знает секреты умерших.", ability: "После смерти один раз помогает раскрыть роль в игре." }, en: { desc: "Speaks with spirits. Knows the secrets of the dead.", ability: "After death, can help reveal a role in the game once." } },
  gunner: { ru: { desc: "Меткий стрелок. Стреляет первым.", ability: "Днём может ограниченное число раз выстрелить — выстрел убивает цель." }, en: { desc: "A sharpshooter. Shoots first.", ability: "Can fire a limited number of shots during the day \u2014 a shot kills its target." } },
  citizen: { ru: { desc: "Обычный житель. Но голосует за правду.", ability: "Не имеет особых способностей. Вносит вклад в победу через обсуждение и голосование." }, en: { desc: "An ordinary citizen. But votes for the truth.", ability: "Has no special ability. Contributes to victory through discussion and voting." } },
  survivor: { ru: { desc: "Думает только о собственной жизни.", ability: "Не имеет особых способностей. Победа — дожить до конца игры." }, en: { desc: "Only thinks about their own life.", ability: "Has no special ability. Wins by surviving to the end of the game." } },
  jester: { ru: { desc: "Забавный, но умирает в одиночестве.", ability: "Не имеет особых способностей. Побеждает, если город его повесит." }, en: { desc: "Funny, but dies alone.", ability: "Has no special ability. Wins if the town hangs them." } },
  serialkiller: { ru: { desc: "Убийца. Получает удовольствие только от убийств.", ability: "Каждую ночь убивает одного игрока. Действует в одиночку." }, en: { desc: "A killer. Only takes pleasure in killing.", ability: "Kills one player each night. Acts alone." } },
  arsonist: { ru: { desc: "Поджигатель. Уничтожает всех в огне.", ability: "Ночью обливает игроков бензином, а позже может мгновенно поджечь их всех." }, en: { desc: "Spreads fire. Destroys everyone in flames.", ability: "Douses players in gasoline at night, then can ignite them all at once later." } },
};

function roleText(r) {
  const tr = ROLE_I18N[r.id] && ROLE_I18N[r.id][currentLang];
  return tr ? tr : { desc: r.desc, ability: r.ability };
}

function renderRoles(filter) {
  const root = document.getElementById("rolesRoot");
  const facLabel = FAC_LABEL[currentLang] || FAC_LABEL.uz;
  const facs = filter === "all" ? ["mafia", "town", "neutral"] : [filter];
  root.innerHTML = facs.map((fac) => {
    const items = ROLES.filter((r) => r.fac === fac);
    return `<div class="factiontitle ${fac}">${facLabel[fac]}<span class="n">(${items.length})</span></div>
    <div class="rolegrid">${items.map((r) => `
      <div class="rolecell ${fac}" onclick="showRole('${r.id}')">
        <div class="roleicon"><img src="${r.icon}" alt=""></div>
        <div class="rolename">${r.name}</div>
      </div>`).join("")}</div>`;
  }).join("");
}
function showRole(id) {
  const r = ROLES.find((x) => x.id === id);
  const facVar = r.fac === "mafia" ? "red-hi" : r.fac === "town" ? "town-hi" : "neutral-hi";
  const facLabel = FAC_LABEL[currentLang] || FAC_LABEL.uz;
  const text = roleText(r);
  const abilityLabel = I18N[currentLang]?.role_ability_label || I18N.uz.role_ability_label;
  const el = document.getElementById("roleDetail");
  el.innerHTML = `
    <div class="roledetail-card">
      <img src="${r.card || r.icon}" alt="${r.name}">
    </div>
    <div class="roledetail-head">
      <div><div class="roledetail-name">${r.name}</div><div class="roledetail-fac" style="color:var(--${facVar})">${facLabel[r.fac]}</div></div>
    </div>
    <div class="roledetail-desc">${text.desc}</div>
    <div class="roledetail-ability"><b>${abilityLabel}</b>${text.ability}</div>`;
  el.classList.add("show");
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  document.getElementById("roleDetail").classList.remove("show");
  renderRoles(t.dataset.fac);
}));
renderRoles("all");

// -------------------------------------------------------- avatar helper --
// Real players get their Telegram photo when we have one; otherwise a
// stable initial-based placeholder so the grid never looks broken.
function avatarStyle(p) {
  if (p.avatar_url) return `background-image:url('${p.avatar_url}')`;
  const hue = Math.abs(hashStr(p.display_name)) % 360;
  return `background:linear-gradient(160deg, hsl(${hue} 45% 38%), hsl(${hue} 55% 20%));
    display:flex;align-items:center;justify-content:center;color:#f1e7d3;font:600 15px var(--ui)`;
}
function avatarInitial(p) { return (p.display_name || "?").trim().charAt(0).toUpperCase(); }
function hashStr(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i); return h; }

// -------------------------------------------------------- main render() --

function render() {
  if (!currentState) return;
  const s = currentState;
  const phase = s.phase;

  renderLobbyScreen(s);

  if (phase === "lobby") { go("lobby"); return; }

  if (phase === "role_assignment") { renderRoleScreen(s); go("role"); return; }

  if (phase === "night") {
    renderNightScreen(s);
    go("night");
    return;
  }

  if (phase === "day_discussion") {
    if (s.last_night_deaths && s.last_night_deaths.length && s.night_number !== lastShownNightDeathFor) {
      lastShownNightDeathFor = s.night_number;
      renderOutcomeScreen(s, { kind: "night" });
      go("outcome");
      return;
    }
    renderDayScreen(s);
    go("day");
    return;
  }

  if (phase === "voting") { renderVoteScreen(s); go("vote"); return; }

  if (phase === "vote_results") {
    renderOutcomeScreen(s, { kind: "vote" });
    go("outcome");
    return;
  }

  if (phase === "game_over") { renderWinScreen(s); return; }
}

// ------------------------------------------------------------- countdown --
// The server is authoritative; phase_ends_in (seconds, from the latest
// state push) just seeds a local ticker so the number moves smoothly
// between pushes instead of only updating once a second from the network.
function startCountdown(seconds, elIds) {
  clearInterval(countdownTimer);
  let remaining = Math.max(0, Math.round(seconds || 0));
  const paint = () => {
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const sec = String(remaining % 60).padStart(2, "0");
    elIds.forEach((id) => { const el = document.getElementById(id); if (el) el.textContent = `${m}:${sec}`; });
  };
  paint();
  countdownTimer = setInterval(() => { if (remaining > 0) { remaining--; paint(); } }, 1000);
}

// --------------------------------------------------------- lobby screen --

function renderLobbyScreen(s) {
  const iAmHost = myPlayerId === s.host_id;
  document.getElementById("lobbyCount").textContent = `O'YINCHILAR  ${s.players.length}/25`;
  document.getElementById("lobbyPlayers").innerHTML = s.players.map((p, i) => `
    <div class="player">
      <div class="avatar ${p.player_id === s.host_id ? "host" : ""}" style="${avatarStyle(p)}">
        ${!p.avatar_url ? avatarInitial(p) : ""}
        ${p.player_id === s.host_id ? '<svg class="icon solid crownbadge"><use href="#i-crown"/></svg>' : ""}
        <span class="badge">${i + 1}</span>
      </div>${escapeHtml(p.display_name)}
    </div>`).join("") +
    (s.players.length < 25 ? `<div class="player"><div class="avatar empty"><svg class="icon" style="width:18px;height:18px"><use href="#i-plus"/></svg></div>Bo'sh joy</div>` : "");

  const startBtn = document.getElementById("startBtn");
  if (s.phase !== "lobby") { startBtn.style.display = "none"; return; }
  startBtn.style.display = "";
  if (iAmHost) {
    startBtn.disabled = s.players.length < 6;
    startBtn.textContent = s.players.length < 6 ? `Kamida 6 kerak (${s.players.length}/6)` : "O'yinni boshlash";
    startBtn.onclick = startGame;
  } else {
    startBtn.disabled = true;
    startBtn.textContent = "Admin boshlashini kuting...";
  }
}

async function startGame() {
  send("start_game");
}

// ---------------------------------------------------------- role screen --

function renderRoleScreen(s) {
  const me = s.me || {};
  const r = roleByApiName[me.role] || null;
  const facColor = r && r.fac === "mafia" ? "var(--red-hi)" : r && r.fac === "town" ? "var(--town-hi)" : "var(--neutral-hi)";
  const hero = document.getElementById("roleHero");
  hero.style.background = "radial-gradient(circle at 50% 30%, rgba(184,40,29,.18), #0a0908 70%)";
  hero.innerHTML = `
    <div class="role-content">
      <div class="role-card-wrap" style="border-color:${facColor};box-shadow:0 0 40px ${facColor}55">
        <img src="${r ? (r.card || r.icon) : ""}" alt="${r ? r.name : ""}">
      </div>
      <div class="smallcap" style="color:${facColor};margin-top:14px">${r ? FAC_LABEL[r.fac] : ""}</div>
      <div class="role-name" style="color:${facColor}">${(me.role || "?").toUpperCase()}</div>
      <p class="subtitle role-izoh">${me.role_description || (r ? r.desc + " " + r.ability : "")}</p>
    </div>`;
}

// --------------------------------------------------------- night screen --

function renderNightScreen(s) {
  const me = s.me || {};
  startCountdown(s.phase_ends_in, ["nightTimer"]);
  document.querySelector('#night .topbar .title').textContent = `TUN — ${s.night_number}-kecha`;

  const box = document.getElementById("nightAction");
  selectedTarget = null;

  if (me.has_submitted_night_action) {
    document.getElementById("nightActionLabel").textContent = "YUBORILDI";
    box.innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Tanlovingiz qabul qilindi. Boshqalar hali harakat qilmoqda...</div>`;
    return;
  }

  if (!me.night_action_type) {
    document.getElementById("nightActionLabel").textContent = "TUNGI HARAKAT";
    box.innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Sizning rolingiz tungi harakatga ega emas. Tinch uxlang.</div>`;
    return;
  }

  document.getElementById("nightActionLabel").textContent = "TANLANG";

  if (!me.night_action_needs_target) {
    // Veteran alert / Arsonist ignite — a single confirm, no target.
    const chargesLine = me.max_charges != null
      ? `<div class="charges">${Array.from({ length: me.max_charges }).map((_, i) =>
          `<span class="${i < (me.charges_used || 0) ? "used" : "left"}"></span>`).join("")}</div>` : "";
    box.innerHTML = `
      <p class="subtitle" style="margin:0 0 12px">${nightPrompt(me.night_action_type)}</p>
      ${chargesLine}
      <button class="btn" style="margin-top:12px" onclick="confirmNightAction(null)">Tasdiqlash</button>`;
    return;
  }

  const alive = s.players.filter((p) => p.alive);
  const targets = me.can_target_self ? alive : alive.filter((p) => p.player_id !== myPlayerId);
  box.innerHTML = `
    <p class="subtitle" style="margin:0 0 12px;text-align:left">${nightPrompt(me.night_action_type)}</p>
    <div class="list" id="nightTargetList">
      ${targets.map((p) => `
        <div class="row" data-pid="${p.player_id}" onclick="selectNightTarget(this)">
          <div class="avatar" style="width:36px;height:36px;margin:0;${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
          <span class="rowname">${escapeHtml(p.display_name)}</span>
          <span class="radio"></span>
        </div>`).join("")}
    </div>
    <button class="btn" style="margin-top:14px" id="nightConfirmBtn" disabled onclick="confirmNightAction(selectedTarget)">Tanlashni tasdiqlash</button>`;
}

function nightPrompt(actionType) {
  const prompts = {
    kill: "Kimni yo'q qilasiz?", protect: "Kimni himoya qilasiz?", guard: "Kimni qo'riqlaysiz?",
    investigate: "Kimni tekshirasiz?", frame: "Kimni ramkalaysiz?", silence: "Kimni sukutga olasiz?",
    track: "Kimni kuzatasiz?", watch: "Kimning oldiga kim kelishini ko'rmoqchisiz?",
    alert: "Bu kecha ehtiyot bo'lish rejimini yoqasizmi?", douse: "Kimni benzin bilan belgilaysiz?",
    ignite: "Belgilangan barcha o'yinchilarni yoqasizmi?", seance: "Kim bilan seans o'tkazasiz?",
  };
  return prompts[actionType] || "Harakatingizni tanlang";
}

function selectNightTarget(el) {
  document.querySelectorAll("#nightTargetList .row").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  selectedTarget = el.dataset.pid;
  const btn = document.getElementById("nightConfirmBtn");
  if (btn) btn.disabled = false;
}

function confirmNightAction(targetId) {
  send("night_action", { target_id: targetId });
}

// ----------------------------------------------------------- day screen --

function renderDayScreen(s) {
  document.querySelector('#day .topbar .title').textContent = `KUN ${s.day_number}`;
  startCountdown(s.phase_ends_in, ["dayTimer"]);
  document.getElementById("dayPlayers").innerHTML = s.players.map((p, i) => `
    <div class="player" style="${p.alive ? "" : "opacity:.4"}">
      <div class="avatar ${p.player_id === s.host_id ? "host" : ""}" style="${avatarStyle(p)}">
        ${!p.avatar_url ? avatarInitial(p) : ""}
        <span class="badge">${i + 1}</span>
      </div>${escapeHtml(p.display_name)}
    </div>`).join("");
  renderDayAction(s);
  renderChat(s);
}

async function advanceToVoting() {
  send("advance_to_voting");
}

// ------------------------------------------------- day action (role) ----
// Mayor's reveal and Gunner's shoot are the only two day actions the game
// has — every other role's ability is a night action already handled
// generically by renderNightScreen. Same principle here: driven entirely
// by what the server says in me.day_action_type, never hardcoded per role.

function renderDayAction(s) {
  const box = document.getElementById("dayAction");
  const me = s.me || {};
  if (!me.alive || !me.day_action_type) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  box.style.display = "";

  if (me.day_action_type === "reveal") {
    if (me.mayor_revealed) {
      box.innerHTML = `
        <div class="smallcap" style="color:var(--gold-hi)">MER OSHKOR QILINDI</div>
        <p class="subtitle" style="margin:6px 0 0">Ovozingiz endi 3 baravar kuchli.</p>`;
    } else {
      box.innerHTML = `
        <div class="smallcap">MER SIFATIDA OSHKOR BO'LISH</div>
        <p class="subtitle" style="margin:6px 0 12px">Oshkor bo'lsangiz, ovozingiz 3 baravar kuchli bo'ladi. Buni ortga qaytarib bo'lmaydi.</p>
        <button class="btn gold" onclick="revealMayor()">O'zini oshkor qilish</button>`;
    }
    return;
  }

  if (me.day_action_type === "shoot") {
    const used = me.charges_used || 0;
    const max = me.max_charges || 0;
    const chargesLine = `<div class="charges">${Array.from({ length: max }).map((_, i) =>
      `<span class="${i < used ? "used" : "left"}"></span>`).join("")}</div>`;
    if (used >= max) {
      box.innerHTML = `
        <div class="smallcap">O'Q OTISH</div>
        ${chargesLine}
        <p class="subtitle" style="margin:8px 0 0">O'qlaringiz tugadi.</p>`;
      return;
    }
    const alive = s.players.filter((p) => p.alive && p.player_id !== myPlayerId);
    box.innerHTML = `
      <div class="smallcap">O'Q OTISH</div>
      ${chargesLine}
      <p class="subtitle" style="margin:8px 0 12px;text-align:left">Kimni otasiz?</p>
      <div class="list" id="gunnerTargetList">
        ${alive.map((p) => `
          <div class="row" data-pid="${p.player_id}" onclick="selectGunnerTarget(this)">
            <div class="avatar" style="width:36px;height:36px;margin:0;${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
            <span class="rowname">${escapeHtml(p.display_name)}</span>
            <span class="radio"></span>
          </div>`).join("")}
      </div>
      <button class="btn" style="margin-top:14px" id="gunnerConfirmBtn" disabled onclick="confirmGunnerShoot(selectedGunnerTarget)">Otishni tasdiqlash</button>`;
    return;
  }
}

function revealMayor() {
  send("reveal_mayor");
}

let selectedGunnerTarget = null;
function selectGunnerTarget(el) {
  document.querySelectorAll("#gunnerTargetList .row").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  selectedGunnerTarget = el.dataset.pid;
  const btn = document.getElementById("gunnerConfirmBtn");
  if (btn) btn.disabled = false;
}

function confirmGunnerShoot(targetId) {
  if (!targetId) return;
  send("gunner_shoot", { target_id: targetId });
  selectedGunnerTarget = null;
}

// -------------------------------------------------- discussion chat -----
// Spec sections 11 & 32: discussion happens ONLY here, inside the WebApp —
// never in the Telegram group. Server is authoritative on every rule
// (alive-only, silenced-block, phase-gated); this just renders what the
// last state push already told us and forwards what the player types.

let lastChatLen = -1;

function renderChat(s) {
  const me = s.me || {};
  const log = document.getElementById("chatLog");
  const chat = s.chat || [];

  if (chat.length === 0) {
    log.innerHTML = `<div class="chatempty">Hali xabar yo'q. Muhokamani boshlang.</div>`;
  } else {
    log.innerHTML = chat.map((m) => {
      const sender = s.players.find((p) => p.player_id === m.player_id);
      const isDead = sender && !sender.alive;
      const isMe = m.player_id === myPlayerId;
      return `<div class="chatmsg ${isMe ? "me" : ""} ${isDead ? "dead" : ""}">
        <div class="chatname">${escapeHtml(m.display_name)}${isDead ? " †" : ""}</div>
        <div class="chattext">${escapeHtml(m.text)}</div>
      </div>`;
    }).join("");
  }
  if (chat.length !== lastChatLen) {
    log.scrollTop = log.scrollHeight;
    lastChatLen = chat.length;
  }

  const inputArea = document.getElementById("chatInputArea");
  if (me.can_chat) {
    inputArea.innerHTML = `
      <div class="chatinputrow">
        <input class="chatinput" id="chatInput" maxlength="500" placeholder="Xabar yozing..."
          onkeydown="if(event.key==='Enter')sendChatMessage()">
        <button class="chatsend" onclick="sendChatMessage()"><svg class="icon" style="width:17px;height:17px;stroke:#fff"><use href="#i-send"/></svg></button>
      </div>`;
  } else if (!me.alive) {
    inputArea.innerHTML = `<div class="chatspectate">Siz kuzatuvchisiz — spectator sifatida ko'rasiz, yoza olmaysiz</div>`;
  } else {
    inputArea.innerHTML = `<div class="chatspectate">Bugun sukut qilingansiz — xabar yubora olmaysiz</div>`;
  }
}

function sendChatMessage() {
  const input = document.getElementById("chatInput");
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  send("chat_message", { text });
  input.value = "";
}

// ---------------------------------------------------------- vote screen --

function renderVoteScreen(s) {
  document.getElementById("voteDayLabel").textContent = `KUN ${s.day_number}`;
  startCountdown(s.phase_ends_in, ["voteTimer"]);
  const me = s.me || {};
  selectedTarget = null;
  const alive = s.players.filter((p) => p.alive);

  if (me.has_voted) {
    document.getElementById("voteList").innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Ovozingiz qabul qilindi. Boshqalarni kutmoqda...</div>`;
    document.getElementById("voteBtn").style.display = "none";
    return;
  }
  document.getElementById("voteBtn").style.display = "";
  document.getElementById("voteBtn").disabled = true;

  document.getElementById("voteList").innerHTML = alive.map((p) => `
    <div class="row" data-pid="${p.player_id}" onclick="selectVoteTarget(this)">
      <div class="avatar" style="width:36px;height:36px;margin:0;${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
      <span class="rowname">${escapeHtml(p.display_name)}${p.player_id === myPlayerId ? " (siz)" : ""}</span>
      ${p.player_id === s.host_id ? '<svg class="icon" style="width:14px;height:14px;color:var(--gold)"><use href="#i-crown"/></svg>' : ""}
      <span class="radio"></span>
    </div>`).join("");
}

function selectVoteTarget(el) {
  document.querySelectorAll("#voteList .row").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  selectedTarget = el.dataset.pid;
  document.getElementById("voteBtn").disabled = false;
}

function submitVote() {
  if (!selectedTarget) return;
  send("vote", { target_id: selectedTarget });
}

// ------------------------------------------------------- outcome screen --

function nameFor(s, playerId) {
  const p = s.players.find((x) => x.player_id === playerId);
  return p ? p.display_name : "Noma'lum";
}
const DEATH_REASON_UZ = {
  mafia: "mafiya tomonidan o'ldirildi", serial_killer: "seriyali qotil tomonidan o'ldirildi",
  arsonist: "yong'inda halok bo'ldi", veteran_alert: "faxriyga hujum qilib halok bo'ldi",
  bodyguard_intercept: "himoyachi bilan birga halok bo'ldi", gunner: "otib o'ldirildi",
  day_vote: "shahar tomonidan osib qo'yildi",
};

function renderOutcomeScreen(s, opts) {
  const heroEl = document.getElementById("outcomeHero");
  const extraEl = document.getElementById("outcomeExtra");
  const titleEl = document.getElementById("outcomeTitle");
  const introEl = document.getElementById("outcomeIntro");
  const continueBtn = document.getElementById("outcomeContinueBtn");
  extraEl.innerHTML = "";

  if (opts.kind === "night") {
    const deaths = s.last_night_deaths || [];
    titleEl.textContent = "TUN NATIJASI";
    introEl.textContent = deaths.length ? "Shahar kimnidir yo'qotdi..." : "Bu kecha hech kim o'lmadi.";
    if (deaths.length === 0) {
      heroEl.style.backgroundImage = "";
      heroEl.style.aspectRatio = "auto";
      heroEl.innerHTML = `<div class="card" style="text-align:center;padding:28px">Hammasi tinch o'tdi.</div>`;
    } else {
      const first = deaths[0];
      heroEl.style.backgroundImage = "url('data:image/jpeg;base64,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')";
      heroEl.style.aspectRatio = "";
      heroEl.innerHTML = `<div class="death-content"><div class="big-name">${escapeHtml(nameFor(s, first.player_id))}</div>
        <div class="subtitle" style="color:var(--red-hi);font-weight:700;letter-spacing:.06em">O'LDIRILDI</div></div>`;
      if (deaths.length > 1) {
        extraEl.innerHTML = `<div class="card" style="margin-top:14px">` +
          deaths.slice(1).map((d) => `<div class="deathrow"><b>${escapeHtml(nameFor(s, d.player_id))}</b> — ${DEATH_REASON_UZ[d.reason] || d.reason}</div>`).join("") +
          `</div>`;
      }
    }
    continueBtn.onclick = () => { go("day"); };
    continueBtn.textContent = "Davom etish";
    return;
  }

  // day-vote outcome
  const result = s.last_vote_result;
  titleEl.textContent = "OVOZ NATIJASI";
  heroEl.style.aspectRatio = "";
  if (!result || !result.eliminated) {
    introEl.textContent = "Ovozlar taqsimlandi — hech kim osilmadi.";
    heroEl.style.backgroundImage = "";
    heroEl.innerHTML = `<div class="card" style="text-align:center;padding:28px">Shahar qaror qila olmadi.</div>`;
  } else {
    introEl.textContent = "Shahar hukmini chiqardi.";
    heroEl.style.backgroundImage = "url('data:image/jpeg;base64,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')";
    heroEl.innerHTML = `<div class="death-content"><div class="big-name">${escapeHtml(nameFor(s, result.eliminated))}</div>
      <div class="subtitle" style="color:var(--red-hi);font-weight:700;letter-spacing:.06em">OSIB QO'YILDI</div></div>`;
  }
  continueBtn.textContent = "Keyingi tunga o'tish";
  continueBtn.onclick = () => { send("start_next_night"); };
}

function dismissOutcome() {
  // Fallback for the generic button binding; renderOutcomeScreen always
  // overrides onclick with the correct behavior for what's on screen.
  go("day");
}

// ------------------------------------------------------------ win screen --

function renderWinScreen(s) {
  const w = s.winner || {};
  const winners = (w.winners || []).map((pid) => nameFor(s, pid)).filter(Boolean);
  const list = winners.length ? winners.join(", ") : "";
  const targetScreen = w.faction === "town" ? "town_win" : "mafia_win";

  if (w.faction === "town") {
    document.getElementById("winNotice").textContent = "Barcha mafiya yo'q qilindi. Shahar tinch." + (list ? ` G'oliblar: ${list}.` : "");
  } else if (w.faction === "mafia") {
    document.getElementById("winNoticeM").textContent = "Shahar mafiyaning qo'liga o'tdi." + (list ? ` G'oliblar: ${list}.` : "");
  } else {
    // Neutral win (Survivor / Jester / Serial Killer / Arsonist) — no
    // unique art yet, so we reuse the mafia_win shell recolored purple.
    const box = document.querySelector("#mafia_win .win");
    box.classList.add("red");
    document.getElementById("winTitleM").textContent = "G'ALABA";
    document.getElementById("winTitleM").style.color = "var(--neutral-hi)";
    document.getElementById("winSubtitleM").style.color = "var(--neutral-hi)";
    document.getElementById("winSubtitleM").textContent = "MUSTAQIL G'OLIB!";
    document.getElementById("winIconM").style.color = "var(--neutral-hi)";
    document.getElementById("winNoticeM").textContent = (w.reason || "") + (list ? ` G'olib: ${list}.` : "");
  }

  renderFinalStats(s, targetScreen === "town_win" ? "myStats" : "myStatsM");
  renderFinalRoster(s, targetScreen === "town_win" ? "finalRoster" : "finalRosterM");
  go(targetScreen);
}

function renderFinalStats(s, elId) {
  const st = (s.me && s.me.stats) || {};
  const rows = [
    [st.won ? "G'ALABA" : "MAG'LUBIYAT", "NATIJA"],
    [st.role || "—", "ROLINGIZ"],
    [st.kills != null ? st.kills : 0, "O'LDIRISH"],
    [st.investigations != null ? st.investigations : 0, "TEKSHIRUV"],
    [st.protections != null ? st.protections : 0, "HIMOYA"],
    [st.votes_cast != null ? st.votes_cast : 0, "OVOZ"],
  ];
  document.getElementById(elId).innerHTML = rows.map(([val, label]) =>
    `<div class="statbox"><b>${escapeHtml(String(val))}</b><span>${label}</span></div>`).join("");
}

function renderFinalRoster(s, elId) {
  document.getElementById(elId).innerHTML = s.players.map((p) => {
    const r = roleByApiName[p.role];
    const facColor = r ? (r.fac === "mafia" ? "var(--red-hi)" : r.fac === "town" ? "var(--town-hi)" : "var(--neutral-hi)") : "var(--muted)";
    return `<div class="rosterrow">
      <div class="avatar" style="${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
      <span class="rname">${escapeHtml(p.display_name)}${!p.alive ? " †" : ""}</span>
      <span class="smallcap" style="color:${facColor}">${p.role || "?"}</span>
    </div>`;
  }).join("");
}

// ------------------------------------------------------------- utilities --

function escapeHtml(str) {
  return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ----------------------------------------------------------- admin panel --
// Bot-owner-only (settings.admin_telegram_ids on the backend), and
// deliberately independent of currentState/ws — the owner can see and
// manage every active match across every Telegram group without ever
// having joined any of them as a player. Driven entirely by REST calls
// to /admin/*, not the per-game WebSocket this file otherwise uses.

let isBotAdmin = false;
let adminGamesList = [];
let adminStats = null;
let adminSelectedGameId = null;
let adminSelectedGameDetail = null;

const PHASE_LABEL_UZ = {
  lobby: "Lobbi", role_assignment: "Rol taqsimoti", night: "Tun",
  day_discussion: "Kunduz — muhokama", voting: "Ovoz berish",
  vote_results: "Ovoz natijasi", game_over: "O'yin tugadi",
};

function updateAdminNavVisibility() {
  document.getElementById("adminNavBtn").style.display = isBotAdmin ? "" : "none";
}

function openAdminPanel() {
  go("admin");
  loadAdminStats();
  loadAdminGamesList();
}

async function loadAdminStats() {
  try {
    adminStats = await api("/admin/stats");
  } catch (e) {
    adminStats = null;
  }
  renderAdminScreen();
}

async function loadAdminGamesList() {
  try {
    const res = await api("/admin/games");
    adminGamesList = res.games;
  } catch (e) {
    adminGamesList = [];
    toast(e.message);
  }
  renderAdminScreen();
}

async function adminOpenGame(gameId) {
  try {
    adminSelectedGameDetail = await api(`/admin/games/${gameId}`);
    adminSelectedGameId = gameId;
  } catch (e) {
    toast(e.message);
    adminSelectedGameId = null;
    adminSelectedGameDetail = null;
  }
  renderAdminScreen();
}

function adminBackToGamesList() {
  adminSelectedGameId = null;
  adminSelectedGameDetail = null;
  renderAdminScreen();
  loadAdminGamesList();
}

function renderAdminScreen() {
  if (adminSelectedGameId && adminSelectedGameDetail) {
    renderAdminGameDetail(adminSelectedGameDetail);
  } else {
    renderAdminGamesList();
  }
}

function renderAdminGamesList() {
  document.getElementById("adminStatus").innerHTML = adminStats ? `
    <div class="smallcap">UMUMIY STATISTIKA</div>
    <div class="statsgrid" style="margin-top:10px">
      <div class="statbox"><b>${adminStats.active_games}</b><span>Faol o'yinlar</span></div>
      <div class="statbox"><b>${adminStats.total_finished_games}</b><span>Tugagan o'yinlar</span></div>
      <div class="statbox"><b>${adminStats.total_users}</b><span>Foydalanuvchilar</span></div>
    </div>` : `<div class="waitnote"><span class="dotpulse"></span>Yuklanmoqda...</div>`;

  document.getElementById("adminSettings").style.display = "none";
  document.getElementById("adminSettings").innerHTML = "";

  document.getElementById("adminPlayers").innerHTML = `
    <div class="smallcap">FAOL O'YINLAR (${adminGamesList.length})</div>
    <div class="list" style="margin-top:10px">
      ${adminGamesList.length ? adminGamesList.map((g) => `
        <div class="row" style="cursor:pointer" onclick="adminOpenGame('${g.game_id}')">
          <span class="rowname">${escapeHtml(g.chat_id || g.game_id)}<br>
            <span style="color:var(--muted);font-size:12px">${PHASE_LABEL_UZ[g.phase] || g.phase} · admin: ${escapeHtml(g.host_display_name || "?")}</span></span>
          <span class="rowvotes">${g.alive_count}/${g.player_count}</span>
        </div>`).join("") : `<div class="waitnote">Hozircha faol o'yin yo'q</div>`}
    </div>`;
}

function renderAdminGameDetail(g) {
  document.getElementById("adminStatus").innerHTML = `
    <button class="btn ghost" style="margin-bottom:14px" onclick="adminBackToGamesList()">← Barcha o'yinlar</button>
    <div class="smallcap">${escapeHtml(g.chat_id || g.game_id)}</div>
    <div class="title" style="margin-top:8px;font-size:17px">${PHASE_LABEL_UZ[g.phase] || g.phase}</div>
    <div class="stack" style="margin-top:14px">
      <button class="btn dark" onclick="adminForceAdvance('${g.game_id}')">Keyingi bosqichga o'tkazish</button>
      <button class="btn ghost" onclick="adminExtendTimer('${g.game_id}')">+30 soniya qo'shish</button>
      <button class="btn ghost" onclick="adminTerminateGame('${g.game_id}')">O'yinni butunlay tugatish</button>
    </div>`;

  const settingsEl = document.getElementById("adminSettings");
  if (g.phase === "lobby") {
    settingsEl.style.display = "";
    const st = g.settings;
    settingsEl.innerHTML = `
      <div class="smallcap">O'YIN SOZLAMALARI</div>
      <div class="adminfield"><label>Tungi vaqt (soniya)</label>
        <input class="admininput" type="number" id="setNight" value="${st.night_duration_s}" min="10" max="300"></div>
      <div class="adminfield"><label>Kunduzgi muhokama vaqti (soniya)</label>
        <input class="admininput" type="number" id="setDay" value="${st.day_duration_s}" min="30" max="600"></div>
      <div class="adminfield"><label>Ovoz berish vaqti (soniya)</label>
        <input class="admininput" type="number" id="setVote" value="${st.voting_duration_s}" min="15" max="300"></div>
      <div class="adminfield"><label>Durang bo'lsa</label>
        <select class="adminselect" id="setTie">
          <option value="no_elimination" ${st.tie_rule === "no_elimination" ? "selected" : ""}>Hech kim chiqarilmaydi</option>
          <option value="revote" ${st.tie_rule === "revote" ? "selected" : ""}>Qayta ovoz berish</option>
          <option value="random" ${st.tie_rule === "random" ? "selected" : ""}>Tasodifiy tanlanadi</option>
        </select></div>
      <label class="admincheck"><input type="checkbox" id="setSelfVote" ${st.allow_self_vote ? "checked" : ""}> O'ziga ovoz berishga ruxsat</label>
      <label class="admincheck"><input type="checkbox" id="setRevealDeath" ${st.reveal_role_on_death ? "checked" : ""}> O'lgan o'yinchining roli ko'rinsin</label>
      <label class="admincheck"><input type="checkbox" id="setAnonVote" ${st.anonymous_voting ? "checked" : ""}> Ovozlar anonim bo'lsin</label>
      <button class="btn gold" style="margin-top:16px" onclick="adminSaveSettings('${g.game_id}')">Sozlamalarni saqlash</button>`;
  } else {
    settingsEl.style.display = "none";
    settingsEl.innerHTML = "";
  }

  document.getElementById("adminPlayers").innerHTML = `
    <div class="smallcap">O'YINCHILAR (${g.players.length})</div>
    <div class="list" style="margin-top:10px">
      ${g.players.map((p) => `
        <div class="row">
          <span class="rowname">${escapeHtml(p.display_name)}${p.is_host ? " 👑" : ""}${!p.alive ? " †" : ""}</span>
          <span class="smallcap" style="color:var(--muted);text-transform:none;font-weight:400">${escapeHtml(p.role || "?")}</span>
          <button class="btn ghost" style="width:auto;min-height:32px;padding:0 12px" onclick="adminRemovePlayer('${g.game_id}','${p.player_id}')">Chiqarish</button>
        </div>`).join("")}
    </div>`;
}

async function adminForceAdvance(gameId) {
  try {
    await api(`/admin/games/${gameId}/force-advance`, { method: "POST" });
    toast("Bosqich o'tkazildi");
    await adminOpenGame(gameId);
  } catch (e) { toast(e.message); }
}

async function adminExtendTimer(gameId) {
  try {
    await api(`/admin/games/${gameId}/extend-timer`, { method: "POST", body: JSON.stringify({ seconds: 30 }) });
    toast("+30 soniya qo'shildi");
    await adminOpenGame(gameId);
  } catch (e) { toast(e.message); }
}

async function adminTerminateGame(gameId) {
  try {
    await api(`/admin/games/${gameId}/terminate`, { method: "POST" });
    toast("O'yin tugatildi");
    adminBackToGamesList();
  } catch (e) { toast(e.message); }
}

async function adminRemovePlayer(gameId, targetId) {
  try {
    await api(`/admin/games/${gameId}/remove/${targetId}`, { method: "POST" });
    toast("O'yinchi olib tashlandi");
    await adminOpenGame(gameId);
  } catch (e) { toast(e.message); }
}

async function adminSaveSettings(gameId) {
  const settings = {
    night_duration_s: parseInt(document.getElementById("setNight").value, 10),
    day_duration_s: parseInt(document.getElementById("setDay").value, 10),
    voting_duration_s: parseInt(document.getElementById("setVote").value, 10),
    tie_rule: document.getElementById("setTie").value,
    allow_self_vote: document.getElementById("setSelfVote").checked,
    reveal_role_on_death: document.getElementById("setRevealDeath").checked,
    anonymous_voting: document.getElementById("setAnonVote").checked,
  };
  try {
    await api(`/admin/games/${gameId}/settings`, { method: "POST", body: JSON.stringify({ settings }) });
    toast("Sozlamalar saqlandi");
    await adminOpenGame(gameId);
  } catch (e) { toast(e.message); }
}
