const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const numberFormat = new Intl.NumberFormat();
let userOffset = 0;
let currentLogType = "activity";
let activeSessionId = "";

async function adminRequest(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken, ...(options.headers || {}) },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Admin request failed");
    return data;
}

function status(message, error = false, target = "adminStatus") {
    const element = document.getElementById(target);
    if (!element) return;
    element.textContent = message;
    element.classList.toggle("error-text", error);
}

function addCell(row, value, className = "") {
    const cell = document.createElement("td");
    cell.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
    if (className) cell.className = className;
    row.append(cell);
    return cell;
}

function button(label, action, value, className = "quiet-button") {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    element.dataset.action = action;
    element.dataset.value = value;
    element.className = className;
    return element;
}

function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function formatDuration(value) {
    if (value === null || value === undefined) return "-";
    const seconds = Math.max(0, Number(value) || 0);
    return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

async function loadDashboard() {
    try {
        const data = await adminRequest(`/admin/api/dashboard?period=${encodeURIComponent(document.getElementById("periodFilter").value)}`);
        document.getElementById("metricActive").textContent = numberFormat.format(data.active_users);
        document.getElementById("metricOnline").textContent = numberFormat.format(data.online_now);
        document.getElementById("metricTotal").textContent = numberFormat.format(data.total_users);
        document.getElementById("metricNew").textContent = numberFormat.format(data.new_users);
        document.getElementById("metricIncidents").textContent = numberFormat.format(data.incidents);
        document.getElementById("metricReports").textContent = numberFormat.format(data.reports);
        const cost = document.getElementById("metricCost");
        if (data.cost_configured) {
            try {
                cost.textContent = new Intl.NumberFormat(undefined, { style: "currency", currency: data.cost_currency }).format(data.cost);
            } catch {
                cost.textContent = `${data.cost_currency} ${Number(data.cost).toFixed(2)}`;
            }
            document.getElementById("metricCostNote").textContent = "Estimated production run cost per day";
        } else {
            cost.textContent = "Not set";
            document.getElementById("metricCostNote").textContent = "Set a daily estimate in Settings";
        }
        document.getElementById("dashboardRange").textContent = `${data.start_day} to ${data.end_day} · UTC`;
        status("");
    } catch (error) {
        status(error.message, true);
    }
}

function renderUser(user) {
    const row = document.createElement("tr");
    const userCell = document.createElement("td");
    const name = document.createElement("strong");
    name.className = "primary-cell";
    name.textContent = user.name;
    const email = document.createElement("span");
    email.className = "secondary-cell";
    email.textContent = user.email;
    userCell.append(name, email);
    row.append(userCell);
    addCell(row, user.user_id);
    addCell(row, user.country_code);
    addCell(row, formatDate(user.created_at));
    addCell(row, formatDuration(user.total_chat_seconds));
    addCell(row, user.reports_received);
    addCell(row, user.admin_blocked ? "Blocked" : "Active", user.admin_blocked ? "status-blocked" : "status-ok");
    const actions = document.createElement("td");
    const group = document.createElement("div");
    group.className = "row-actions";
    group.append(button("View", "user", user.user_id));
    group.append(button("Activity", "activity", user.user_id));
    group.append(button("Reset password", "reset", user.user_id));
    group.append(button(user.admin_blocked ? "Unblock" : "Block", user.admin_blocked ? "unblock" : "block", user.user_id));
    group.append(button("Delete", "delete", user.user_id, "danger-button"));
    actions.append(group);
    row.append(actions);
    return row;
}

async function loadUsers(reset = true) {
    const table = document.getElementById("usersTable");
    if (reset) {
        userOffset = 0;
        table.replaceChildren();
    }
    try {
        const query = new URLSearchParams({ q: document.getElementById("userSearch").value, limit: "50", offset: String(userOffset) });
        const data = await adminRequest(`/admin/api/users?${query}`);
        data.users.forEach((user) => table.append(renderUser(user)));
        if (!userOffset && !data.users.length) {
            const row = document.createElement("tr");
            const cell = addCell(row, "No users found.", "empty-state");
            cell.colSpan = 8;
            table.append(row);
        }
        userOffset += data.users.length;
        document.getElementById("userCount").textContent = `${numberFormat.format(userOffset)} of ${numberFormat.format(data.total)} users`;
        document.getElementById("loadMoreUsers").classList.toggle("hidden", userOffset >= data.total || data.users.length < 50);
    } catch (error) {
        status(error.message, true);
    }
}

async function loadSessions(event) {
    event?.preventDefault();
    const params = new URLSearchParams({
        q: document.getElementById("chatQuery").value,
        ip: document.getElementById("chatIp").value,
        start: document.getElementById("chatStart").value,
        end: document.getElementById("chatEnd").value,
    });
    const body = document.getElementById("sessionsTable");
    body.replaceChildren();
    try {
        const data = await adminRequest(`/admin/api/sessions?${params}`);
        if (!data.sessions.length) {
            const row = document.createElement("tr");
            const cell = addCell(row, "No chat records found.", "empty-state");
            cell.colSpan = 7;
            body.append(row);
            return;
        }
        data.sessions.forEach((item) => {
            const row = document.createElement("tr");
            addCell(row, item.session_id);
            addCell(row, `${item.user_a_id} · ${item.ip_a || "IP unavailable"}`);
            addCell(row, `${item.user_b_id} · ${item.ip_b || "IP unavailable"}`);
            addCell(row, formatDate(item.started_at));
            addCell(row, formatDate(item.ended_at));
            addCell(row, formatDuration(item.duration_seconds));
            const actions = document.createElement("td");
            actions.append(button("View transcript", "transcript", item.session_id));
            row.append(actions);
            body.append(row);
        });
    } catch (error) {
        status(error.message, true);
    }
}

async function loadInbox() {
    const table = document.getElementById("inboxTable");
    table.replaceChildren();
    status("Loading support inbox…", false, "inboxStatus");
    try {
        const data = await adminRequest("/admin/api/inbox");
        if (!data.messages.length) {
            const row = document.createElement("tr");
            const cell = addCell(row, "Inbox is empty.", "empty-state");
            cell.colSpan = 5;
            table.append(row);
        }
        data.messages.forEach((message) => {
            const row = document.createElement("tr");
            addCell(row, formatDate(message.date));
            addCell(row, message.from);
            addCell(row, message.subject);
            addCell(row, message.is_read ? "Read" : "Unread");
            const actions = document.createElement("td");
            actions.append(button("View", "inbox-message", message.uid));
            row.append(actions);
            table.append(row);
        });
        status(data.has_more ? "Showing the 50 most recent messages." : "", false, "inboxStatus");
    } catch (error) {
        status(error.message, true, "inboxStatus");
    }
}

async function showInboxMessage(uid) {
    try {
        const data = await adminRequest(`/admin/api/inbox/${encodeURIComponent(uid)}`);
        document.getElementById("inboxMessageSubject").textContent = data.subject || "(no subject)";
        const meta = document.getElementById("inboxMessageMeta");
        meta.replaceChildren();
        [["From", data.from], ["To", data.to], ["Date", formatDate(data.date)]].forEach(([label, value]) => detail(meta, label, value));
        document.getElementById("inboxMessageBody").textContent = data.body || "(This message has no readable text body.)";
        document.getElementById("inboxMessageDialog").showModal();
    } catch (error) {
        status(error.message, true, "inboxStatus");
    }
}

function detail(parent, label, value) {
    const item = document.createElement("div");
    item.className = "detail-item";
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
    item.append(term, description);
    parent.append(item);
}

async function showUser(userId, focusActivity = false) {
    try {
        const data = await adminRequest(`/admin/api/users/${encodeURIComponent(userId)}`);
        const details = document.getElementById("userDetails");
        details.replaceChildren();
        const fields = [["User ID", "user_id"], ["Name", "name"], ["Username", "username"], ["Email", "email"], ["Phone", "phone_number"], ["Country", "country_code"], ["Date of birth", "date_of_birth"], ["Gender", "gender"], ["Created", "created_at"], ["Last active", "last_active_date"], ["Chat time", "total_chat_seconds"], ["Reports", "reports_received"], ["Moderation events", "moderation_events"], ["Profile bio", "bio"], ["Profession", "profession"], ["Education", "education"], ["Location", "location"]];
        fields.forEach(([label, key]) => detail(details, label, key === "created_at" ? formatDate(data.user[key]) : key === "total_chat_seconds" ? formatDuration(data.user[key]) : data.user[key]));
        const activity = document.getElementById("userActivity");
        activity.replaceChildren();
        data.activity.forEach((entry) => {
            const row = document.createElement("tr");
            addCell(row, formatDate(entry.occurred_at));
            addCell(row, entry.event.replaceAll("_", " "));
            addCell(row, `${entry.actor_role || "unknown"}${entry.actor_id ? ` · ${entry.actor_id}` : ""}`);
            addCell(row, entry.session_id);
            addCell(row, entry.ip);
            activity.append(row);
        });
        if (!data.activity.length) {
            const row = document.createElement("tr");
            const cell = addCell(row, "No activity history.", "empty-state");
            cell.colSpan = 5;
            activity.append(row);
        }
        document.getElementById("userDialog").showModal();
        if (focusActivity) document.getElementById("userActivity").scrollIntoView({ block: "nearest" });
    } catch (error) {
        status(error.message, true);
    }
}

async function resetPassword(userId) {
    if (!window.confirm("Issue a one-time temporary password for this user?")) return;
    try {
        const data = await adminRequest(`/admin/api/users/${encodeURIComponent(userId)}/reset-password`, { method: "POST" });
        document.getElementById("temporaryPassword").value = data.temporary_password;
        status("Shown once; deliver securely, and close this dialog when finished.", false, "resetStatus");
        document.getElementById("resetDialog").showModal();
    } catch (error) {
        status(error.message, true);
    }
}

async function createUser(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    try {
        const result = await adminRequest("/admin/api/users", { method: "POST", body: JSON.stringify(data) });
        document.getElementById("temporaryPassword").value = result.temporary_password;
        document.getElementById("resetStatus").textContent = "Development verification is active. Deliver the temporary password securely; the account is created after code verification.";
        document.getElementById("createUserDialog").close();
        document.getElementById("resetDialog").showModal();
        form.reset();
        loadUsers(true);
        loadDashboard();
    } catch (error) {
        status(error.message, true, "createUserStatus");
    }
}

async function changeUserState(userId, action) {
    const labels = { block: "Block this user? They will be signed out of active chat.", unblock: "Unblock this user?", delete: "Permanently delete this user and their profile?" };
    if (!window.confirm(labels[action])) return;
    try {
        const method = action === "delete" ? "DELETE" : "POST";
        const suffix = action === "delete" ? "" : `/${action}`;
        await adminRequest(`/admin/api/users/${encodeURIComponent(userId)}${suffix}`, { method });
        await loadUsers(true);
        await loadDashboard();
    } catch (error) {
        status(error.message, true);
    }
}

function openTranscriptKey(sessionId) {
    activeSessionId = sessionId;
    document.getElementById("transcriptKey").value = "";
    document.getElementById("transcriptError").textContent = "";
    document.getElementById("transcriptKeyDialog").showModal();
}

async function loadTranscript(event) {
    event.preventDefault();
    const input = document.getElementById("transcriptKey");
    const error = document.getElementById("transcriptError");
    try {
        const data = await adminRequest(`/admin/api/transcripts/${encodeURIComponent(activeSessionId)}`, { method: "POST", body: JSON.stringify({ key: input.value }) });
        input.value = "";
        document.getElementById("transcriptKeyDialog").close();
        const meta = document.getElementById("transcriptMeta");
        meta.replaceChildren();
        [["Chat ID", data.session_id], ["Started", formatDate(data.started_at)], ["Ended", formatDate(data.ended_at)], ["Participant 1", `${data.user_a_id} · ${data.ip_a || "IP unavailable"}`], ["Participant 2", `${data.user_b_id} · ${data.ip_b || "IP unavailable"}`], ["Duration", formatDuration(data.duration_seconds)]].forEach(([label, value]) => detail(meta, label, value));
        const activities = document.getElementById("transcriptActivities");
        activities.replaceChildren();
        data.activities.forEach((item) => {
            const line = document.createElement("li");
            line.textContent = `${formatDate(item.occurred_at)} · ${item.event.replaceAll("_", " ")} · ${item.user_id || "system"}`;
            activities.append(line);
        });
        const messages = document.getElementById("transcriptMessages");
        messages.replaceChildren();
        data.transcript.forEach((message) => {
            const line = document.createElement("li");
            line.textContent = `${message.sender_user_id}: ${message.text}`;
            messages.append(line);
        });
        document.getElementById("transcriptDialog").showModal();
    } catch (requestError) {
        input.value = "";
        error.textContent = requestError.message;
    }
}

async function loadSettings() {
    try {
        const data = await adminRequest("/admin/api/settings");
        document.getElementById("costPerDay").value = data.company_cost_per_day;
        document.getElementById("costCurrency").value = data.company_cost_currency;
        document.getElementById("logRetention").value = data.activity_log_retention_days;
        document.getElementById("transcriptKeyStatus").textContent = data.transcript_key_configured ? "Configured on the server." : "Not configured; transcript viewing is disabled.";
    } catch (error) {
        status(error.message, true);
    }
}

async function saveSettings(event) {
    event.preventDefault();
    try {
        await adminRequest("/admin/api/settings", { method: "PUT", body: JSON.stringify({ company_cost_per_day: document.getElementById("costPerDay").value, company_cost_currency: document.getElementById("costCurrency").value, activity_log_retention_days: document.getElementById("logRetention").value }) });
        status("Settings saved.", false, "settingsStatus");
        loadDashboard();
    } catch (error) {
        status(error.message, true, "settingsStatus");
    }
}

async function loadLogs() {
    const head = document.getElementById("logsHead");
    const body = document.getElementById("logsTable");
    head.replaceChildren();
    body.replaceChildren();
    const production = currentLogType === "production";
    const columns = production ? ["Time", "Level", "Message", "IP"] : ["Time", "Event", "Actor", "User ID", "Chat ID", "IP"];
    const header = document.createElement("tr");
    columns.forEach((title) => { const th = document.createElement("th"); th.textContent = title; header.append(th); });
    head.append(header);
    const params = new URLSearchParams({ q: document.getElementById("logSearch").value });
    if (production) params.set("level", document.getElementById("logLevel").value);
    try {
        const data = await adminRequest(`/admin/api/${production ? "logs" : "activity"}?${params}`);
        const rows = production ? data.logs : data.events;
        rows.forEach((item) => {
            const row = document.createElement("tr");
            addCell(row, formatDate(item.occurred_at));
            if (production) {
                addCell(row, item.level);
                addCell(row, item.message);
                addCell(row, item.ip);
            } else {
                addCell(row, item.event.replaceAll("_", " "));
                addCell(row, `${item.actor_role || "unknown"}${item.actor_id ? ` · ${item.actor_id}` : ""}`);
                addCell(row, item.user_id);
                addCell(row, item.session_id);
                addCell(row, item.ip);
            }
            body.append(row);
        });
        if (!rows.length) {
            const row = document.createElement("tr");
            const cell = addCell(row, "No logs found.", "empty-state");
            cell.colSpan = columns.length;
            body.append(row);
        }
    } catch (error) {
        status(error.message, true);
    }
}

document.querySelectorAll(".admin-tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".admin-tab").forEach((item) => {
        const selected = item === tab;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-selected", String(selected));
    });
    document.querySelectorAll(".admin-panel").forEach((panel) => panel.classList.toggle("hidden", panel.id !== tab.dataset.panel));
}));
document.querySelectorAll(".log-tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".log-tab").forEach((item) => {
        const selected = item === tab;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-selected", String(selected));
    });
    currentLogType = tab.dataset.log;
    loadLogs();
}));
document.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    const value = control.dataset.value;
    if (control.dataset.action === "user") showUser(value);
    if (control.dataset.action === "activity") showUser(value, true);
    if (control.dataset.action === "reset") resetPassword(value);
    if (["block", "unblock", "delete"].includes(control.dataset.action)) changeUserState(value, control.dataset.action);
    if (control.dataset.action === "transcript") openTranscriptKey(value);
    if (control.dataset.action === "inbox-message") showInboxMessage(value);
});
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));
document.getElementById("periodFilter").addEventListener("change", loadDashboard);
document.getElementById("searchUsers").addEventListener("click", () => loadUsers(true));
document.getElementById("userSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); loadUsers(true); } });
document.getElementById("loadMoreUsers").addEventListener("click", () => loadUsers(false));
document.getElementById("chatSearchForm").addEventListener("submit", loadSessions);
document.getElementById("refreshInbox").addEventListener("click", loadInbox);
document.getElementById("createUserButton").addEventListener("click", () => document.getElementById("createUserDialog").showModal());
document.getElementById("createUserForm").addEventListener("submit", createUser);
document.getElementById("settingsForm").addEventListener("submit", saveSettings);
document.getElementById("transcriptKeyForm").addEventListener("submit", loadTranscript);
document.getElementById("searchLogs").addEventListener("click", loadLogs);
document.getElementById("logSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); loadLogs(); } });
document.getElementById("copyTemporaryPassword").addEventListener("click", async () => {
    try {
        await navigator.clipboard.writeText(document.getElementById("temporaryPassword").value);
        status("Copied. Close this dialog when finished.", false, "resetStatus");
    } catch {
        status("Clipboard blocked. Select and copy the password securely.", true, "resetStatus");
    }
});
document.getElementById("resetDialog").addEventListener("close", () => {
    document.getElementById("temporaryPassword").value = "";
    document.getElementById("resetStatus").textContent = "";
});
document.querySelector('[data-panel="inboxPanel"]').addEventListener("click", loadInbox, { once: true });

loadDashboard();
loadUsers();
loadSettings();