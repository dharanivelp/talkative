(() => {
    const messages = document.getElementById("globalChatMessages");
    const status = document.getElementById("globalChatStatus");
    const guestGate = document.getElementById("globalChatGuestGate");
    const guestMessage = document.getElementById("globalChatGuestMessage");
    const form = document.getElementById("globalChatForm");
    const input = document.getElementById("globalChatInput");
    const sendButton = document.getElementById("globalChatSendButton");
    const MAX_RENDERED_MESSAGES = 100;
    let authenticated = false;
    let previewExpired = false;
    let lastMessageId = 0;
    let initialLoad = true;
    let requestInProgress = false;
    let simulationCursor = null;
    let simulationRequestInProgress = false;
    const simulationEnabled = document.getElementById("globalChat").dataset.simulationEnabled === "true";

    function renderMessage(message, updateCursor = true) {
        const item = document.createElement("li");
        item.className = `global-chat-message${message.mine ? " is-mine" : ""}`;
        const heading = document.createElement("div");
        heading.className = "global-chat-message-heading";
        const name = document.createElement("strong");
        name.className = "global-chat-message-name";
        name.textContent = message.name || "Participant";
        const time = document.createElement("time");
        const created = new Date(message.created_at);
        time.textContent = Number.isNaN(created.valueOf())
            ? ""
            : created.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        heading.append(name, time);
        const text = document.createElement("p");
        text.textContent = message.text;
        item.append(heading, text);
        if (message.simulated) {
            item.dataset.simulationMessage = String(message.id);
        }
        messages.append(item);
        while (messages.children.length > MAX_RENDERED_MESSAGES) {
            messages.firstElementChild.remove();
        }
        messages.scrollTop = messages.scrollHeight;
        if (updateCursor) lastMessageId = Math.max(lastMessageId, Number(message.id) || 0);
    }

    function showGuestPrompt(message) {
        guestMessage.textContent = message;
        guestGate.classList.remove("hidden");
    }

    window.promptGlobalChatLogin = function promptGlobalChatLogin(mode) {
        if (window.matchMedia("(max-width: 760px)").matches) {
            window.setMobileSection("chat");
        }
        if (document.getElementById("login").classList.contains("hidden")) {
            window.show("login");
        }
        window.showAuth(mode);
        document.getElementById(mode === "signup" ? "signupFirstName" : "loginEmail").focus();
    };

    window.refreshGlobalChat = function refreshGlobalChat() {
        authenticated = true;
        previewExpired = false;
        lastMessageId = 0;
        initialLoad = true;
        messages.replaceChildren();
        simulationCursor = null;
        form.classList.remove("hidden");
        guestGate.classList.add("hidden");
        pollGlobalChat();
        if (simulationEnabled) pollGlobalChatSimulation();
    };

    async function pollGlobalChat() {
        if (requestInProgress) return;
        requestInProgress = true;
        try {
            const url = lastMessageId ? `/api/global-chat?after=${lastMessageId}` : "/api/global-chat";
            const response = await fetch(url, { credentials: "same-origin" });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Unable to load global chat.");
            authenticated = Boolean(result.authenticated);
            const wasPreviewExpired = previewExpired;
            previewExpired = Boolean(result.preview_expired);
            if (authenticated) {
                form.classList.remove("hidden");
                guestGate.classList.add("hidden");
            } else {
                if (!previewExpired) form.classList.remove("hidden");
            }
            if (previewExpired) {
                if (!wasPreviewExpired) {
                    messages.replaceChildren();
                }
                form.classList.add("hidden");
                showGuestPrompt("Log in to keep reading global chat.");
            } else {
                for (const message of result.messages || []) renderMessage(message);
                if (initialLoad && messages.childElementCount === 0) {
                    const empty = document.createElement("li");
                    empty.className = "global-chat-empty";
                    empty.textContent = "No messages yet. Start the conversation!";
                    messages.append(empty);
                }
                if ((result.messages || []).length) {
                    const empty = messages.querySelector(".global-chat-empty");
                    if (empty) empty.remove();
                }
                status.textContent = "";
            }
            initialLoad = false;
        } catch (error) {
            status.textContent = error.message;
            console.error("Global chat could not be refreshed", error);
        } finally {
            requestInProgress = false;
        }
    }

    async function pollGlobalChatSimulation() {
        if (!simulationEnabled || simulationRequestInProgress) return;
        simulationRequestInProgress = true;
        try {
            const cursor = simulationCursor === null ? "" : `?after=${simulationCursor}`;
            const response = await fetch(`/api/global-chat/simulation${cursor}`, { credentials: "same-origin" });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Unable to load chat simulation.");
            if (result.reset) {
                messages.querySelectorAll("[data-simulation-message]").forEach((message) => message.remove());
            }
            for (const message of result.messages || []) renderMessage(message, false);
            if ((result.messages || []).length) {
                const empty = messages.querySelector(".global-chat-empty");
                if (empty) empty.remove();
            }
            simulationCursor = Number(result.cursor) || 0;
        } catch (error) {
            status.textContent = error.message;
            console.error("Global chat simulation could not be refreshed", error);
        } finally {
            simulationRequestInProgress = false;
        }
    }

    window.sendGlobalChatMessage = async function sendGlobalChatMessage(event) {
        event.preventDefault();
        if (!authenticated) {
            showGuestPrompt("Please log in to send a message in global chat.");
            return;
        }
        const text = input.value.trim();
        if (!text) return;
        sendButton.disabled = true;
        status.textContent = "";
        try {
            const response = await fetch("/api/global-chat", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text }),
            });
            const result = await response.json();
            if (response.status === 401) {
                authenticated = false;
                showGuestPrompt(result.error || "Please log in to send a message in global chat.");
                return;
            }
            if (!response.ok) throw new Error(result.error || "Unable to send your message.");
            input.value = "";
            await pollGlobalChat();
        } catch (error) {
            status.textContent = error.message;
            console.error("Global chat message could not be sent", error);
        } finally {
            sendButton.disabled = false;
        }
    };

    pollGlobalChat();
    window.setInterval(pollGlobalChat, 2500);
    if (simulationEnabled) {
        pollGlobalChatSimulation();
        window.setInterval(pollGlobalChatSimulation, 1000);
    }
})();
