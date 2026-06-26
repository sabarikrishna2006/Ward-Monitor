// Global application state + re-render engine

const ADMIN_USER  = { name: "Sneha Nair",   role: "Admin Staff",  initials: "SN" };
const DOCTOR_USER = { name: "Dr. A. Mehta", role: "Cardiologist", initials: "AM" };

// Detect reset-password link on page load
const _urlParams = new URLSearchParams(window.location.search);
const _initialScreen = (_urlParams.get("reset_token") && _urlParams.get("email")) ? "reset-password" : "login";

const APP = {
  screen: _initialScreen,
  role: null,
  currentUser: null,
  claims: null,
  hovered: null,
  editingClaim: null,
  showSignOff: false,
  counts: { total: 148, red: 3, corrected: 0, rejected: 0 },
  adminEncounters: null,
  selectedPatientHadmId: null,
};

function getUser() {
  if (APP.currentUser) return APP.currentUser;
  return APP.role === "doctor" ? DOCTOR_USER : ADMIN_USER;
}

// One central re-render.
// Partial update: keeps .sidebar and .main containers in the DOM and only
// swaps their innerHTML — the shell never disappears so there is no flash.
// Falls back to full root.innerHTML replace for login / first render.
let _rafPending = false;

function _applyRender(html) {
  const root     = document.getElementById("root");
  if (!root) return;
  const oldMain    = root.querySelector(".main");
  const oldSidebar = root.querySelector(".sidebar");
  if (oldMain && oldSidebar) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    const newMain    = tmp.querySelector(".main");
    const newSidebar = tmp.querySelector(".sidebar");
    if (newMain && newSidebar) {
      oldSidebar.innerHTML = newSidebar.innerHTML;
      oldMain.innerHTML    = newMain.innerHTML;
      attachSharedListeners();
      if (typeof setupShellListeners === "function") setupShellListeners();
      const setup = SCREEN_SETUP[APP.screen];
      if (setup) setup();
      return;
    }
  }
  // Login screen or first load — full replace
  root.innerHTML = html;
  attachSharedListeners();
  if (typeof setupShellListeners === "function") setupShellListeners();
  const setup = SCREEN_SETUP[APP.screen];
  if (setup) setup();
}

function renderApp() {
  if (_rafPending) return;
  _rafPending = true;
  requestAnimationFrame(() => {
    _rafPending = false;
    const fn = SCREEN_RENDERERS[APP.screen];
    _applyRender(fn ? fn() : (SCREEN_RENDERERS["login"] || (() => ""))());
  });
}

function navigate(screen) {
  APP.prevScreen = APP.screen;
  // When leaving existing-encounter, clear the loading flag so spinner stops in patients directory
  if (APP.screen === "existing-encounter") {
    const _id = typeof _ee !== "undefined" ? parseInt((_ee.query || "").replace(/\D/g, ""), 10) : 0;
    if (_id && typeof patCacheGet === "function") {
      const _cached = patCacheGet(_id);
      if (_cached && _cached.loading) patCachePut(_id, { ..._cached, loading: false });
    }
  }
  if (screen === "admin-dashboard"  && typeof dashInvalidate === "function") dashInvalidate();
  if (screen === "doctor-dashboard" && typeof ddInvalidate   === "function") ddInvalidate();
  if (screen === "admin-queue"      && typeof aqInvalidate   === "function") aqInvalidate();
  if (screen === "doctor-queue"     && typeof dqInvalidate   === "function") dqInvalidate();
  if (screen === "patients-list"    && typeof patInvalidate  === "function") patInvalidate();
  APP.screen = screen;
  renderApp();
}

// Registry filled in by each screen file
const SCREEN_RENDERERS = {};
const SCREEN_SETUP = {};

// ── Shared listeners (sidebar nav + topbar logout) ───────────────────────────
function attachSharedListeners() {
  // Sidebar nav items
  document.querySelectorAll("[data-nav]").forEach(el => {
    el.addEventListener("click", () => {
      const id = el.dataset.nav;
      if (APP.role === "admin") {
        const map = {
          dashboard: "admin-dashboard",
          ingest: "ingest",
          "patients-list": "patients-list",
          queue: "admin-queue",
          reports: "reports",
          settings: "settings"
        };
        if (map[id]) navigate(map[id]);
      } else {
        const map = {
          "my-queue": "doctor-dashboard",
          settings: "settings",
          signed: "signed"
        };
        if (map[id]) navigate(map[id]);
      }
    });
  });

  // Topbar logout
  const logoutBtn = document.getElementById("topbar-logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      sessionStorage.clear();
      window.location.href = '/';
    });
  }
}

window.APP = APP;
window.getUser = getUser;
window.renderApp = renderApp;
window.navigate = navigate;
window.SCREEN_RENDERERS = SCREEN_RENDERERS;
window.SCREEN_SETUP = SCREEN_SETUP;
window.ADMIN_USER = ADMIN_USER;
window.DOCTOR_USER = DOCTOR_USER;
