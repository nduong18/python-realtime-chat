const socket = io();

// username input may be missing for logged-in users; fallback to dataset.currentUser
const usernameInput = document.getElementById("username") || {
  value: document.body.dataset.currentUser || "",
};
// room/join controls may be omitted when user is logged-in; guard them
const roomInput = document.getElementById("room") || { value: "main" };
const joinBtn = document.getElementById("joinBtn");
const leaveBtn = document.getElementById("leaveBtn");
const messagesDiv = document.getElementById("messages");
const chatForm = document.getElementById("chatForm");
const msgInput = document.getElementById("msgInput");

let joined = false;

// allow templates to inject a room/partner via body data attributes
const injectedRoom = document.body.dataset.room || "";
const injectedPartner = document.body.dataset.partner || "";
const sidebar = document.getElementById("sidebar");
// handle any collapse controls (topbar + sidebar header)
const collapseControls = Array.from(
  document.querySelectorAll(".collapse-control")
);

// persisted collapsed state key
const SIDEBAR_COLLAPSED_KEY = "sidebar.collapsed";

function applyCollapsedState() {
  const collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
  // authoritative: set both body and sidebar classes to the same state
  if (!sidebar) {
    // still set body class so other code can read it
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    return;
  }
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  sidebar.classList.toggle("collapsed", collapsed);
}

if (collapseControls && collapseControls.length) {
  collapseControls.forEach((ctrl) => {
    try {
      ctrl.style.cursor = "pointer";
      ctrl.addEventListener("click", () => {
        const collapsed =
          localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, (!collapsed).toString());
        applyCollapsedState();
      });
    } catch (e) {
      // ignore
    }
  });
}

let lastPresence = [];
function renderSidebar(friends) {
  const body = document.getElementById("sidebar-body");
  if (!body) return;
  // keep collapsed state on the sidebar element
  const wasCollapsed = sidebar && sidebar.classList.contains("collapsed");
  body.innerHTML = "";
  friends.forEach((f) => {
    const el = document.createElement("div");
    el.className = "friend-item";
    el.dataset.room = f.room;
    const isOnline = lastPresence && lastPresence.indexOf(f.username) !== -1;
    el.innerHTML = `<div class="friend-name">${f.username}</div>
      <div style="margin-left:auto; display:flex; align-items:center; gap:8px">
        <div class="presence-dot ${isOnline ? "online" : "offline"}" title="${
      isOnline ? "Online" : "Offline"
    }"></div>
        <div class="friend-last">${f.last ? f.last.msg.slice(0, 40) : ""}</div>
      </div>`;
    el.addEventListener("click", () => {
      window.location.href = `/?room=${encodeURIComponent(
        f.room
      )}&partner=${encodeURIComponent(f.username)}`;
    });
    body.appendChild(el);
  });
  if (sidebar && wasCollapsed) sidebar.classList.add("collapsed");
}

function loadSidebar() {
  fetch("/api/friends")
    .then((r) => r.json())
    .then((j) => {
      if (j && j.friends) renderSidebar(j.friends);
    })
    .catch((e) => console.warn("sidebar load failed", e));
}

function timeNow() {
  const d = new Date();
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function avatarFor(name) {
  if (!name) return "A";
  return name
    .trim()
    .split(" ")
    .map((s) => s[0].toUpperCase())
    .slice(0, 2)
    .join("");
}

function addStatus(text) {
  const div = document.createElement("div");
  div.className = "status";
  div.textContent = text;
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addMessageBubble({ username, msg, ts }) {
  const displayName = username || "Anonymous";
  const local =
    ((usernameInput.value && usernameInput.value.trim()) ||
      document.body.dataset.currentUser ||
      "") === displayName;
  const wrapper = document.createElement("div");
  wrapper.className = "bubble" + (local ? " right" : "");

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = avatarFor(displayName);

  const content = document.createElement("div");
  content.className = "content";
  const nameEl = document.createElement("div");
  nameEl.style.fontWeight = "600";
  nameEl.style.marginBottom = "4px";
  nameEl.textContent = displayName;

  const msgEl = document.createElement("div");
  msgEl.textContent = msg;

  const meta = document.createElement("div");
  meta.className = "meta";
  // prefer server timestamp if present
  if (ts) {
    const d = new Date(ts);
    meta.textContent = d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } else {
    meta.textContent = timeNow();
  }

  content.appendChild(nameEl);
  content.appendChild(msgEl);
  content.appendChild(meta);

  wrapper.appendChild(avatar);
  wrapper.appendChild(content);

  messagesDiv.appendChild(wrapper);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

if (joinBtn) {
  joinBtn.addEventListener("click", () => {
    const username =
      (usernameInput && usernameInput.value.trim()) || "Anonymous";
    const room = (roomInput && roomInput.value.trim()) || "main";
    socket.emit("join", { username, room });
    joined = true;
    joinBtn.disabled = true;
    if (leaveBtn) leaveBtn.disabled = false;
  });
}

if (leaveBtn) {
  leaveBtn.addEventListener("click", () => {
    const username =
      (usernameInput && usernameInput.value.trim()) || "Anonymous";
    const room = (roomInput && roomInput.value.trim()) || "main";
    socket.emit("leave", { username, room });
    joined = false;
    if (joinBtn) joinBtn.disabled = false;
    leaveBtn.disabled = true;
  });
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  if (!joined) {
    addStatus("Join a room first.");
    return;
  }
  const username = usernameInput.value.trim() || "Anonymous";
  // prefer injected room (private chat) if present
  const room =
    injectedRoom ||
    (roomInput && roomInput.value && roomInput.value.trim()) ||
    "main";
  const msg = msgInput.value.trim();
  if (!msg) return;
  console.log("[chat] emit message", { username, room, msg });
  socket.emit("message", { username, room, msg });
  msgInput.value = "";
});

socket.on("connect", () => {
  addStatus("Connected to server.");
  console.log("[chat] socket connected id=", socket.id);
  // load friends sidebar for logged-in users
  applyCollapsedState();
  loadSidebar();
  // if server injected a username into the page, auto-join so logged-in users
  // don't need to click a Join button (index.html sets data-current-user)
  const currentUser = document.body.dataset.currentUser || "";
  if (currentUser) {
    const username = currentUser;
    // prefer injected room (private chat) if present
    const room =
      injectedRoom ||
      (roomInput && roomInput.value && roomInput.value.trim()) ||
      "main";
    console.log("[chat] auto-join", { username, room, injectedPartner });
    socket.emit("join", { username, room });
    joined = true;
    if (joinBtn) joinBtn.disabled = true;
    if (leaveBtn) leaveBtn.disabled = false;
  }

  // if a partner is injected, add a small status line
  if (injectedPartner) {
    addStatus(`Private chat with ${injectedPartner}`);
  }
});

socket.on("disconnect", () => {
  addStatus("Disconnected from server.");
});

socket.on("status", (data) => {
  addStatus(data.msg);
});

socket.on("message", (data) => {
  console.log("[chat] received message", data);
  addMessageBubble(data);
  // reload sidebar previews when new messages arrive
  loadSidebar();
});

// history: array of messages from server
socket.on("history", (payload) => {
  console.log("[chat] history", payload);
  const list = payload && payload.messages ? payload.messages : [];
  list.forEach((m) =>
    addMessageBubble({ username: m.username, msg: m.msg, ts: m.ts })
  );
});

// presence list event from server: array of online usernames
socket.on("presence_list", (payload) => {
  try {
    const list = payload && payload.online ? payload.online : payload || [];
    lastPresence = list;
    // re-render sidebar with presence badges if it's loaded
    fetch("/api/friends")
      .then((r) => r.json())
      .then((j) => {
        if (j && j.friends) renderSidebar(j.friends);
      })
      .catch((e) => console.warn("sidebar reload failed", e));
  } catch (e) {
    console.warn("presence_list handler error", e);
  }
});

// apply collapsed state immediately
applyCollapsedState();
