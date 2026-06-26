// Sidebar + Topbar HTML generators

function renderSidebar(role, current) {
  const adminItems = [
    { id: "dashboard",     label: "Dashboard",         icon: "dashboard" },
    { id: "patients-list", label: "Patients",           icon: "user"      },
    { id: "queue",         label: "Patient Queue",      icon: "queue"     },
    { id: "reports",       label: "Reports",            icon: "report"    },
  ];
  const doctorItems = [
    { id: "my-queue",  label: "My Queue",        icon: "queue"    },
  ];
  const items = role === "doctor" ? doctorItems : adminItems;
  const sectionLabel = role === "doctor" ? "Clinician" : "Workflows";
  return `
    <div class="sidebar-backdrop" id="sidebar-backdrop"></div>
    <aside class="sidebar" id="main-sidebar">
      <div class="brand">
        <div class="logo">Foqal</div>
        <div class="name">Foqal AI<small>Discharge Summary · Cardiology</small></div>
      </div>
      <nav>
        <div class="nav-section">${sectionLabel}</div>
        ${items.map(it => `
          <div class="nav-item ${current === it.id ? "active" : ""}" data-nav="${it.id}">
            ${iconSVG(it.icon, 16)}
            <span>${it.label}</span>
          </div>
        `).join("")}
      </nav>
      <div class="footer">
        <div class="pill"><span class="ldot"></span>SYSTEM HEALTHY</div>
        <div style="margin-top:8px">Foqal AI · NABH v1.0</div>
      </div>
    </aside>`;
}

function renderTopbar(opts) {
  const { crumbs = [], user = {}, extra = "" } = opts;
  const crumbHTML = crumbs.length ? `<div class="crumbs">${crumbs.map((c, i) => {
    const label = typeof c === "object" ? c.label : c;
    const onclick = typeof c === "object" && c.onclick ? ` onclick="${c.onclick}" style="cursor:pointer;color:var(--brand)"` : "";
    return i === crumbs.length - 1
      ? `<strong>${label}</strong>`
      : `<span${onclick}>${label}</span><span style="display:inline-flex;align-items:center;">${iconSVG("chevR", 12)}</span>`;
  }).join("")}</div>` : "";
  const displayName     = user.full_name || user.name || "";
  const displayEmail    = user.email || user.hospital_email || "";
  const displayInitials = user.initials
    || (displayName ? displayName.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase() : "?");
  return `
    <header class="topbar">
      <button class="hamburger" id="topbar-hamburger" aria-label="Open menu">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect y="3" width="18" height="2" rx="1" fill="currentColor"/>
          <rect y="8" width="18" height="2" rx="1" fill="currentColor"/>
          <rect y="13" width="18" height="2" rx="1" fill="currentColor"/>
        </svg>
      </button>
      ${crumbHTML}
      <div class="spacer"></div>
      ${extra}
      <div class="user">
        <div class="meta">
          <div class="n">${displayName}</div>
          <div class="r">${displayEmail || user.role || ""}</div>
        </div>
        <button class="iconbtn" id="topbar-logout" title="Sign out" style="margin-left:8px">
          ${iconSVG("logout", 15)}
        </button>
      </div>
    </header>`;
}

function setupShellListeners() {
  const hamburger = document.getElementById("topbar-hamburger");
  const sidebar   = document.getElementById("main-sidebar");
  const backdrop  = document.getElementById("sidebar-backdrop");
  if (!hamburger || !sidebar) return;

  const open  = () => { sidebar.classList.add("open"); backdrop.classList.add("open"); };
  const close = () => { sidebar.classList.remove("open"); backdrop.classList.remove("open"); };

  hamburger.addEventListener("click", () => sidebar.classList.contains("open") ? close() : open());
  backdrop.addEventListener("click", close);

  // Close sidebar on nav item click (mobile)
  sidebar.querySelectorAll(".nav-item").forEach(el => el.addEventListener("click", close));
}

window.renderSidebar      = renderSidebar;
window.renderTopbar       = renderTopbar;
window.setupShellListeners = setupShellListeners;
