function setTheme(theme, save = true) {
    const dark = theme === "dark";
    const label = dark ? "Switch to light theme" : "Switch to dark theme";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.querySelectorAll(".theme-button").forEach((button) => {
        button.setAttribute("aria-pressed", String(dark));
        button.setAttribute("aria-label", label);
        button.title = label;
    });
    if (save) {
        try {
            localStorage.setItem("talkative-theme", dark ? "dark" : "light");
        } catch {}
    }
}

function toggleTheme() {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
}

setTheme(document.documentElement.dataset.theme || "light", false);

async function loadSignedInHeader() {
    try {
        const response = await fetch("/api/me");
        if (!response.ok) return;
        document.getElementById("accountButton").classList.remove("hidden");
        document.getElementById("onlineBadge").classList.remove("hidden");
        const onlineResponse = await fetch("/api/online");
        if (onlineResponse.ok) {
            const data = await onlineResponse.json();
            const badge = document.getElementById("onlineBadge");
            document.getElementById("onlineCount").textContent = data.demo ? `${data.online} online` : data.online;
            badge.setAttribute(
                "aria-label",
                data.demo ? `Demo count, not actual users: ${data.online}` : `${data.online} users online`,
            );
        }
    } catch {}
}

loadSignedInHeader();
